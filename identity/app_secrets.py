"""Encrypted app configuration and durable restart admission."""
import hashlib
import hmac
import json
import os
import re
import stat
import time
import uuid

from cryptography.fernet import Fernet
from .common import Failure
from . import lifecycle

NOTICE = ('Authorized app users can trigger credential-backed actions exposed by app code. '
          'Use appropriately scoped credentials; app code can disclose entrusted secrets.')


def validate(name, value=None):
    if (not isinstance(name, str) or not re.fullmatch(r'[A-Z_][A-Z0-9_]{0,127}', name)
            or name in ('PORT', 'DATABASE_URL') or name.startswith('SMALL_CLOUD_')):
        raise Failure('INVALID_ARGUMENT', 'Invalid or platform-reserved secret name.')
    if value is not None and (not isinstance(value, str) or '\0' in value
                              or not 1 <= len(value.encode('utf-8')) <= 16384):
        raise Failure('INVALID_ARGUMENT', 'Secret value must be 1–16384 UTF-8 bytes without NUL.')


def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS app_secrets (
            app_id TEXT NOT NULL, name TEXT NOT NULL, value BLOB NOT NULL,
            PRIMARY KEY(app_id,name));
        CREATE TABLE IF NOT EXISTS retired_secrets (
            app_id TEXT NOT NULL, operation TEXT NOT NULL, value BLOB NOT NULL, expires REAL);
    ''')
    if 'kind' not in {row[1] for row in db.execute('PRAGMA table_info(deployments)')}:
        db.execute("ALTER TABLE deployments ADD COLUMN kind TEXT NOT NULL DEFAULT 'deploy'")


class Vault:
    def __init__(self, state):
        self.state = state
        path = state.path.parent / 'app-secrets.key'
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(Fernet.generate_key())
                stream.flush()
                os.fsync(stream.fileno())
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_uid != state.path.stat().st_uid):
                raise ValueError('Unsafe app secret key')
            self.key = stream.read(1024)
        self.cipher = Fernet(self.key)

    def environment(self, app_id):
        with self.state.connect() as db:
            return {row['name']: self.cipher.decrypt(row['value']).decode() for row in
                    db.execute('SELECT name,value FROM app_secrets WHERE app_id=?', (app_id,))}

    def redactions(self, app_id, now):
        with self.state.connect() as db:
            rows = db.execute('SELECT value FROM app_secrets WHERE app_id=? UNION ALL '
                              'SELECT value FROM retired_secrets WHERE app_id=? AND (expires IS NULL OR expires>?)',
                              (app_id, app_id, now)).fetchall()
        return [self.cipher.decrypt(row['value']) for row in rows]

    @staticmethod
    def owner(publishing, db, token, name):
        _, user = publishing.store.credential(db, token)
        app = db.execute('SELECT * FROM apps WHERE name=? AND owner=? AND workspace_id=?',
                         (name, user['id'], user['workspace_id'])).fetchone()
        if not app:
            raise Failure('NOT_FOUND', 'App not found.', 404)
        if not user['creator']:
            raise Failure('FORBIDDEN', 'Secret management requires creator authority.', 403)
        return app, user

    def names(self, publishing, token, name):
        with self.state.connect() as db:
            app, _ = self.owner(publishing, db, token, name)
            return {'names': [row[0] for row in db.execute(
                'SELECT name FROM app_secrets WHERE app_id=? ORDER BY name', (app['id'],))]}

    def change(self, publishing, token, name, action, body, request_id):
        allowed = {'name', 'value', 'acknowledge_secret_authority'} if action == 'set' else {'name'}
        if set(body) - allowed or 'name' not in body or (action == 'set' and not isinstance(body.get('value'), str)):
            raise Failure('INVALID_ARGUMENT', 'Supply a secret name and a value for set.')
        if 'acknowledge_secret_authority' in body and not isinstance(body['acknowledge_secret_authority'], bool):
            raise Failure('INVALID_ARGUMENT', 'Acknowledgement must be boolean.')
        validate(body['name'], body.get('value'))
        fingerprint = hmac.new(self.key, json.dumps(['secret', action, name, body], sort_keys=True).encode(), hashlib.sha256).hexdigest()
        with self.state.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            app, user = self.owner(publishing, db, token, name)
            if app['disabled']:
                raise Failure('APP_DISABLED', 'App is disabled.', 403)
            cached = db.execute('SELECT * FROM requests WHERE actor=? AND id=? AND expires>?',
                                (user['id'], request_id, time.time())).fetchone()
            if cached:
                if cached['fingerprint'] != fingerprint:
                    raise Failure('REQUEST_CONFLICT', 'Request ID was used with different inputs.', 409)
                return json.loads(cached['result'])
            if action == 'set' and app['sharing_scope'] == 'workspace-wide' and body.get('acknowledge_secret_authority') is not True:
                raise Failure('ACKNOWLEDGEMENT_REQUIRED', NOTICE)
            old = db.execute('SELECT value FROM app_secrets WHERE app_id=? AND name=?', (app['id'], body['name'])).fetchone()
            result = {'app': name, 'changed': False, 'state': 'succeeded'}
            if action == 'set' or old:
                if (app['runtime_state'] in ('queued', 'starting', 'stopping', 'cleaning', 'blocked') or db.execute(
                        "SELECT 1 FROM deployments WHERE app_id=? AND state NOT IN ('succeeded','failed')", (app['id'],)).fetchone()):
                    raise Failure('OPERATION_CONFLICT', 'App already has an operation in progress.', 409)
                try:
                    lifecycle.reserve(db, app)
                except Failure as error:
                    raise Failure(error.code, error.message, 409, **error.details) from None
                if action == 'set' and not old and db.execute('SELECT COUNT(*) FROM app_secrets WHERE app_id=?', (app['id'],)).fetchone()[0] >= 50:
                    raise Failure('INVALID_ARGUMENT', 'At most 50 secret names are allowed per app.')
                operation = 's-' + uuid.uuid4().hex[:24]
                if old:
                    db.execute('INSERT INTO retired_secrets VALUES(?,?,?,NULL)', (app['id'], operation, old['value']))
                db.execute('DELETE FROM app_secrets WHERE app_id=? AND name=?', (app['id'], body['name']))
                if action == 'set':
                    db.execute('INSERT INTO app_secrets VALUES(?,?,?)', (app['id'], body['name'], self.cipher.encrypt(body['value'].encode())))
                db.execute("INSERT INTO deployments(id,app_id,actor,request_id,state,created,kind) VALUES(?,?,?,?,'accepted',?,'secret-change')",
                           (operation, app['id'], user['id'], request_id, publishing.clock()))
                db.execute("UPDATE apps SET runtime_state='stopping',target_host=NULL,target_port=NULL WHERE id=?", (app['id'],))
                result = {'app': name, 'changed': True, 'configuration_saved': True, 'operation_id': operation, 'state': 'accepted'}
            db.execute('DELETE FROM requests WHERE actor=? AND id=?', (user['id'], request_id))
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?)', (user['id'], request_id, fingerprint, json.dumps(result), time.time() + 604800))
            return result
