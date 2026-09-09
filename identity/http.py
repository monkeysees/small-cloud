"""Bounded loopback HTTP adapter, served behind the management-origin TLS proxy."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
import html
import json
import secrets
import urllib.parse
import uuid
import threading

from .common import Failure, digest, envelope, origin
from .google import Google
from .store import Store

COOKIE = '__Host-small-cloud-session'
FLOW_COOKIE = '__Host-small-cloud-flow'


class Application:
    def __init__(self, config, google=None):
        self.origin = origin(config['origin'])
        self.store = Store(config['state_directory'])
        self.google = google or Google(config['google_client_id'], config['google_client_secret'])
        from .publishing import Publishing
        self.publishing = Publishing(self.store, self.origin)
        self.upload_slots = threading.BoundedSemaphore(1)
        from .gateway import Gateway
        self.gateway = Gateway(self.store, self.google, self.origin,
                               urllib.parse.urlsplit(self.origin).hostname, self.publishing)


class Handler(BaseHTTPRequestHandler):
    server: 'Server'
    server_version = 'SmallCloud'

    def log_message(self, *_args):
        # Request URLs can contain OAuth codes; never send them to access logs.
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    @property
    def app(self):
        return self.server.application

    def respond(self, status, body, content_type='application/json', headers=None):
        payload = (json.dumps(body) if content_type == 'application/json' else body).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        # Preserve Origin on form POSTs without disclosing OAuth URL paths or queries.
        self.send_header('Referrer-Policy', 'strict-origin')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def cookie(self, name):
        cookie = SimpleCookie()
        cookie.load(self.headers.get('Cookie', ''))
        return cookie[name].value if name in cookie else ''

    @staticmethod
    def set_cookie(name, value, age):
        return f'{name}={value}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age={age}'

    def body(self):
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
            raise Failure('INVALID_ARGUMENT', 'Transfer encoding is not accepted.')
        size = int(self.headers.get('Content-Length', '0'))
        if size < 0 or size > 16384:
            raise Failure('INVALID_ARGUMENT', 'Request body exceeds limit.')
        raw = self.rfile.read(size)
        if self.headers.get_content_type() == 'application/x-www-form-urlencoded':
            return {key: values[0] for key, values in urllib.parse.parse_qs(raw.decode(), strict_parsing=True).items()}
        if self.headers.get_content_type() != 'application/json':
            raise Failure('INVALID_ARGUMENT', 'Expected JSON request body.')
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise Failure('INVALID_ARGUMENT', 'Expected an object.')
        return body

    def bearer(self):
        headers = self.headers.get_all('Authorization', [])
        if len(headers) != 1 or not headers[0].startswith('Bearer '):
            raise Failure('AUTH_REQUIRED', 'CLI credential required.', 401)
        return headers[0][7:]

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def __getattr__(self, name):
        if name.startswith('do_'):
            return self.dispatch
        raise AttributeError(name)

    def dispatch(self):
        self.request_id = None
        try:
            if len(self.headers.get_all('Host', [])) != 1:
                raise Failure('FORBIDDEN', 'One Host header is required.', 403)
            if (self.command == 'GET' and self.headers['Host'] == '127.0.0.1:' + str(self.server.server_port)
                    and urllib.parse.urlsplit(self.path).path == '/internal/tls'):
                domain = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('domain', [''])[0]
                if not self.app.publishing.certificate_allowed(domain):
                    raise Failure('FORBIDDEN', 'Certificate hostname not admitted.', 403)
                self.respond(200, envelope({'allowed': True}))
                return
            if self.app.gateway.app_id(self.headers.get('Host', '')):
                self.app.gateway.route(self)
                return
            if self.headers.get('Host') != urllib.parse.urlsplit(self.app.origin).netloc:
                raise Failure('FORBIDDEN', 'Unexpected management origin.', 403)
            if self.command == 'POST' and self.path.startswith('/api/') and self.path not in ('/api/auth/login', '/api/auth/poll'):
                self.request_id = str(uuid.UUID(self.headers.get('X-Request-ID', '')))
            self.route()
        except Failure as exc:
            self.respond(exc.status, envelope(failure=exc, request_id=self.request_id))
        except (ValueError, KeyError, TypeError):
            self.respond(400, envelope(failure=Failure('INVALID_ARGUMENT', 'Invalid request.')))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.respond(500, envelope(failure=Failure('INTERNAL', 'Identity service could not complete the request.', 500)))

    def route(self):
        parsed = urllib.parse.urlsplit(self.path)
        path, store = parsed.path, self.app.store
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if self.command == 'GET' and path == '/health':
            self.respond(200, envelope({'ready': True}))
        elif self.command == 'POST' and path == '/api/auth/login':
            result = store.start_login(self.body()['poll_secret'])
            result['verification_url'] = self.app.origin + '/auth/verify?code=' + result['user_code']
            self.respond(200, envelope(result))
        elif self.command == 'POST' and path == '/api/auth/poll':
            self.respond(200, envelope(store.poll(self.body()['poll_secret'])))
        elif self.command == 'GET' and path == '/auth/verify':
            code = query['code'][0]
            browser_secret = secrets.token_urlsafe(32)
            state, nonce, pkce = store.begin_oauth(code, browser_secret)
            url = self.app.google.authorization_url(self.app.origin + '/auth/callback', state, nonce, pkce)
            self.respond(302, '', 'text/html', {'Location': url,
                         'Set-Cookie': self.set_cookie(FLOW_COOKIE, browser_secret, 600)})
        elif self.command == 'GET' and path == '/auth/callback':
            if self.app.gateway.has_oauth_state(query['state'][0]):
                self.app.gateway.callback(self)
                return
            flow = store.take_oauth(query['state'][0], self.cookie(FLOW_COOKIE))
            claims = self.app.google.exchange(query['code'][0], self.app.origin + '/auth/callback', flow['nonce'], flow['pkce'])
            session = store.bind_google(claims)
            self.respond(302, '', 'text/html', {'Location': '/auth/approval?code=' + flow['code'],
                         'Set-Cookie': self.set_cookie(COOKIE, session, 43200)})
        elif self.command == 'GET' and path == '/auth/approval':
            code, session = query['code'][0], self.cookie(COOKIE)
            identity = store.approval(code, session)
            self.respond(200, '<!doctype html><title>Approve Small Cloud CLI</title>'
                         '<h1>Approve CLI sign-in</h1><p>Only approve a sign-in you started. '
                         'Check that this code matches your terminal: <strong>' + html.escape(code) + '</strong></p>'
                         '<p>Sign in as ' + html.escape(identity['user']['email']) + '</p>'
                         '<form method="post" action="/auth/approve"><input type="hidden" name="csrf" value="' + digest(session + ':csrf') + '">'
                         '<input type="hidden" name="code" value="' + html.escape(code, quote=True) + '">'
                         '<button type="submit">Approve CLI sign-in</button></form>', 'text/html')
        elif self.command == 'POST' and path == '/auth/approve':
            body, session = self.body(), self.cookie(COOKIE)
            if (self.headers.get('Origin') != self.app.origin or not session
                    or not secrets.compare_digest(body.get('csrf', ''), digest(session + ':csrf'))):
                raise Failure('FORBIDDEN', 'Browser approval requires a valid CSRF token and origin.', 403)
            store.approval(body['code'], session, approve=True)
            self.respond(200, '<!doctype html><title>Sign-in approved</title><p>Approved. Return to your terminal.</p>', 'text/html')
        elif self.command == 'GET' and path == '/api/auth/status':
            self.respond(200, envelope(store.status(self.bearer())))
        elif self.command == 'POST' and path == '/api/deploy':
            token = self.bearer()
            identity = store.status(token)
            if 'creator' not in identity['roles']:
                raise Failure('FORBIDDEN', 'Creator privileges required.', 403)
            if (self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1
                    or self.headers.get_content_type() != 'application/x-tar'):
                raise Failure('UPLOAD_REJECTED', 'Expected a bounded uncompressed tar archive.')
            size = int(self.headers['Content-Length'])
            if not 0 < size <= 116 * 1024 * 1024:
                raise Failure('UPLOAD_REJECTED', 'Upload exceeds archive size limit.')
            if not self.app.upload_slots.acquire(blocking=False):
                raise Failure('BUILD_BUSY', 'Upload capacity is occupied; retry later.', 409)
            try:
                archive = self.rfile.read(size)
                if len(archive) != size:
                    raise Failure('UPLOAD_REJECTED', 'Upload was incomplete.')
                if any(len(values) != 1 for values in query.values()) or set(query) - {'name', 'description'}:
                    raise Failure('INVALID_ARGUMENT', 'Invalid deployment metadata.')
                result = self.app.publishing.deploy(token, {key: values[0] for key, values in query.items()},
                                                    archive, self.request_id)
                self.respond(202, envelope(result, request_id=self.request_id))
            finally:
                self.app.upload_slots.release()
        elif self.command == 'GET' and path == '/api/directory':
            self.respond(200, envelope(self.app.publishing.directory(self.bearer())))
        elif self.command == 'POST' and path.startswith('/api/apps/') and path.endswith('/share'):
            name = urllib.parse.unquote(path.removeprefix('/api/apps/').removesuffix('/share'))
            result = self.app.publishing.share(self.bearer(), name, self.body(), self.request_id)
            self.respond(200, envelope(result, request_id=self.request_id))
        elif self.command == 'GET' and path == '/api/operations':
            result = self.app.publishing.operation(self.bearer(), request_id=query['request_id'][0])
            self.respond(200, envelope(result))
        elif self.command == 'GET' and path.startswith('/api/operations/'):
            result = self.app.publishing.operation(self.bearer(), operation_id=path.removeprefix('/api/operations/'))
            self.respond(200, envelope(result))
        elif self.command == 'GET' and path.startswith('/api/apps/'):
            target = urllib.parse.unquote(path.removeprefix('/api/apps/'))
            if target.endswith('/logs'):
                result = self.app.publishing.logs(self.bearer(), target.removesuffix('/logs'),
                    source=query['source'][0], deployment=query.get('deployment', [None])[0],
                    since=query.get('since', [None])[0], limit=int(query.get('limit', ['100'])[0]))
            else:
                result = self.app.publishing.status(self.bearer(), target)
            self.respond(200, envelope(result))
        elif self.command == 'POST' and path in ('/api/auth/logout', '/api/auth/revoke', '/api/admin/member/add', '/api/admin/creator/grant'):
            action = path.removeprefix('/api/').removeprefix('auth/')
            result = store.mutate(self.bearer(), action, self.body(), self.request_id)
            self.respond(200, envelope(result, request_id=self.request_id))
        else:
            raise Failure('NOT_FOUND', 'Route not found.', 404)


class Server(ThreadingHTTPServer):
    application: Application
    daemon_threads = True

    def __init__(self, address, handler):
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def create_server(config, port=8765, google=None):
    server = Server(('127.0.0.1', port), Handler)
    server.application = Application(config, google)
    return server
