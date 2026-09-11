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

    def body(self, limit=16384):
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
            raise Failure('INVALID_ARGUMENT', 'Transfer encoding is not accepted.')
        size = int(self.headers.get('Content-Length', '0'))
        if size < 0 or size > limit:
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

    def workspace(self):
        values = [urllib.parse.unquote(value, errors='strict') for value in self.headers.get_all('X-Workspace', [])]
        if len(values) > 1 or values and (not values[0].strip() or len(values[0]) > 100):
            raise Failure('INVALID_ARGUMENT', 'Supply one workspace ID or exact name in X-Workspace.')
        return values[0] if values else None

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
            session = store.bind_google(claims, self.cookie(COOKIE))
            if flow['code'].startswith('/directory'):
                self.respond(302, '', 'text/html', {'Location': flow['code'],
                             'Set-Cookie': self.set_cookie(COOKIE, session, 43200)})
                return
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
            self.respond(200, envelope(store.status(self.bearer(), self.workspace())))
        elif self.command == 'GET' and path == '/directory':
            if set(query) - {'workspace'} or any(len(values) != 1 for values in query.values()):
                raise Failure('INVALID_ARGUMENT', 'Supply one workspace target.')
            with store.connect() as db:
                try:
                    user = store.browser_user(db, self.cookie(COOKIE))
                except Failure as error:
                    if error.code != 'AUTH_REQUIRED':
                        raise
                    user = None
                if user is not None:
                    member = store.select_workspace(db, user, query.get('workspace', [None])[0])
                    apps = list(self.app.publishing.accessible_apps(db, user['id'], workspace=member['workspace_id']))
                    workspaces = list(db.execute('SELECT workspace_id,workspace_name FROM workspace_users '
                                                  'WHERE id=? AND member=1 ORDER BY workspace_name', (user['id'],)))
            if user is None:
                browser_secret = secrets.token_urlsafe(32)
                return_to = '/directory' + ('?' + urllib.parse.urlencode({'workspace': query['workspace'][0]}) if query else '')
                state, nonce, pkce = store.begin_oauth(return_to, browser_secret, directory=True)
                url = self.app.google.authorization_url(self.app.origin + '/auth/callback', state, nonce, pkce)
                self.respond(302, '', 'text/html', {'Location': url,
                             'Set-Cookie': self.set_cookie(FLOW_COOKIE, browser_secret, 600)})
                return
            links = ''.join('<li><a href="/directory?workspace=' + urllib.parse.quote(row['workspace_id']) + '">'
                            + html.escape(row['workspace_name']) + '</a></li>' for row in workspaces)
            entries = ''.join('<li><a href="' + html.escape(self.app.publishing.url(app), quote=True) + '">'
                              + html.escape(app['name']) + '</a> — ' + html.escape(app['description']) + '</li>' for app in apps)
            self.respond(200, '<!doctype html><html lang="en"><meta charset="utf-8">'
                         '<meta name="viewport" content="width=device-width, initial-scale=1">'
                         '<title>Small Cloud apps</title><main><h1>' + html.escape(member['workspace_name']) + '</h1>'
                         '<nav aria-label="Workspaces"><ul>' + links + '</ul></nav><h2>Accessible apps</h2>'
                         + ('<ul>' + entries + '</ul>' if apps else '<p>No accessible apps.</p>') + '</main></html>', 'text/html')
        elif self.command == 'GET' and path == '/api/workspaces':
            self.respond(200, envelope(store.workspaces(self.bearer(), self.workspace())))
        elif self.command == 'POST' and path in ('/api/workspaces/create', '/api/workspaces/select'):
            result = store.mutate(self.bearer(), path.removeprefix('/api/'), self.body(), self.request_id, self.workspace())
            self.respond(200, envelope(result, request_id=self.request_id))
        elif self.command == 'POST' and path == '/api/deploy':
            token = self.bearer()
            identity = store.status(token, self.workspace())
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
                                                    archive, self.request_id, identity['workspace']['id'])
                self.respond(202, envelope(result, request_id=self.request_id))
            finally:
                self.app.upload_slots.release()
        elif self.command == 'GET' and path == '/api/usage':
            self.respond(200, envelope(self.app.publishing.usage(self.bearer(), self.workspace())))
        elif self.command == 'GET' and path == '/api/directory':
            self.respond(200, envelope(self.app.publishing.directory(self.bearer(), self.workspace())))
        elif self.command == 'POST' and path.startswith('/api/apps/') and path.endswith('/share'):
            name = urllib.parse.unquote(path.removeprefix('/api/apps/').removesuffix('/share'))
            result = self.app.publishing.share(self.bearer(), name, self.body(), self.request_id, self.workspace())
            self.respond(200, envelope(result, request_id=self.request_id))
        elif self.command == 'POST' and path.startswith('/api/apps/') and path.endswith(('/secrets/set', '/secrets/delete')):
            target, action = path.removeprefix('/api/apps/').rsplit('/secrets/', 1)
            result = self.app.publishing.secrets.change(self.app.publishing, self.bearer(),
                urllib.parse.unquote(target), action, self.body(131072), self.request_id, self.workspace())
            self.respond(202 if result['changed'] else 200, envelope(result, request_id=self.request_id))
        elif self.command == 'GET' and path == '/api/operations':
            if set(query) != {'request_id'} or len(query['request_id']) != 1:
                raise Failure('INVALID_ARGUMENT', 'Supply one request ID or use the operation ID route.')
            query['request_id'][0] = str(uuid.UUID(query['request_id'][0]))
            result = self.app.publishing.operation(self.bearer(), request_id=query['request_id'][0], workspace=self.workspace())
            self.respond(200, envelope(result))
        elif self.command == 'GET' and path.startswith('/api/operations/'):
            if query:
                raise Failure('INVALID_ARGUMENT', 'Operation ID and request ID targets are mutually exclusive.')
            result = self.app.publishing.operation(self.bearer(), operation_id=path.removeprefix('/api/operations/'), workspace=self.workspace())
            self.respond(200, envelope(result))
        elif self.command == 'GET' and path.startswith('/api/apps/'):
            target = urllib.parse.unquote(path.removeprefix('/api/apps/'))
            allowed = {'source', 'deployment', 'since', 'limit', 'cursor', 'tail'} if target.endswith('/logs') else set()
            if set(query) - allowed or any(len(values) != 1 for values in query.values()):
                raise Failure('INVALID_ARGUMENT', 'Unsupported or duplicate app target inputs.')
            if target.endswith('/secrets'):
                result = self.app.publishing.secrets.names(self.app.publishing, self.bearer(), target.removesuffix('/secrets'), self.workspace())
            elif target.endswith('/logs'):
                if query.get('tail', ['false'])[0] not in ('true', 'false'):
                    raise Failure('INVALID_ARGUMENT', 'Tail must be true or false.')
                result = self.app.publishing.logs(self.bearer(), target.removesuffix('/logs'),
                    source=query['source'][0], deployment=query.get('deployment', [None])[0],
                    since=query.get('since', [None])[0], limit=int(query.get('limit', ['100'])[0]),
                    cursor=query.get('cursor', [None])[0], workspace=self.workspace(),
                    tail=query.get('tail', ['false'])[0] == 'true')
            else:
                result = self.app.publishing.status(self.bearer(), target, self.workspace())
            self.respond(200, envelope(result))
        elif self.command == 'POST' and path in ('/api/auth/logout', '/api/auth/revoke', '/api/admin/member/add', '/api/admin/creator/grant'):
            action = path.removeprefix('/api/').removeprefix('auth/')
            result = store.mutate(self.bearer(), action, self.body(), self.request_id, self.workspace())
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
