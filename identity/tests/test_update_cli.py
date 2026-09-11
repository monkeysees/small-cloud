"""Explicit updates through the CLI and a controlled HTTPS artifact service."""
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import signal
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


class UpdateAcceptance(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.installed = self.home / 'installed bin' / 'small-cloud'
        self.installed.parent.mkdir()
        fixture = os.environ.get('SMALL_CLOUD_TEST_BINARY')
        command = [fixture] if fixture else [sys.executable, '-m', 'identity.tests.cli']
        version = subprocess.run([*command, '--version'], capture_output=True, text=True,
                                 env={**os.environ, 'SMALL_CLOUD_TEST_ORIGIN': 'https://localhost'}, timeout=30)
        self.assertEqual(version.returncode, 0, version.stderr)
        self.version = version.stdout.strip().removeprefix('small-cloud ')
        if fixture:
            shutil.copy2(fixture, self.installed)
        else:
            self.installed.write_text(f'#!/bin/sh\necho "small-cloud {self.version}"\n')
            self.installed.chmod(0o755)
        self.original = self.installed.read_bytes()
        self.candidate = b'#!/bin/sh\necho "small-cloud 999.0.0"\n'
        self.paths = []
        self.bad_checksum = False
        self.download_failure = None
        self.download_started = threading.Event()
        self.release_download = threading.Event()
        system = {'Linux': 'linux', 'Darwin': 'macos'}[platform.system()]
        arch = {'x86_64': 'x86_64', 'aarch64': 'arm64', 'arm64': 'arm64'}[platform.machine()]
        self.asset = f'small-cloud-{system}-{arch}'
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
                .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), False)
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
                .sign(key, hashes.SHA256()))
        cert_path, key_path = self.home / 'ca.pem', self.home / 'key.pem'
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        owner = self

        class Downloads(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                owner.paths.append(self.path)
                if owner.download_failure == 'wait':
                    owner.download_started.set()
                    owner.release_download.wait(180)
                    return
                if owner.download_failure == 'trickle':
                    self.wfile.write(b'HTTP/1.1 200 OK\r\nX-Slow: ')
                    owner.download_started.set()
                    while not owner.release_download.wait(1):
                        try:
                            self.wfile.write(b'x')
                        except OSError:
                            break
                    return
                if owner.download_failure == 'redirect':
                    self.send_response(302)
                    self.send_header('Location', 'http://localhost/unsafe-download')
                    self.end_headers()
                    return
                if owner.download_failure == 'unavailable':
                    self.send_error(503)
                    return
                if self.path == '/cli/releases/latest/' + owner.asset + '.sha256':
                    checksum = '0' * 64 if owner.bad_checksum else hashlib.sha256(owner.candidate).hexdigest()
                    body = f'{checksum}  {owner.asset}\n'.encode()
                elif self.path == '/cli/releases/latest/' + owner.asset:
                    body = owner.candidate
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(body) + (10 if owner.download_failure == 'truncated' else 0)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(('localhost', 0), Downloads)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert_path, key_path)
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.environment = {**os.environ, 'HOME': str(self.home),
            'XDG_STATE_HOME': str(self.home / 'state'), 'XDG_CONFIG_HOME': str(self.home / 'config'),
            'SMALL_CLOUD_TEST_ORIGIN': f'https://localhost:{server.server_port}',
            'SMALL_CLOUD_TEST_EXECUTABLE': str(self.installed), 'SSL_CERT_FILE': str(cert_path)}
        for name in ('.profile', '.bashrc', '.zshrc'):
            (self.home / name).write_text('# preserved\n')

    def cli(self, *args):
        command = ([str(self.installed)] if os.environ.get('SMALL_CLOUD_TEST_BINARY') else
                   [sys.executable, '-m', 'identity.tests.cli'])
        result = subprocess.run([*command, *args], env=self.environment,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45)
        self.assertFalse((self.home / 'state').exists())
        self.assertFalse((self.home / 'config').exists())
        for name in ('.profile', '.bashrc', '.zshrc'):
            self.assertEqual((self.home / name).read_text(), '# preserved\n')
        return result

    def test_explicit_update_replaces_executable_and_reports_versions_without_login(self):
        result = self.cli('update', '--json', '--no-input')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertIsNone(report['request_id'])
        self.assertEqual(report['data']['outcome'], 'updated')
        self.assertEqual(report['data']['installed_version'], self.version)
        self.assertEqual(report['data']['resulting_version'], '999.0.0')
        self.assertEqual(self.installed.read_bytes(), self.candidate)
        started = subprocess.run([str(self.installed), '--version'], capture_output=True, text=True)
        self.assertEqual(started.stdout.strip(), 'small-cloud 999.0.0')
        self.assertEqual(started.returncode, 0)
        self.assertEqual(set(self.paths), {'/cli/releases/latest/' + self.asset,
                                        '/cli/releases/latest/' + self.asset + '.sha256'})

    def test_current_release_does_not_rewrite_or_download_executable(self):
        self.candidate = self.original
        before = self.installed.stat()
        result = self.cli('update', '--json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)['data']
        self.assertEqual(data['outcome'], 'already_current')
        self.assertEqual(data['installed_version'], data['resulting_version'])
        self.assertEqual(self.installed.stat().st_ino, before.st_ino)
        self.assertEqual(self.installed.stat().st_mtime_ns, before.st_mtime_ns)
        human = self.cli('update')
        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertIn('Already current: ' + self.version, human.stdout)
        self.assertTrue(all(path.endswith('.sha256') for path in self.paths))

    def test_corruption_and_unusable_releases_preserve_a_runnable_installation(self):
        for candidate, bad_checksum in ((self.candidate, True), (b'not an executable', False),
                (b'#!/bin/sh\necho "small-cloud 0.7.0"\nexit 1\n', False),
                (b'#!/bin/sh\necho "small-cloud 0.5.0"\n', False)):
            with self.subTest(candidate=candidate, bad_checksum=bad_checksum):
                self.candidate, self.bad_checksum = candidate, bad_checksum
                result = self.cli('update', '--json')
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                error = json.loads(result.stdout)['error']
                self.assertEqual(error['code'], 'UPDATE_FAILED')
                self.assertEqual(error['details']['resulting_version'], self.version)
                self.assertEqual(error['details']['next_command'], 'small-cloud guide updating')
                self.assertEqual(self.installed.read_bytes(), self.original)
                self.assertEqual(list(self.installed.parent.iterdir()), [self.installed])
                version = subprocess.run([str(self.installed), '--version'], env=self.environment,
                                         capture_output=True, text=True, timeout=30)
                self.assertEqual(version.returncode, 0, version.stderr)
                self.assertEqual(version.stdout.strip(), 'small-cloud ' + self.version)

    def test_discovery_and_ordinary_commands_never_contact_update_service(self):
        for args in (('--help',), ('update', '--help'), ('catalog', 'update', '--json'),
                     ('guide', 'updating'), ('--version',)):
            result = self.cli(*args)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.paths, [])
        self.assertEqual(self.installed.read_bytes(), self.original)

    def test_source_installation_refuses_update_without_replacing_python(self):
        before = Path(sys.executable).stat()
        result = subprocess.run([sys.executable, '-m', 'identity.cli', 'update', '--json'],
                                env=self.environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        error = json.loads(result.stdout)['error']
        self.assertEqual(error['code'], 'UPDATE_UNSUPPORTED')
        self.assertEqual(error['details']['next_command'], 'small-cloud guide updating')
        self.assertEqual(Path(sys.executable).stat(), before)
        self.assertEqual(self.paths, [])
        self.assertEqual(self.installed.read_bytes(), self.original)

    def test_unwritable_install_directory_preserves_executable_and_reports_recovery(self):
        if os.geteuid() == 0:
            self.skipTest('Root bypasses directory mode restrictions.')
        self.installed.parent.chmod(0o555)
        try:
            result = self.cli('update', '--json')
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            error = json.loads(result.stdout)['error']
            self.assertEqual(error['code'], 'UPDATE_FAILED')
            self.assertEqual(error['details']['resulting_version'], self.version)
            self.assertEqual(error['details']['next_command'], 'small-cloud guide updating')
            self.assertEqual(self.installed.read_bytes(), self.original)
        finally:
            self.installed.parent.chmod(0o755)

    def test_failed_and_truncated_downloads_report_recovery_without_replacing(self):
        for failure in ('unavailable', 'redirect', 'truncated'):
            with self.subTest(failure=failure):
                self.download_failure = failure
                result = self.cli('update', '--json')
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                error = json.loads(result.stdout)['error']
                self.assertEqual(error['code'], 'UPDATE_FAILED')
                self.assertIn('small-cloud guide updating', error['details']['next_command'])
                self.assertEqual(self.installed.read_bytes(), self.original)
                human = self.cli('update')
                self.assertEqual(human.returncode, 1)
                self.assertIn('Existing executable kept', human.stderr)
                self.assertIn('Installed version: ' + self.version, human.stderr)
                self.assertIn('Resulting version: ' + self.version, human.stderr)
                self.assertNotIn('Traceback', human.stderr)

    def test_download_deadline_interrupts_stalled_headers_without_replacing(self):
        frozen = bool(os.environ.get('SMALL_CLOUD_TEST_BINARY'))
        self.download_failure = 'trickle' if frozen else 'wait'
        self.addCleanup(self.release_download.set)
        command = ([str(self.installed)] if os.environ.get('SMALL_CLOUD_TEST_BINARY') else
                   [sys.executable, '-m', 'identity.tests.cli'])
        process = subprocess.Popen([*command, 'update', '--json'], env=self.environment,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True)
        try:
            self.assertTrue(self.download_started.wait(15))
            # Native acceptance waits for the real deadline; source tests accelerate its OS signal.
            if not frozen:
                process.send_signal(signal.SIGALRM)
            stdout, stderr = process.communicate(timeout=135 if frozen else 5)
            self.assertEqual(process.returncode, 1, stdout + stderr)
            error = json.loads(stdout)['error']
            self.assertEqual(error['code'], 'UPDATE_FAILED')
            self.assertIn('time limit', error['message'])
            self.assertEqual(self.installed.read_bytes(), self.original)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_interruption_reports_unknown_version_and_keeps_executable_usable(self):
        self.download_failure = 'wait'
        self.addCleanup(self.release_download.set)
        command = ([str(self.installed)] if os.environ.get('SMALL_CLOUD_TEST_BINARY') else
                   [sys.executable, '-m', 'identity.tests.cli'])
        process = subprocess.Popen([*command, 'update', '--json'], env=self.environment,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        try:
            self.assertTrue(self.download_started.wait(15))
            os.killpg(process.pid, signal.SIGINT)
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 130, stdout + stderr)
            error = json.loads(stdout)['error']
            self.assertEqual(error['code'], 'INTERRUPTED')
            self.assertIsNone(error['details']['resulting_version'])
            self.assertEqual(error['details']['next_command'], 'small-cloud --version')
            self.assertEqual(self.installed.read_bytes(), self.original)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_update_keeps_custom_symlink_and_reports_human_outcome(self):
        link = self.home / 'small-cloud-link'
        link.symlink_to(self.installed)
        self.environment['SMALL_CLOUD_TEST_EXECUTABLE'] = str(link)
        result = self.cli('update')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'Updated: {self.version} → 999.0.0', result.stdout)
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.read_bytes(), self.candidate)

    def test_installed_native_fixture_updates_to_real_production_artifact(self):
        production = os.environ.get('SMALL_CLOUD_TEST_PRODUCTION_BINARY')
        if not production:
            self.skipTest('Native artifact acceptance runs in distribution/verify.py.')
        self.candidate = Path(production).read_bytes()
        self.environment['PATH'] = '/nonexistent'
        self.environment.pop('PYTHONPATH', None)
        result = self.cli('update', '--json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['data']['outcome'], 'updated')
        self.assertEqual(self.installed.read_bytes(), self.candidate)
        for args in (('--version',), ('--help',), ('catalog', 'update', '--json')):
            check = subprocess.run([str(self.installed), *args], env=self.environment,
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)


if __name__ == '__main__':
    unittest.main()
