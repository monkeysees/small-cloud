"""Durable HTTP idle stopping and capacity reservations for retained releases."""
from contextlib import contextmanager
import fcntl
import json
import os
import time

from .common import Failure

IDLE_SECONDS = 1800
RESERVED = "(a.target_port IS NOT NULL OR a.id IN (SELECT app_id FROM deployments WHERE state IN ('starting','cleaning')) OR a.runtime_state IN ('queued','starting','stopping','cleaning','blocked'))"


def initialize(db, now):
    columns = {row[1] for row in db.execute('PRAGMA table_info(apps)')}
    if 'runtime_state' not in columns:
        db.execute("ALTER TABLE apps ADD COLUMN runtime_state TEXT NOT NULL DEFAULT 'unavailable'")
        db.execute('ALTER TABLE apps ADD COLUMN last_http REAL')
        db.execute('ALTER TABLE apps ADD COLUMN runtime_error TEXT')
        db.execute("UPDATE apps SET runtime_state=CASE WHEN target_port IS NOT NULL THEN 'running' "
                   "WHEN active_deployment_id IS NOT NULL THEN 'stopped' ELSE 'unavailable' END, last_http=?", (now,))


def reserve(db, app):
    if db.execute('SELECT 1 FROM apps a WHERE a.id=? AND ' + RESERVED, (app['id'],)).fetchone():
        return
    if db.execute('SELECT COUNT(*) FROM apps a WHERE ' + RESERVED).fetchone()[0] >= 5:
        raise Failure('ACTIVE_CAPACITY', 'All five active app slots are occupied. Retry when capacity is available.', 503, limit=5)


@contextmanager
def app_lock(state, app_id, exclusive=False):
    # Kernel locks survive arbitrarily long requests and release on process loss.
    # State.connect also selects the service identity in the privileged worker.
    with state.connect():
        directory = state.path.parent / 'runtime-locks'
        directory.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(directory / app_id, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            yield True
    finally:
        os.close(fd)


class LifecycleWorker:
    def __init__(self, state, infrastructure, clock=time.time, registry=None):
        self.state, self.infrastructure, self.clock = state, infrastructure, clock
        self.registry = registry
        from .app_secrets import Vault
        self.secrets = Vault(state)

    def recover(self):
        with self.state.connect() as db:
            db.execute("UPDATE apps SET runtime_state='stopping' WHERE id IN "
                       "(SELECT app_id FROM deployments WHERE kind='secret-change' AND state NOT IN ('succeeded','failed'))")
        with self.state.connect() as db:
            db.execute("UPDATE apps SET runtime_state='cleaning' WHERE runtime_state IN ('starting','blocked')")

    def once(self):
        with self.state.connect() as db:
            rows = db.execute("SELECT id FROM apps a WHERE runtime_state IN ('stopping','cleaning','queued') OR "
                              "(runtime_state='running' AND last_http<=? AND NOT EXISTS "
                              "(SELECT 1 FROM deployments WHERE app_id=a.id AND state NOT IN ('succeeded','failed'))) "
                              "ORDER BY CASE WHEN runtime_state='queued' THEN 1 ELSE 0 END, last_http",
                              (self.clock() - IDLE_SECONDS,)).fetchall()
        for row in rows:
            with app_lock(self.state, row['id'], exclusive=True) as acquired:
                if acquired and self.process(row['id']):
                    return True
        return False

    def process(self, app_id):
        with self.state.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            app = dict(db.execute('SELECT * FROM apps WHERE id=?', (app_id,)).fetchone())
            secret = db.execute("SELECT * FROM deployments WHERE app_id=? AND kind='secret-change' "
                                "AND state NOT IN ('succeeded','failed')", (app_id,)).fetchone()
            state = app['runtime_state']
            if state == 'running':
                if app['last_http'] > self.clock() - IDLE_SECONDS or db.execute(
                        "SELECT 1 FROM deployments WHERE app_id=? AND state NOT IN ('succeeded','failed')", (app_id,)).fetchone():
                    return False
                state = 'stopping'
            elif state not in ('queued', 'stopping', 'cleaning'):
                return False
            db.execute('UPDATE apps SET runtime_state=? WHERE id=?',
                       ('starting' if state == 'queued' else state, app_id))
        try:
            if secret:
                self.infrastructure.stop(app)
                with self.state.connect() as db:
                    db.execute('UPDATE retired_secrets SET expires=? WHERE app_id=? AND expires IS NULL',
                               (self.clock() + 7 * 86400, app_id))
                    db.execute("UPDATE deployments SET state='starting' WHERE id=?", (secret['id'],))
                state = 'queued'
            if state == 'queued':
                if not app['active_deployment_id']:
                    raise Failure('STARTUP_FAILED', 'Configuration is saved; deploy a release before starting this app.', 503)
                app['runtime_environment'] = self.secrets.environment(app_id)
                target = self.infrastructure.wake(app, lambda values: self.registry.register(
                    app['active_deployment_id'], values) if self.registry else None)
                self.infrastructure.ready(target)
                with self.state.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    allowed = db.execute('SELECT 1 FROM apps a JOIN memberships m ON m.user_id=a.owner '
                                         'AND m.workspace_id=a.workspace_id WHERE a.id=? AND a.disabled=0 '
                                         'AND m.member=1 AND m.creator=1', (app_id,)).fetchone()
                    if not allowed:
                        raise Failure('APP_DISABLED', 'App authority changed during startup.', 403)
                    db.execute("UPDATE apps SET runtime_state='running',runtime_error=NULL,target_host=?,target_port=?,"
                               'container=?,last_http=? WHERE id=?',
                               (target['host'], target['port'], target['container'], self.clock(), app_id))
            else:
                self.infrastructure.stop(app)
                with self.state.connect() as db:
                    db.execute("UPDATE apps SET runtime_state='stopped',runtime_error=NULL,target_host=NULL,target_port=NULL,container=NULL "
                               'WHERE id=?', (app_id,))
        except (Failure, OSError, ValueError, KeyError) as error:
            failure = error if isinstance(error, Failure) else Failure('STARTUP_FAILED', 'App startup failed. Retry to start again.', 503)
            try:
                self.infrastructure.stop(app)
                if secret:
                    with self.state.connect() as db:
                        db.execute('UPDATE retired_secrets SET expires=? WHERE app_id=? AND expires IS NULL',
                                   (self.clock() + 7 * 86400, app_id))
                result = 'failed' if state == 'queued' or secret else 'stopped'
            except (Failure, OSError, ValueError):
                result = 'blocked'
                failure = Failure('STARTUP_FAILED', 'Runtime cleanup requires operator inspection.', 503,
                                  reconciliation_required=True)
            with self.state.connect() as db:
                db.execute('UPDATE apps SET runtime_state=?,target_host=NULL,target_port=NULL,container=NULL,runtime_error=? '
                           'WHERE id=?', (result, json.dumps({'code': failure.code, 'message': failure.message,
                                                           'details': failure.details}), app_id))
        if secret:
            with self.state.connect() as db:
                current = db.execute('SELECT runtime_state,runtime_error FROM apps WHERE id=?', (app_id,)).fetchone()
                error = json.loads(current['runtime_error']) if current['runtime_error'] else None
                if error:
                    error['code'] = 'STARTUP_FAILED'
                    error['details']['configuration_saved'] = True
                    error['details']['operation_id'] = secret['id']
                    error['retryable'] = False
                blocked = current['runtime_state'] == 'blocked'
                db.execute('UPDATE deployments SET state=?,finished=?,error=? WHERE id=?',
                           ('cleaning' if blocked else 'succeeded' if current['runtime_state'] == 'running' else 'failed',
                            None if blocked else self.clock(), json.dumps(error) if error else None, secret['id']))
        return True
