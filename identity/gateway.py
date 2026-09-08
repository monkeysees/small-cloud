"""Authenticated app ingress and host-bound browser sign-in."""
import base64
import http.client
from http.cookies import SimpleCookie
import secrets
import posixpath
import time
import urllib.parse

from .common import Failure, digest

COOKIE = '__Host-small-cloud-app'
FLOW_COOKIE = '__Host-small-cloud-app-flow'
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade'}


class Gateway:
    def __init__(self, store, google, management_origin, app_domain, publishing):
        self.store, self.google, self.origin = store, google, management_origin
        self.domain, self.publishing = app_domain, publishing
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS app_oauth (
                    state TEXT PRIMARY KEY, browser TEXT NOT NULL, app TEXT NOT NULL,
                    nonce TEXT NOT NULL, pkce TEXT NOT NULL, expires REAL NOT NULL,
                    handoff TEXT, session TEXT);
                CREATE TABLE IF NOT EXISTS app_sessions (
                    verifier TEXT PRIMARY KEY, app TEXT NOT NULL, user_id TEXT NOT NULL,
                    expires REAL NOT NULL);
            ''')

    def app_id(self, host):
        suffix = '.' + self.domain
        if not host.endswith(suffix):
            return None
        label = host[:-len(suffix)]
        return label if label and '.' not in label and all(c in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in label) else None

    def has_oauth_state(self, state):
        with self.store.connect() as db:
            return db.execute('SELECT 1 FROM app_oauth WHERE state=?', (digest(state),)).fetchone() is not None

    def callback(self, handler):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(handler.path).query)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            flow = db.execute('SELECT * FROM app_oauth WHERE state=? AND expires>? AND handoff IS NULL',
                              (digest(query['state'][0]), time.time())).fetchone()
            if not flow:
                raise Failure('AUTH_REQUIRED', 'App sign-in expired.', 401)
            claims = self.google.exchange(query['code'][0], self.origin + '/auth/callback', flow['nonce'], flow['pkce'])
            # Binding is performed outside this transaction, which holds the SQLite writer lock.
            flow = dict(flow)
            db.execute('UPDATE app_oauth SET handoff=? WHERE state=?', ('pending', flow['state']))
        session = self.store.bind_google(claims)
        with self.store.connect() as db:
            user = self.store.browser_user(db, session)
            self.publishing.gateway_target(flow['app'], user['id'])
            token, handoff = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            db.execute('INSERT INTO app_sessions VALUES(?,?,?,?)', (digest(token), flow['app'], user['id'], time.time() + 43200))
            db.execute('DELETE FROM browser_sessions WHERE verifier=?', (digest(session),))
            db.execute('UPDATE app_oauth SET handoff=?,session=? WHERE state=?', (digest(handoff), token, flow['state']))
        handler.respond(302, '', 'text/html', {'Location': 'https://' + flow['app'] + '.' + self.domain + '/_small-cloud/auth/finish?code=' + handoff})

    def user(self, handler, app_id):
        # An explicit credential takes precedence over ambient browser cookies.
        if handler.headers.get('Authorization'):
            with self.store.connect() as db:
                return dict(self.store.credential(db, handler.bearer())[1])
        with self.store.connect() as db:
            user = db.execute('SELECT u.* FROM app_sessions s JOIN users u ON u.id=s.user_id '
                              'WHERE s.verifier=? AND s.app=? AND s.expires>? AND u.member=1',
                              (digest(handler.cookie(COOKIE)), app_id, time.time())).fetchone()
            if user:
                return dict(user)
        raise Failure('AUTH_REQUIRED', 'App sign-in required.', 401)

    def route(self, handler):
        app_id = self.app_id(handler.headers.get('Host', ''))
        if not app_id:
            raise Failure('NOT_FOUND', 'App not found.', 404)
        parsed = urllib.parse.urlsplit(handler.path)
        path = posixpath.normpath(urllib.parse.unquote(parsed.path).replace('\\', '/'))
        path = '/' + path.lstrip('/')
        if path == '/_small-cloud/auth/finish' and handler.command == 'GET':
            code = urllib.parse.parse_qs(parsed.query)['code'][0]
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                flow = db.execute('SELECT * FROM app_oauth WHERE handoff=? AND browser=? AND app=? AND expires>?',
                                  (digest(code), digest(handler.cookie(FLOW_COOKIE)), app_id, time.time())).fetchone()
                if not flow:
                    raise Failure('AUTH_REQUIRED', 'App sign-in expired.', 401)
                token = flow['session']
                db.execute('DELETE FROM app_oauth WHERE state=?', (flow['state'],))
            handler.respond(302, '', 'text/html', {'Location': '/', 'Set-Cookie': handler.set_cookie(COOKIE, token, 43200)})
            return
        try:
            user = self.user(handler, app_id)
        except Failure as exc:
            if exc.status != 401 or handler.command != 'GET' or 'text/html' not in handler.headers.get('Accept', ''):
                raise
            state, browser, nonce, pkce = (secrets.token_urlsafe(32) for _ in range(4))
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('DELETE FROM app_oauth WHERE expires<=?', (time.time(),))
                db.execute('DELETE FROM app_sessions WHERE expires<=?', (time.time(),))
                if db.execute('SELECT COUNT(*) FROM app_oauth').fetchone()[0] >= 200:
                    raise Failure('REQUEST_CONFLICT', 'Too many pending sign-ins.', 429)
                db.execute('INSERT INTO app_oauth VALUES(?,?,?,?,?,?,NULL,NULL)',
                           (digest(state), digest(browser), app_id, nonce, pkce, time.time() + 600))
            handler.respond(302, '', 'text/html', {
                'Location': self.google.authorization_url(self.origin + '/auth/callback', state, nonce, pkce),
                'Set-Cookie': handler.set_cookie(FLOW_COOKIE, browser, 600)})
            return
        target = self.publishing.gateway_target(app_id, user['id'])
        if handler.command not in ('GET', 'HEAD', 'OPTIONS'):
            origins = handler.headers.get_all('Origin', [])
            expected_origin = 'https://' + app_id + '.' + self.domain
            if origins != [expected_origin]:
                if origins or not handler.headers.get('Authorization'):
                    raise Failure('FORBIDDEN', 'App mutations require the app origin.', 403)
        if path.startswith('/_small-cloud/'):
            raise Failure('NOT_FOUND', 'Route not found.', 404)
        if handler.headers.get('Upgrade'):
            # No unauthenticated upgrade path; unsupported upgrades fail closed.
            raise Failure('INVALID_ARGUMENT', 'Protocol upgrades are not supported.', 400)
        self.proxy(handler, user, target)

    def proxy(self, handler, user, target):
        lengths = handler.headers.get_all('Content-Length', [])
        if handler.headers.get('Transfer-Encoding') or len(lengths) > 1:
            raise Failure('INVALID_ARGUMENT', 'Ambiguous request framing.')
        length = int(lengths[0]) if lengths else 0
        if length < 0 or length > 16 * 1024 * 1024:
            raise Failure('INVALID_ARGUMENT', 'App request body exceeds 16 MiB.')
        body = handler.rfile.read(length)
        if len(body) != length:
            raise Failure('INVALID_ARGUMENT', 'Incomplete app request body.')
        blocked = HOP | {'authorization', 'cookie', 'host', 'content-length', 'expect'}
        blocked |= {part.strip().lower() for part in ','.join(handler.headers.get_all('Connection', [])).split(',')}
        connection = http.client.HTTPConnection(target['host'], target['port'], timeout=30)
        try:
            connection.putrequest(handler.command, handler.path, skip_host=True, skip_accept_encoding=True)
            for name, value in handler.headers.items():
                if name.lower() not in blocked and not name.lower().startswith(('x-small-cloud-', 'x-forwarded-')):
                    connection.putheader(name, value)
            cookies = SimpleCookie()
            cookies.load(handler.headers.get('Cookie', ''))
            app_cookies = '; '.join(m.OutputString() for name, m in cookies.items()
                                    if not name.lower().startswith('__host-small-cloud-'))
            if app_cookies:
                connection.putheader('Cookie', app_cookies)
            connection.putheader('Host', handler.headers['Host'])
            connection.putheader('Content-Length', str(length))
            for key in ('id', 'name', 'email'):
                value = user[key] if key == 'id' else base64.urlsafe_b64encode(user[key].encode()).rstrip(b'=').decode()
                connection.putheader('X-Small-Cloud-User-' + key.title(), value)
            connection.endheaders(body)
            response = connection.getresponse()
            payload = response.read(16 * 1024 * 1024 + 1)
            if len(payload) > 16 * 1024 * 1024:
                raise Failure('INTERNAL', 'App response exceeds 16 MiB.', 502)
            handler.send_response(response.status)
            response_blocked = HOP | {'content-length', 'set-cookie'}
            response_blocked |= {part.strip().lower() for part in ','.join(value for name, value in response.getheaders() if name.lower() == 'connection').split(',')}
            for name, value in response.getheaders():
                if name.lower() == 'set-cookie':
                    cookies = SimpleCookie()
                    cookies.load(value)
                    for cookie_name, morsel in cookies.items():
                        if not cookie_name.lower().startswith('__host-small-cloud-') and not morsel['domain']:
                            handler.send_header('Set-Cookie', morsel.OutputString())
                elif name.lower() not in response_blocked:
                    handler.send_header(name, value)
            # HEAD/304 describe a representation without carrying its body.
            if response.status == 304 or (handler.command == 'HEAD' and response.status >= 200 and response.status != 204):
                lengths = [value for name, value in response.getheaders() if name.lower() == 'content-length']
                if len(lengths) == 1 and lengths[0].isascii() and lengths[0].isdigit():
                    handler.send_header('Content-Length', lengths[0])
            elif response.status >= 200 and response.status != 204:
                handler.send_header('Content-Length', str(len(payload)))
            handler.end_headers()
            if handler.command != 'HEAD' and response.status >= 200 and response.status not in (204, 304):
                handler.wfile.write(payload)
        except (OSError, http.client.HTTPException):
            raise Failure('INTERNAL', 'App is unavailable.', 502) from None
        finally:
            connection.close()
