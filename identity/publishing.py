"""Durable deployment admission and authorized publishing observations."""
import hashlib
import json
import re
import time
import uuid
from contextlib import contextmanager
from urllib.parse import urlsplit

from .common import Failure, digest, timestamp
from .upload import validate_archive
from . import allowance, diagnostics, lifecycle


class Publishing:
    def __init__(self, store, origin, clock=time.time):
        self.store = store
        self.clock = clock
        domain = urlsplit(origin).hostname
        if not domain:
            raise ValueError('Publishing origin must have a hostname')
        self.domain: str = domain
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS apps (
                    id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, owner TEXT NOT NULL,
                    workspace_id TEXT NOT NULL DEFAULT 'ws-initial' CHECK(workspace_id='ws-initial'),
                    description TEXT NOT NULL, sharing_scope TEXT NOT NULL DEFAULT 'creator-only',
                    disabled INTEGER NOT NULL DEFAULT 0, active_deployment_id TEXT,
                    target_host TEXT, target_port INTEGER, container TEXT,
                    created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS deployments (
                    id TEXT PRIMARY KEY, app_id TEXT NOT NULL, actor TEXT NOT NULL,
                    request_id TEXT NOT NULL, state TEXT NOT NULL, source BLOB,
                    created REAL NOT NULL, finished REAL, error TEXT,
                    candidate_host TEXT, candidate_port INTEGER, candidate_container TEXT,
                    previous_container TEXT, cleanup_pending INTEGER NOT NULL DEFAULT 0);
            ''')
            diagnostics.initialize(db)
            db.execute('BEGIN IMMEDIATE')
            allowance.initialize(db)
            lifecycle.initialize(db, self.clock())

    def deploy(self, token, metadata, archive, request_id):
        name = metadata.get('name')
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,62}', name):
            raise Failure('INVALID_ARGUMENT', 'App name must be a lowercase ASCII slug of at most 63 characters.')
        if 'description' in metadata and (not isinstance(metadata['description'], str) or len(metadata['description']) > 500):
            raise Failure('INVALID_ARGUMENT', 'Description must be text of at most 500 characters.')
        if set(metadata) - {'name', 'description'}:
            raise Failure('INVALID_ARGUMENT', 'Unknown deployment input.')
        validate_archive(archive)
        fingerprint = digest(json.dumps(['deploy', metadata, hashlib.sha256(archive).hexdigest()], sort_keys=True))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            _, user = self.store.credential(db, token)
            if not user['creator']:
                raise Failure('FORBIDDEN', 'Publishing requires creator authority.', 403)
            app = db.execute('SELECT * FROM apps WHERE name=?', (name,)).fetchone()
            if app and (app['workspace_id'] != user['workspace_id'] or app['owner'] != user['id']):
                raise Failure('NOT_FOUND', 'App not found.', 404)
            if app and app['disabled']:
                raise Failure('APP_DISABLED', 'App is disabled.', 403)
            cached = db.execute('SELECT * FROM requests WHERE actor=? AND id=? AND expires>?',
                                (user['id'], request_id, time.time())).fetchone()
            if cached:
                if cached['fingerprint'] != fingerprint:
                    raise Failure('REQUEST_CONFLICT', 'Request ID was used with different inputs.', 409)
                return json.loads(cached['result'])
            if app and app['runtime_state'] in ('queued', 'starting', 'stopping', 'cleaning', 'blocked'):
                raise Failure('OPERATION_CONFLICT', 'App runtime has an operation in progress.', 409)
            if app and db.execute("SELECT 1 FROM deployments WHERE app_id=? AND state NOT IN ('succeeded','failed')",
                                  (app['id'],)).fetchone():
                raise Failure('OPERATION_CONFLICT', 'App already has an operation in progress.', 409)
            if db.execute("SELECT 1 FROM deployments WHERE actor=? AND state NOT IN ('succeeded','failed')",
                          (user['id'],)).fetchone():
                raise Failure('BUILD_BUSY', 'Creator already has an accepted build.', 409)
            if not app:
                if 'description' not in metadata:
                    raise Failure('INVALID_ARGUMENT', 'New apps require a description; empty text is allowed.')
                if db.execute('SELECT COUNT(*) FROM apps').fetchone()[0] >= 30:
                    raise Failure('DEPLOYED_CAPACITY', 'All thirty deployed app slots are occupied.', 409, limit=30)
                app_id = 'a-' + uuid.uuid4().hex[:24]
                db.execute('INSERT INTO apps(id,name,owner,description,created,workspace_id) VALUES(?,?,?,?,?,?)',
                           (app_id, name, user['id'], metadata['description'], time.time(), user['workspace_id']))
                app = db.execute('SELECT * FROM apps WHERE id=?', (app_id,)).fetchone()
            elif 'description' in metadata:
                db.execute('UPDATE apps SET description=? WHERE id=?', (metadata['description'], app['id']))
            operation_id = 'd-' + uuid.uuid4().hex[:24]
            now = self.clock()
            allowance.reserve(db, operation_id, user['workspace_id'], now)
            db.execute('INSERT INTO deployments(id,app_id,actor,request_id,state,source,created) VALUES(?,?,?,?,?,?,?)',
                       (operation_id, app['id'], user['id'], request_id, 'accepted', archive, now))
            result = {'operation_id': operation_id, 'state': 'accepted', 'app': name,
                      'url': self.url(app), 'active_deployment_id': app['active_deployment_id']}
            db.execute('DELETE FROM requests WHERE actor=? AND id=?', (user['id'], request_id))
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?)',
                       (user['id'], request_id, fingerprint, json.dumps(result), time.time() + 604800))
            return result

    def usage(self, token):
        with self.store.connect() as db:
            db.execute('BEGIN')
            _, user = self.store.credential(db, token)
            if not (user['creator'] or user['administrator']):
                raise Failure('FORBIDDEN', 'Usage requires creator or administrator authority.', 403)
            workspace = user['workspace_id']
            creators = db.execute('SELECT COUNT(*) FROM memberships WHERE workspace_id=? AND creator=1 AND member=1',
                                  (workspace,)).fetchone()[0]
            apps = db.execute('SELECT COUNT(*), COUNT(*) FILTER (WHERE ' + lifecycle.RESERVED + ') '
                              'FROM apps a WHERE workspace_id=?', (workspace,)).fetchone()
            return {'creators': {'used': creators, 'limit': 5}, 'deployed_apps': {'used': apps[0], 'limit': 30},
                    'active_apps': {'used': apps[1], 'limit': 5},
                    'build': allowance.usage(db, workspace, self.clock())}

    def url(self, app):
        return 'https://' + app['id'] + '.' + self.domain

    def share(self, token, name, body, request_id):
        if set(body) != {'scope'} or body['scope'] not in ('creator-only', 'workspace-wide'):
            raise Failure('INVALID_ARGUMENT', 'Supply scope creator-only or workspace-wide.')
        fingerprint = digest(json.dumps(['share', name, body], sort_keys=True))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            _, user = self.store.credential(db, token)
            app = db.execute('SELECT * FROM apps WHERE name=? AND owner=?', (name, user['id'])).fetchone()
            if not app or app['workspace_id'] != user['workspace_id']:
                raise Failure('NOT_FOUND', 'App not found.', 404)
            if not user['creator']:
                raise Failure('FORBIDDEN', 'Sharing requires creator authority.', 403)
            if app['disabled']:
                raise Failure('APP_DISABLED', 'App is disabled.', 403)
            cached = db.execute('SELECT * FROM requests WHERE actor=? AND id=? AND expires>?',
                                (user['id'], request_id, time.time())).fetchone()
            if cached:
                if cached['fingerprint'] != fingerprint:
                    raise Failure('REQUEST_CONFLICT', 'Request ID was used with different inputs.', 409)
                return json.loads(cached['result'])
            db.execute('UPDATE apps SET sharing_scope=? WHERE id=?', (body['scope'], app['id']))
            result = {'app': name, 'sharing_scope': body['scope'], 'secret_authority_acknowledged': False}
            db.execute('DELETE FROM requests WHERE actor=? AND id=?', (user['id'], request_id))
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?)',
                       (user['id'], request_id, fingerprint, json.dumps(result), time.time() + 604800))
            return result

    def authorized_app(self, db, token, name):
        _, user = self.store.credential(db, token)
        app = db.execute('SELECT * FROM apps WHERE name=?', (name,)).fetchone()
        if (not app or app['workspace_id'] != user['workspace_id']
                or (app['owner'] != user['id'] and not user['administrator'])):
            raise Failure('NOT_FOUND', 'App not found.', 404)
        return app

    @staticmethod
    def operation_result(row, app):
        return {'id': row['id'], 'kind': 'deploy', 'app': app,
                'operation_id': row['id'], 'deployment_id': row['id'], 'state': row['state'],
                'request_id': row['request_id'], 'created_at': timestamp(row['created']),
                'updated_at': timestamp(row['finished'] or row['created']),
                'completed_at': timestamp(row['finished']) if row['finished'] else None,
                'error': json.loads(row['error']) if row['error'] else None,
                'cleanup_pending': bool(row['cleanup_pending'])}

    def status(self, token, name):
        with self.store.connect() as db:
            app = self.authorized_app(db, token, name)
            latest = db.execute('SELECT * FROM deployments WHERE app_id=? ORDER BY created DESC LIMIT 1',
                                (app['id'],)).fetchone()
            return {'app': app['name'], 'app_id': app['id'], 'description': app['description'],
                    'url': self.url(app), 'sharing_scope': app['sharing_scope'],
                    'availability': 'disabled' if app['disabled'] else 'running' if app['target_port'] else
                                    'starting' if app['runtime_state'] in ('queued', 'starting', 'stopping') else
                                    'stopped' if app['runtime_state'] == 'stopped' else 'unavailable',
                    'runtime_error': json.loads(app['runtime_error']) if app['runtime_error'] else None,
                    'active_deployment_id': app['active_deployment_id'],
                    'latest_operation': self.operation_result(latest, app['name']) if latest else None,
                    'cleanup': None}

    def operation(self, token, operation_id=None, request_id=None):
        with self.store.connect() as db:
            _, user = self.store.credential(db, token)
            if request_id:
                row = db.execute('SELECT * FROM deployments WHERE actor=? AND request_id=? ORDER BY created DESC LIMIT 1',
                                 (user['id'], request_id)).fetchone()
            else:
                row = db.execute('SELECT * FROM deployments WHERE id=?', (operation_id,)).fetchone()
            if not row or (row['actor'] != user['id'] and not user['administrator']):
                raise Failure('NOT_FOUND', 'Operation not found.', 404)
            app = db.execute('SELECT name FROM apps WHERE id=? AND workspace_id=?',
                             (row['app_id'], user['workspace_id'])).fetchone()
            if not app:
                raise Failure('NOT_FOUND', 'Operation not found.', 404)
            return self.operation_result(row, app['name'])

    def logs(self, token, name, source, deployment=None, since=None, limit=100, cursor=None):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            app = self.authorized_app(db, token, name)
            _, user = self.store.credential(db, token)
            return diagnostics.snapshot(db, user['id'], app, source, deployment, since, limit, cursor, self.clock())

    @staticmethod
    def accessible_apps(db, user_id, app_id=None):
        return db.execute('SELECT a.*, owner.name AS creator_name FROM apps a '
                          'JOIN users owner ON owner.id=a.owner '
                          'JOIN memberships author ON author.user_id=a.owner AND author.workspace_id=a.workspace_id '
                          'JOIN memberships viewer ON viewer.user_id=? AND viewer.workspace_id=a.workspace_id '
                          'WHERE author.member=1 AND viewer.member=1 AND a.disabled=0 '
                          "AND (a.owner=viewer.user_id OR a.sharing_scope='workspace-wide') "
                          'AND (? IS NULL OR a.id=?) ORDER BY a.name', (user_id, app_id, app_id))

    def directory(self, token):
        with self.store.connect() as db:
            _, user = self.store.credential(db, token)
            return {'apps': [{'name': app['name'], 'description': app['description'],
                              'creator': {'id': app['owner'], 'name': app['creator_name']},
                              'url': self.url(app)} for app in self.accessible_apps(db, user['id'])]}

    def check_access(self, app_id, user_id):
        with self.store.connect() as db:
            if not self.accessible_apps(db, user_id, app_id).fetchone():
                raise Failure('NOT_FOUND', 'App not found.', 404)

    @contextmanager
    def gateway_request(self, app_id, user_id, retry=False):
        self.check_access(app_id, user_id)
        with lifecycle.app_lock(self.store, app_id) as acquired:
            if not acquired:
                raise Failure('STARTING', 'App is starting or stopping. Retry shortly.', 503)
            target = self.gateway_target(app_id, user_id, retry)
            try:
                yield target
            finally:
                if target.get('forwarded'):
                    with self.store.connect() as db:
                        db.execute('UPDATE apps SET last_http=? WHERE id=?', (self.clock(), app_id))

    def gateway_target(self, app_id, user_id, retry=False):
        failure = None
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            app = self.accessible_apps(db, user_id, app_id).fetchone()
            if not app:
                raise Failure('NOT_FOUND', 'App not found.', 404)
            if app['target_host'] and app['target_port']:
                return {'host': app['target_host'], 'port': app['target_port']}
            if app['runtime_state'] == 'blocked':
                raise Failure('STARTUP_FAILED', 'Runtime cleanup requires operator inspection.', 503, reconciliation_required=True)
            if app['runtime_state'] == 'failed' and not retry:
                raise Failure('STARTUP_FAILED', 'App startup failed. Retry to start again.', 503)
            if app['runtime_state'] in ('stopped', 'failed'):
                pending = db.execute("SELECT 1 FROM deployments WHERE app_id=? AND state NOT IN ('succeeded','failed')",
                                     (app_id,)).fetchone()
                if not pending:
                    lifecycle.reserve(db, app)
                    db.execute("UPDATE apps SET runtime_state='queued',runtime_error=NULL WHERE id=?", (app_id,))
                failure = Failure('STARTING', 'Starting app. This can take up to two minutes after runtime launch.', 503)
            else:
                pending = db.execute("SELECT 1 FROM deployments WHERE app_id=? AND state NOT IN ('succeeded','failed')",
                                     (app_id,)).fetchone()
                failure = Failure('STARTING' if pending or app['runtime_state'] in ('queued', 'starting', 'stopping', 'cleaning')
                                  else 'STARTUP_FAILED', 'App is not ready.', 503)
        # Commit a cold-start reservation before reporting progress to the caller.
        raise failure

    def certificate_allowed(self, hostname):
        suffix = '.' + self.domain
        if not isinstance(hostname, str) or not hostname.endswith(suffix):
            return False
        app_id = hostname[:-len(suffix)]
        if not re.fullmatch(r'a-[0-9a-f]{24}', app_id):
            return False
        with self.store.connect() as db:
            return db.execute('SELECT 1 FROM apps WHERE id=?', (app_id,)).fetchone() is not None
