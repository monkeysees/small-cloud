"""Transactional identity state on the trusted control host."""
import re
import sqlite3
import uuid
import secrets
import time
import json
import os
from contextlib import contextmanager
from pathlib import Path

from .common import Failure, digest, protected_directory, timestamp, validate_private_file
from .workspaces import INITIAL_WORKSPACE, migrate


def email_address(value):
    if not isinstance(value, str) or len(value) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
        raise Failure('INVALID_ARGUMENT', 'Supply a valid Google email address.')
    return value.lower()


class Store:
    def __init__(self, directory: str):
        self.path = protected_directory(Path(directory)) / 'identity.sqlite3'
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            validate_private_file(fd)
        finally:
            os.close(fd)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, admission_email TEXT UNIQUE NOT NULL,
                    subject TEXT UNIQUE, name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL,
                    platform_administrator INTEGER NOT NULL DEFAULT 0,
                    default_workspace TEXT REFERENCES workspaces(id));
                CREATE TABLE IF NOT EXISTS credentials (
                    id TEXT PRIMARY KEY, verifier TEXT UNIQUE NOT NULL, user_id TEXT NOT NULL,
                    expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS browser_sessions (
                    verifier TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS logins (
                    code TEXT PRIMARY KEY, poll_verifier TEXT UNIQUE NOT NULL, expires REAL NOT NULL,
                    user_id TEXT, consumed INTEGER NOT NULL DEFAULT 0, last_poll REAL NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS oauth (
                    state TEXT PRIMARY KEY, browser_verifier TEXT NOT NULL,
                    nonce TEXT NOT NULL, pkce TEXT NOT NULL, code TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (
                    actor TEXT NOT NULL, id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    result TEXT NOT NULL, expires REAL NOT NULL, PRIMARY KEY(actor,id));
            ''')
            migrate(db)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level='IMMEDIATE')
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def bootstrap(self, email):
        email = email_address(email)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM workspace_users WHERE id=owner_id').fetchone()
            if existing:
                if existing['admission_email'] != email:
                    raise Failure('REQUEST_CONFLICT', 'The initial workspace owner is already configured.', 409)
                return self.membership(existing)
            user_id = 'usr_' + uuid.uuid4().hex
            db.execute('INSERT INTO users(id,admission_email,email,platform_administrator,default_workspace) '
                       "VALUES(?,?,?,1,'ws-initial')",
                       (user_id, email, email))
            db.execute('INSERT INTO workspaces VALUES(?,?,?)', (INITIAL_WORKSPACE, 'Initial workspace', user_id))
            db.execute('INSERT INTO memberships VALUES(?,?,1,0,1)', (INITIAL_WORKSPACE, user_id))
            return self.membership(db.execute('SELECT * FROM workspace_users WHERE id=?', (user_id,)).fetchone())

    @staticmethod
    def membership(user):
        return {'user_id': user['id'], 'email': user['email'], 'member': bool(user['member']),
                'creator': bool(user['creator']), 'administrator': bool(user['administrator'])}

    @staticmethod
    def identity(user):
        return {'user': {'id': user['id'], 'name': user['name'], 'email': user['email']},
                'roles': [role for role in ('member', 'creator', 'administrator') if user[role]],
                'workspace': {'id': user['workspace_id'], 'name': user['workspace_name'], 'owner_id': user['owner_id']},
                'default_workspace': user['default_workspace'],
                'platform_administrator': bool(user['platform_administrator'])}

    def start_login(self, poll_secret):
        if not isinstance(poll_secret, str) or len(poll_secret) < 40 or len(poll_secret) > 128:
            raise Failure('INVALID_ARGUMENT', 'Invalid login request.')
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM logins WHERE expires<=?', (now,))
            db.execute('DELETE FROM oauth WHERE expires<=?', (now,))
            db.execute('DELETE FROM browser_sessions WHERE expires<=?', (now,))
            db.execute('DELETE FROM requests WHERE expires<=?', (now,))
            existing = db.execute('SELECT * FROM logins WHERE poll_verifier=?', (digest(poll_secret),)).fetchone()
            if existing:
                return {'user_code': existing['code'], 'expires_in': max(0, int(existing['expires'] - now)), 'interval': 5}
            if db.execute('SELECT COUNT(*) FROM logins').fetchone()[0] >= 100:
                raise Failure('REQUEST_CONFLICT', 'Too many pending sign-ins; retry later.', 429)
            code = '-'.join(secrets.token_hex(3).upper() for _ in range(2))
            db.execute('INSERT INTO logins(code,poll_verifier,expires) VALUES(?,?,?)',
                       (code, digest(poll_secret), now + 600))
            return {'user_code': code, 'expires_in': 600, 'interval': 5}

    def begin_oauth(self, code, browser_secret):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.pending(db, code)
            if db.execute('SELECT COUNT(*) FROM oauth').fetchone()[0] >= 200:
                raise Failure('REQUEST_CONFLICT', 'Too many pending sign-ins.', 429)
            state, nonce, pkce = (secrets.token_urlsafe(32) for _ in range(3))
            db.execute('INSERT INTO oauth VALUES(?,?,?,?,?,?)',
                       (digest(state), digest(browser_secret), nonce, pkce, code, time.time() + 600))
            return state, nonce, pkce

    def take_oauth(self, state, browser_secret):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM oauth WHERE state=? AND browser_verifier=? AND expires>?',
                             (digest(state), digest(browser_secret), time.time())).fetchone()
            if not row:
                raise Failure('AUTH_REQUIRED', 'Sign-in state is invalid or expired.', 401)
            db.execute('DELETE FROM oauth WHERE state=?', (digest(state),))
            return dict(row)

    def bind_google(self, claims):
        subject, email = claims['sub'], email_address(claims['email'])
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            user = db.execute('SELECT * FROM workspace_users WHERE subject=?', (subject,)).fetchone()
            if not user:
                user = db.execute('SELECT * FROM workspace_users WHERE admission_email=? AND subject IS NULL AND member=1',
                                  (email,)).fetchone()
            if not user or not user['member']:
                raise Failure('FORBIDDEN', 'This Google account has not been admitted to the workspace.', 403)
            db.execute('UPDATE users SET subject=?,email=?,name=? WHERE id=?',
                       (subject, email, claims['name'], user['id']))
            token = secrets.token_urlsafe(32)
            db.execute('INSERT INTO browser_sessions VALUES(?,?,?)',
                       (digest(token), user['id'], time.time() + 43200))
            return token

    @staticmethod
    def pending(db, code):
        row = db.execute('SELECT * FROM logins WHERE code=? AND expires>? AND consumed=0',
                         (code, time.time())).fetchone()
        if not row:
            raise Failure('LOGIN_EXPIRED', 'CLI login expired or has already been used.', 401)
        return row

    def browser_user(self, db, token):
        row = db.execute('SELECT u.* FROM browser_sessions b JOIN workspace_users u ON u.id=b.user_id '
                         'WHERE b.verifier=? AND b.expires>? AND u.member=1', (digest(token), time.time())).fetchone()
        if not row:
            raise Failure('AUTH_REQUIRED', 'Browser sign-in required.', 401)
        return row

    def approval(self, code, browser_token, approve=False):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self.pending(db, code)
            user = self.browser_user(db, browser_token)
            if row['user_id']:
                raise Failure('REQUEST_CONFLICT', 'This login has already been approved.', 409)
            if approve:
                db.execute('UPDATE logins SET user_id=? WHERE code=?', (user['id'], code))
            return self.identity(user)

    def poll(self, poll_secret):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM logins WHERE poll_verifier=?', (digest(poll_secret),)).fetchone()
            if not row:
                raise Failure('LOGIN_EXPIRED', 'CLI login expired.', 401)
            row = self.pending(db, row['code'])
            if time.time() - row['last_poll'] < 5:
                return {'state': 'pending', 'interval': 5}
            db.execute('UPDATE logins SET last_poll=? WHERE code=?', (time.time(), row['code']))
            if not row['user_id']:
                return {'state': 'pending', 'interval': 5}
            user = db.execute('SELECT * FROM workspace_users WHERE id=? AND member=1', (row['user_id'],)).fetchone()
            if not user:
                raise Failure('FORBIDDEN', 'Workspace membership required.', 403)
            token, credential_id, expires = secrets.token_urlsafe(32), 'cred_' + uuid.uuid4().hex, time.time() + 2592000
            db.execute('INSERT INTO credentials(id,verifier,user_id,expires) VALUES(?,?,?,?)',
                       (credential_id, digest(token), user['id'], expires))
            db.execute('UPDATE logins SET consumed=1 WHERE code=?', (row['code'],))
            return {**self.identity(user), 'credential_id': credential_id, 'expires_at': timestamp(expires),
                    'credential': token, 'state': 'complete'}

    def credential(self, db, token, allow_revoked=False):
        row = db.execute('SELECT * FROM credentials WHERE verifier=?', (digest(token),)).fetchone()
        if not row:
            raise Failure('AUTH_REQUIRED', 'Sign in with small-cloud auth login.', 401)
        user = db.execute('SELECT * FROM workspace_users WHERE id=?', (row['user_id'],)).fetchone()
        if not user or not user['member']:
            raise Failure('FORBIDDEN', 'Saved workspace membership required; contact the operator.', 403)
        if (row['revoked'] or row['expires'] <= time.time()) and not allow_revoked:
            raise Failure('CREDENTIAL_REVOKED', 'Credential revoked or expired; sign in again.', 401)
        return row, user

    def status(self, token):
        with self.connect() as db:
            credential, user = self.credential(db, token)
            return {**self.identity(user), 'credential_id': credential['id'], 'expires_at': timestamp(credential['expires'])}

    def mutate(self, token, action, body, request_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            credential, user = self.credential(db, token, allow_revoked=action in ('logout', 'revoke'))
            fingerprint = digest(json.dumps([action, body, credential['id'] if action in ('logout', 'revoke') else None],
                                            sort_keys=True, separators=(',', ':')))
            if action.startswith('admin/') and not user['administrator']:
                raise Failure('FORBIDDEN', 'Only the workspace administrator can manage admission.', 403)
            db.execute('DELETE FROM requests WHERE expires<=?', (time.time(),))
            cached = db.execute('SELECT * FROM requests WHERE actor=? AND id=?', (user['id'], request_id)).fetchone()
            if cached:
                if cached['fingerprint'] != fingerprint:
                    raise Failure('REQUEST_CONFLICT', 'Request ID was already used with different inputs.', 409)
                return json.loads(cached['result'])
            if action == 'revoke':
                self.credential(db, token)
                db.execute('UPDATE credentials SET revoked=1 WHERE user_id=?', (user['id'],))
                result = {'revoked': True}
            elif action == 'logout':
                db.execute('UPDATE credentials SET revoked=1 WHERE id=?', (credential['id'],))
                result = {'revoked': True}
            elif action == 'admin/member/add':
                email = email_address(body.get('email'))
                member = db.execute('SELECT * FROM workspace_users WHERE workspace_id=? '
                                    'AND (admission_email=? OR email=?)',
                                    (user['workspace_id'], email, email)).fetchone()
                if not member:
                    user_id = 'usr_' + uuid.uuid4().hex
                    db.execute('INSERT INTO users(id,admission_email,email,default_workspace) VALUES(?,?,?,?)',
                               (user_id, email, email, user['workspace_id']))
                    db.execute('INSERT INTO memberships VALUES(?,?,1,0,0)', (user['workspace_id'], user_id))
                    member = db.execute('SELECT * FROM workspace_users WHERE id=?', (user_id,)).fetchone()
                result = self.membership(member)
            elif action == 'admin/creator/grant':
                member = db.execute('SELECT * FROM workspace_users WHERE id=? AND workspace_id=? '
                                    'AND member=1 AND subject IS NOT NULL',
                                    (body.get('user_id'), user['workspace_id'])).fetchone()
                if not member:
                    raise Failure('NOT_FOUND', 'Member must complete Google sign-in before a creator grant.', 404)
                if not member['creator'] and db.execute('SELECT COUNT(*) FROM memberships WHERE creator=1').fetchone()[0] >= 5:
                    raise Failure('CREATOR_CAPACITY', 'All five creator grants are occupied.', 409, limit=5)
                db.execute('UPDATE memberships SET creator=1 WHERE user_id=? AND workspace_id=?',
                           (member['id'], user['workspace_id']))
                result = {**self.membership(member), 'creator': True}
            else:
                raise Failure('NOT_FOUND', 'Unknown operation.', 404)
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?)',
                       (user['id'], request_id, fingerprint, json.dumps(result), time.time() + 604800))
            return result
