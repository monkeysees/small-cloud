"""Gateway acceptance at authenticated HTTP, with an echo runtime."""
import base64
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import tempfile
import threading
import unittest
import urllib.parse

from identity.common import Failure
from identity.gateway import Gateway
from identity.http import Application, Handler, Server


class GatewayAcceptance(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.application = Application({'origin': 'https://cloud.example.test',
            'state_directory': temp.name + '/state', 'google_client_id': 'unused', 'google_client_secret': 'unused'})
        store = self.application.store
        owner = store.bootstrap('owner@example.test')['user_id']
        browser = store.bind_google({'sub': 'owner', 'email': 'owner@example.test', 'name': 'Zoë 東京'})
        poll = 'a' * 43
        login = store.start_login(poll)
        store.approval(login['user_code'], browser, approve=True)
        self.token = store.poll(poll)['credential']
        self.owner = owner
        self.requests = []
        requests = self.requests

        class Echo(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                requests.append(list(self.headers.items()))
                payload = json.dumps(list(self.headers.items())).encode()
                if self.path == '/no-content':
                    self.send_response(204)
                    self.end_headers()
                    return
                if self.path.startswith('/not-modified'):
                    self.send_response(304)
                    if self.path.endswith('/length'):
                        self.send_header('Content-Length', '123')
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(payload)

            do_HEAD = do_GET
            do_POST = do_GET
            do_DELETE = do_GET

        runtime = ThreadingHTTPServer(('127.0.0.1', 0), Echo)
        self.serve(runtime)
        self.allowed = True
        fixture = self

        class Publishing:
            def gateway_target(self, app_id, user_id):
                if app_id != 'a-example' or user_id != owner or not fixture.allowed:
                    raise Failure('NOT_FOUND', 'App not found.', 404)
                return {'host': '127.0.0.1', 'port': runtime.server_port}

        class Provider:
            def authorization_url(self, redirect, state, nonce, pkce):
                return 'https://accounts.google.com/authorize?' + urllib.parse.urlencode({'state': state})

            def exchange(self, code, redirect, nonce, pkce):
                return {'sub': 'owner', 'email': 'owner@example.test', 'name': 'Zoë 東京'}

        gateway = Gateway(store, Provider(), self.application.origin, 'cloud.example.test', Publishing())

        self.application.gateway = gateway
        self.server = Server(('127.0.0.1', 0), Handler)
        self.server.application = self.application
        self.serve(self.server)

    def serve(self, server):
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

    def request(self, method='GET', path='/', token=True, extra=(), host='a-example.cloud.example.test'):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        self.addCleanup(conn.close)
        conn.putrequest(method, path, skip_host=True)
        conn.putheader('Host', host)
        if token:
            conn.putheader('Authorization', 'Bearer ' + self.token)
        for name, value in extra:
            conn.putheader(name, value)
        conn.endheaders()
        response = conn.getresponse()
        return response.status, response.read(), dict(response.getheaders())

    def test_all_routes_and_methods_require_identity_before_runtime(self):
        for method in ('GET', 'POST', 'DELETE'):
            status, _, _ = self.request(method, '/assets/file', token=False)
            self.assertEqual(status, 401)
        self.assertEqual(self.request(token=False, extra=[('Upgrade', 'websocket')])[0], 401)
        self.assertEqual(self.requests, [])
        status, _, headers = self.request(token=False, extra=[('Accept', 'text/html')])
        self.assertEqual(status, 302)
        self.assertIn('accounts.google.com', headers['Location'])
        self.assertIn('Secure; HttpOnly; SameSite=Lax', headers['Set-Cookie'])
        self.assertNotIn('Domain=', headers['Set-Cookie'])

    def test_trusted_identity_replaces_duplicates_without_credentials(self):
        status, raw, _ = self.request(extra=[('X-Small-Cloud-User-ID', 'spoof'),
            ('x-small-cloud-user-id', 'duplicate'), ('X-Small-Cloud-Other', 'spoof'),
            ('Cookie', '__Host-small-cloud-app=secret; app_preference=dark')])
        self.assertEqual(status, 200)
        headers = [(name.lower(), value) for name, value in json.loads(raw)]
        self.assertEqual([value for name, value in headers if name == 'x-small-cloud-user-id'], [self.owner])
        self.assertEqual(dict(headers)['x-small-cloud-user-name'], base64.urlsafe_b64encode('Zoë 東京'.encode()).rstrip(b'=').decode())
        self.assertNotIn('authorization', dict(headers))
        self.assertNotIn('x-small-cloud-other', dict(headers))
        self.assertEqual(dict(headers)['cookie'], 'app_preference=dark')

    def test_denial_and_reserved_readiness_never_reach_runtime(self):
        self.assertEqual(self.request(path='/_small-cloud/ready')[0], 404)
        self.assertEqual(self.request(path='/%5fsmall-cloud/ready')[0], 404)
        self.allowed = False
        self.assertEqual(self.request()[0], 404)
        self.assertEqual(self.request(extra=[('Upgrade', 'websocket')])[0], 404)
        self.assertEqual(self.requests, [])

    def test_browser_handoff_is_single_use_and_bound_to_initiating_browser(self):
        status, _, headers = self.request(token=False, extra=[('Accept', 'text/html')])
        self.assertEqual(status, 302)
        flow_cookie = headers['Set-Cookie'].split(';')[0]
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(headers['Location']).query)['state'][0]
        status, _, headers = self.request(path='/auth/callback?state=' + state + '&code=provider-code', token=False, host='cloud.example.test')
        self.assertEqual(status, 302)
        finish = urllib.parse.urlsplit(headers['Location'])
        self.assertEqual(finish.netloc, 'a-example.cloud.example.test')
        path = finish.path + '?' + finish.query
        self.assertEqual(self.request(path=path, token=False)[0], 401)
        status, _, headers = self.request(path=path, token=False, extra=[('Cookie', flow_cookie)])
        self.assertEqual(status, 302)
        app_cookie = headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request(path=path, token=False, extra=[('Cookie', flow_cookie)])[0], 401)
        status, raw, _ = self.request(token=False, extra=[('Cookie', app_cookie)])
        self.assertEqual(status, 200)
        self.assertNotIn('__Host-small-cloud-app', raw.decode())
        self.assertEqual(self.request(method='POST', token=False, extra=[('Cookie', app_cookie)])[0], 403)
        self.assertEqual(self.request(method='POST', token=False, extra=[('Cookie', app_cookie),
                         ('Origin', 'https://other.cloud.example.test')])[0], 403)
        self.assertEqual(self.request(method='POST', token=False, extra=[('Cookie', app_cookie),
                         ('Origin', 'https://a-example.cloud.example.test')])[0], 200)
        self.assertEqual(self.request(method='POST', extra=[('Origin', 'https://other.cloud.example.test')])[0], 403)
        self.assertEqual(self.request(method='POST')[0], 200)
        self.allowed = False
        self.assertEqual(self.request(token=False, extra=[('Cookie', app_cookie)])[0], 404)

    def test_head_and_bodyless_status_preserve_representation_framing(self):
        status, body, headers = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(int(headers['Content-Length']), len(body))
        status, head_body, head_headers = self.request(method='HEAD')
        self.assertEqual(status, 200)
        self.assertEqual(head_body, b'')
        self.assertEqual(head_headers['Content-Length'], headers['Content-Length'])
        for path, expected_status in (('/no-content', 204), ('/not-modified', 304)):
            status, body, headers = self.request(path=path)
            self.assertEqual(status, expected_status)
            self.assertEqual(body, b'')
            self.assertNotIn('Content-Length', headers)
        status, body, headers = self.request(path='/not-modified/length')
        self.assertEqual(status, 304)
        self.assertEqual(body, b'')
        self.assertEqual(headers['Content-Length'], '123')
