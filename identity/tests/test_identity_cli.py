"""Acceptance through the operator/creator CLI and the HTTP boundary."""
import json
import http.cookiejar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import ssl
import time
import uuid
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[2]


class IdentityAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = self.home / 'server.json'
        self.config.write_text(json.dumps({
            'origin': 'https://cloud.example.test',
            'google_client_id': 'fixture-client', 'google_client_secret': 'fixture-secret',
            'state_directory': str(self.home / 'server'),
        }))
        self.config.chmod(0o600)

    def operator(self, *args):
        return subprocess.run([sys.executable, '-m', 'identity.server', '--config',
                               str(self.config), *args], cwd=ROOT, capture_output=True, text=True)

    def test_bootstrap_is_explicit_and_cannot_replace_administrator(self):
        first = self.operator('bootstrap', 'admin@example.test')
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(json.loads(first.stdout)['data']['administrator'])
        repeated = self.operator('bootstrap', 'admin@example.test')
        self.assertEqual(json.loads(first.stdout), json.loads(repeated.stdout))
        replacement = self.operator('bootstrap', 'other@example.test')
        self.assertEqual(replacement.returncode, 5)
        self.assertEqual(json.loads(replacement.stdout)['error']['code'], 'REQUEST_CONFLICT')

    def start_platform(self):
        from identity.http import create_server
        from identity.google import Google

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.signing_key = key
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
                .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), False)
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
                .sign(key, hashes.SHA256()))
        cert_path, key_path = self.home / 'cert.pem', self.home / 'key.pem'
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert_path, key_path)
        self.client_tls = ssl.create_default_context(cafile=str(cert_path))
        self.identity = {'sub': 'admin-sub', 'email': 'admin@example.test',
                         'email_verified': True, 'name': 'Admin'}
        self.claim_overrides = {}
        codes = {}
        owner = self

        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path == '/keys':
                    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(json.dumps({'keys': [{**jwk, 'kid': 'fixture'}]}).encode())
                    return
                query = urllib.parse.parse_qs(parsed.query)
                code = str(len(codes))
                codes[code] = query
                self.send_response(302)
                self.send_header('Location', query['redirect_uri'][0] + '?' + urllib.parse.urlencode({
                    'code': code, 'state': query['state'][0]}))
                self.end_headers()

            def do_POST(self):
                body = urllib.parse.parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
                query = codes.pop(body['code'][0])
                import base64
                import hashlib
                challenge = base64.urlsafe_b64encode(hashlib.sha256(body['code_verifier'][0].encode()).digest()).rstrip(b'=').decode()
                assert challenge == query['code_challenge'][0]
                claims = {'iss': 'https://accounts.google.com', 'aud': 'fixture-client',
                          'iat': int(time.time()), 'exp': int(time.time()) + 300,
                          'nonce': query['nonce'][0], **owner.identity, **owner.claim_overrides}
                token = jwt.encode(claims, owner.signing_key, algorithm='RS256', headers={'kid': 'fixture'})
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({'id_token': token}).encode())

        provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        provider.socket = tls.wrap_socket(provider.socket, server_side=True)
        provider_origin = f'https://localhost:{provider.server_port}'
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.client_tls))
        google = Google('fixture-client', 'fixture-secret',
                        authorization_endpoint=provider_origin + '/authorize',
                        token_endpoint=provider_origin + '/token', jwks_uri=provider_origin + '/keys',
                        opener=opener)
        config = json.loads(self.config.read_text())
        server = create_server(config, port=0, google=google)
        self.platform_server, self.server_tls = server, tls
        self.endpoint = f'https://localhost:{server.server_port}'
        server.application.origin = self.endpoint
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        for service in (provider, server):
            threading.Thread(target=service.serve_forever, daemon=True).start()
            self.addCleanup(service.server_close)
            self.addCleanup(service.shutdown)
        self.env = {**os.environ, 'HOME': str(self.home),
                    'XDG_STATE_HOME': str(self.home / 'state'),
                    'XDG_CONFIG_HOME': str(self.home / 'config'),
                    'SSL_CERT_FILE': str(cert_path), 'SMALL_CLOUD_ENDPOINT': self.endpoint,
                    'PYTHONPATH': os.pathsep.join([str(ROOT), os.environ.get('PYTHONPATH', '')]),
                    'PYTHON_KEYRING_BACKEND': 'keyring.backends.fail.Keyring'}
        self.browser = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self.client_tls),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def restart_platform(self):
        from identity.http import create_server
        previous = self.platform_server
        previous.shutdown()
        previous.server_close()
        server = create_server(json.loads(self.config.read_text()), port=previous.server_port,
                               google=previous.application.google)
        server.application.origin = self.endpoint
        server.socket = self.server_tls.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.platform_server = server

    def http(self, path, body=None, token=None, browser=None, headers=None):
        request_headers = dict(headers or {})
        if body is not None:
            request_headers['Content-Type'] = 'application/json'
        if token:
            request_headers['Authorization'] = 'Bearer ' + token
        request = urllib.request.Request(self.endpoint + path,
                    data=None if body is None else json.dumps(body).encode(), headers=request_headers)
        opener = browser or urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.client_tls))
        try:
            response = opener.open(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, response.read().decode()

    def approve(self, url):
        import re
        with self.browser.open(url, timeout=5) as response:
            html = response.read().decode()
            # Fetch's Origin-header algorithm suppresses Origin on no-referrer form POSTs.
            form_origin = 'null' if response.headers.get('Referrer-Policy') == 'no-referrer' else self.endpoint
        csrf = re.search(r'name="csrf" value="([^"]+)"', html).group(1)
        code = re.search(r'name="code" value="([^"]+)"', html).group(1)
        request = urllib.request.Request(self.endpoint + '/auth/approve',
            urllib.parse.urlencode({'csrf': csrf, 'code': code}).encode(),
            headers={'Origin': form_origin, 'Content-Type': 'application/x-www-form-urlencoded'})
        with self.browser.open(request, timeout=5) as response:
            self.assertEqual(response.status, 200)

    def cli(self, *args, cwd=ROOT):
        return subprocess.run([sys.executable, '-m', 'identity.cli', '--json', *args],
                              cwd=cwd, env=self.env, capture_output=True, text=True, timeout=10)

    def login(self, cwd=ROOT):
        process = subprocess.Popen([sys.executable, '-m', 'identity.cli', '--json',
                                    'auth', 'login', '--no-browser'], cwd=cwd, env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        url = None
        for _ in range(3):
            line = process.stderr.readline()
            if line.startswith('Open '):
                url = line.split()[1]
                break
        self.assertIsNotNone(url)
        self.approve(url)
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stderr + stdout)
        return json.loads(stdout)['data']

    def test_administrator_browser_login_retained_cli_and_revocation(self):
        self.assertEqual(self.operator('bootstrap', 'admin@example.test').returncode, 0)
        self.start_platform()
        status, _ = self.http('/api/auth/status')
        self.assertEqual(status, 401)
        logged_in = self.login()
        self.assertEqual(logged_in['roles'], ['member', 'administrator'])
        retained = self.cli('auth', 'status')
        self.assertEqual(json.loads(retained.stdout)['data'], logged_in)
        logged_out = self.cli('auth', 'logout')
        self.assertEqual(logged_out.returncode, 0, logged_out.stdout)
        self.assertEqual(self.cli('auth', 'status').returncode, 3)

    def http_login(self, email, subject=None):
        import secrets
        self.identity = {'sub': subject or email, 'email': email, 'email_verified': True, 'name': email.split('@')[0]}
        poll_secret = secrets.token_urlsafe(32)
        _, raw = self.http('/api/auth/login', {'poll_secret': poll_secret})
        login = json.loads(raw)['data']
        self.approve(login['verification_url'])
        status, raw = self.http('/api/auth/poll', {'poll_secret': poll_secret})
        self.assertEqual(status, 200, raw)
        return json.loads(raw)['data']

    def test_admission_creator_authority_and_five_creator_boundary(self):
        self.operator('bootstrap', 'admin@example.test')
        self.start_platform()
        self.login()
        admitted = self.cli('workspace', 'member', 'add', 'member@example.test')
        self.assertEqual(admitted.returncode, 0, admitted.stdout)
        member_id = json.loads(admitted.stdout)['data']['user_id']
        member = self.http_login('member@example.test')
        self.assertEqual(member['roles'], ['member'])
        status, _ = self.http('/api/admin/creator/grant', {'user_id': member_id}, member['credential'],
                             headers={'X-Request-ID': str(uuid.uuid4())})
        self.assertEqual(status, 403)
        granted = self.cli('workspace', 'creator', 'grant', member_id)
        self.assertEqual(granted.returncode, 0, granted.stdout)
        _, raw = self.http('/api/auth/status', token=member['credential'])
        self.assertEqual(json.loads(raw)['data']['roles'], ['member', 'creator'])
        for number in range(2, 7):
            added = self.cli('workspace', 'member', 'add', f'creator{number}@example.test')
            user_id = json.loads(added.stdout)['data']['user_id']
            self.http_login(f'creator{number}@example.test')
            result = self.cli('workspace', 'creator', 'grant', user_id)
            self.assertEqual(result.returncode, 0 if number <= 5 else 5, result.stdout)
        self.assertEqual(self.cli('workspace', 'creator', 'grant', member_id).returncode, 0)
        self.env['XDG_STATE_HOME'] = str(self.home / 'member-state')
        self.identity = {'sub': 'member@example.test', 'email': 'member@example.test',
                         'email_verified': True, 'name': 'Member'}
        self.assertEqual(self.login()['roles'], ['member', 'creator'])
        self.assertEqual(self.cli('workspace', 'member', 'add', 'intruder@example.test').returncode, 4)

    def test_unadmitted_unverified_and_invalid_google_tokens_are_denied(self):
        self.operator('bootstrap', 'admin@example.test')
        self.start_platform()
        for email, overrides in [
            ('unadmitted@example.test', {}),
            ('admin@example.test', {'email_verified': False}),
            ('admin@example.test', {'iss': 'https://attacker.example'}),
            ('admin@example.test', {'aud': 'other-client'}),
            ('admin@example.test', {'exp': int(time.time()) - 10}),
            ('admin@example.test', {'nonce': 'wrong'}),
        ]:
            with self.subTest(email=email, claims=overrides):
                self.claim_overrides = overrides
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.http_login(email)
                self.assertEqual(caught.exception.code, 403 if not overrides else 401)
        self.claim_overrides = {}
        self.signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.http_login('admin@example.test')
        self.assertEqual(caught.exception.code, 401)

    def test_bound_subject_keeps_ownership_when_email_changes(self):
        self.operator('bootstrap', 'admin@example.test')
        self.start_platform()
        first = self.http_login('admin@example.test', 'stable-google-subject')
        changed = self.http_login('renamed@example.test', 'stable-google-subject')
        self.assertEqual(first['user']['id'], changed['user']['id'])
        self.assertEqual(changed['user']['email'], 'renamed@example.test')
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.http_login('admin@example.test', 'replacement-google-subject')
        self.assertEqual(caught.exception.code, 403)

    def test_revocation_rejects_retained_credentials_and_replays_are_safe(self):
        self.operator('bootstrap', 'admin@example.test')
        self.start_platform()
        self.login()
        second = self.http_login('admin@example.test', 'admin-sub')
        request_id = str(uuid.uuid4())
        headers = {'X-Request-ID': request_id}
        status, receipt = self.http('/api/auth/revoke', {}, second['credential'], headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(self.http('/api/auth/revoke', {}, second['credential'], headers=headers), (status, receipt))
        self.assertEqual(self.http('/api/auth/status', token=second['credential'])[0], 401)
        self.assertEqual(self.cli('auth', 'status').returncode, 3)
        self.assertEqual(self.cli('auth', 'logout').returncode, 0)

    def test_browser_approval_requires_csrf_and_poll_is_single_use(self):
        import secrets
        self.operator('bootstrap', 'admin@example.test')
        self.start_platform()
        secret = secrets.token_urlsafe(32)
        _, raw = self.http('/api/auth/login', {'poll_secret': secret})
        login = json.loads(raw)['data']
        with self.browser.open(login['verification_url']) as response:
            approval_html = response.read().decode()
            self.assertIn('Approve CLI sign-in', approval_html)
            self.assertEqual(response.headers['Referrer-Policy'], 'strict-origin')
        import re
        csrf = re.search(r'name="csrf" value="([^"]+)"', approval_html).group(1)
        for untrusted_origin in ('null', 'https://untrusted.example'):
            status, _ = self.http('/auth/approve', {'code': login['user_code'], 'csrf': csrf},
                                  browser=self.browser, headers={'Origin': untrusted_origin})
            self.assertEqual(status, 403)
        status, _ = self.http('/auth/approve', {'code': login['user_code'], 'csrf': 'forged'},
                              browser=self.browser, headers={'Origin': self.endpoint})
        self.assertEqual(status, 403)
        self.approve(self.endpoint + '/auth/approval?code=' + login['user_code'])
        status, raw = self.http('/api/auth/poll', {'poll_secret': secret})
        self.assertEqual(status, 200)
        token = json.loads(raw)['data']['credential']
        self.assertEqual(self.http('/api/auth/poll', {'poll_secret': secret})[0], 401)
        status, raw = self.http('/api/auth/status', token=token)
        self.assertEqual(status, 200)
        self.assertNotIn(token, raw)

    def test_actor_scoped_request_id_deduplicates_and_rejects_changed_inputs(self):
        self.operator('bootstrap', 'admin@example.test')
        self.start_platform()
        admin = self.http_login('admin@example.test')
        headers = {'X-Request-ID': str(uuid.uuid4())}
        args = ('/api/admin/member/add', {'email': 'member@example.test'}, admin['credential'])
        first = self.http(*args, headers=headers)
        self.assertEqual(first[0], 200)
        self.assertEqual(self.http(*args, headers=headers), first)
        self.assertEqual(self.http(args[0], {'email': 'other@example.test'}, admin['credential'], headers=headers)[0], 409)

    def test_help_precedes_invalid_arguments_and_needs_no_endpoint(self):
        result = subprocess.run([sys.executable, '-m', 'identity.cli', 'nonsense', '--help'],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('small-cloud', result.stdout)

    def test_unsafe_saved_credentials_are_rejected_without_printing_values(self):
        self.operator('bootstrap', 'admin@example.test')
        self.start_platform()
        self.login()
        saved = next((self.home / 'state/small-cloud').glob('*.json'))
        secret = json.loads(saved.read_text())['credential']
        saved.chmod(0o644)
        refused = self.cli('auth', 'status')
        self.assertEqual(refused.returncode, 2)
        self.assertNotIn(secret, refused.stdout + refused.stderr)
        saved.chmod(0o600)
        target = saved.with_suffix('.saved')
        saved.rename(target)
        saved.symlink_to(target)
        self.assertEqual(self.cli('auth', 'status').returncode, 2)

    def test_authentication_from_home_uses_default_external_state_storage(self):
        self.operator('bootstrap', 'admin@example.test')
        self.start_platform()
        self.env.pop('XDG_STATE_HOME')
        status = self.cli('auth', 'status', cwd=self.home)
        self.assertEqual(status.returncode, 3, status.stdout)
        logged_in = self.login(cwd=self.home)
        status = self.cli('auth', 'status', cwd=self.home)
        self.assertEqual(status.returncode, 0, status.stdout)
        self.assertEqual(json.loads(status.stdout)['data'], logged_in)

    def test_project_credential_storage_is_rejected_even_from_another_directory(self):
        self.start_platform()
        for marker in ('git-directory', 'git-worktree', 'dockerfile'):
            with self.subTest(marker=marker):
                project = self.home / marker
                project.mkdir()
                if marker == 'git-directory':
                    (project / '.git').mkdir()
                elif marker == 'git-worktree':
                    (project / '.git').write_text('gitdir: /unused-fixture-path')
                else:
                    (project / 'Dockerfile').write_text('FROM scratch\n')
                state = project / 'state'
                self.env['XDG_STATE_HOME'] = str(state)
                result = self.cli('auth', 'status', cwd=ROOT)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertEqual(json.loads(result.stdout)['error']['message'],
                                 'Credential storage must be outside the source folder.')
                self.assertFalse((state / 'small-cloud').exists())

    def test_competing_grants_cannot_exceed_five_creators(self):
        from concurrent.futures import ThreadPoolExecutor
        self.operator('bootstrap', 'admin@example.test')
        self.start_platform()
        admin = self.http_login('admin@example.test')

        def grant(user_id):
            return self.http('/api/admin/creator/grant', {'user_id': user_id}, admin['credential'],
                             headers={'X-Request-ID': str(uuid.uuid4())})[0]

        candidates = []
        for number in range(6):
            email = f'candidate{number}@example.test'
            self.http('/api/admin/member/add', {'email': email}, admin['credential'],
                      headers={'X-Request-ID': str(uuid.uuid4())})
            member = self.http_login(email)
            if number < 4:
                self.assertEqual(grant(member['user']['id']), 200)
            else:
                candidates.append(member['user']['id'])
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(grant, candidates)), [200, 409])

    def test_login_and_credential_expiry(self):
        import secrets
        from unittest.mock import patch
        self.operator('bootstrap', 'admin@example.test')
        self.start_platform()
        admin = self.http_login('admin@example.test')
        poll_secret = secrets.token_urlsafe(32)
        self.http('/api/auth/login', {'poll_secret': poll_secret})
        now = time.time()
        with patch('identity.store.time.time', return_value=now + 601):
            self.assertEqual(self.http('/api/auth/poll', {'poll_secret': poll_secret})[0], 401)
        with patch('identity.store.time.time', return_value=now + 2592001):
            self.assertEqual(self.http('/api/auth/status', token=admin['credential'])[0], 401)


if __name__ == '__main__':
    unittest.main()
