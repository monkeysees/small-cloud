"""First-workspace migration through service startup and authenticated HTTP/CLI."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import unittest
import uuid

from identity.tests import test_deployment_http as fixture
from identity.tests import test_identity_cli as identity_fixture


class WorkspaceMigrationAcceptance(unittest.TestCase):
    setUp = fixture.DeploymentAcceptance.setUp
    operator = fixture.DeploymentAcceptance.operator
    start_platform = fixture.DeploymentAcceptance.start_platform
    restart_platform = identity_fixture.IdentityAcceptance.restart_platform
    http = fixture.DeploymentAcceptance.http
    http_login = fixture.DeploymentAcceptance.http_login
    approve = fixture.DeploymentAcceptance.approve
    cli = fixture.DeploymentAcceptance.cli
    login = fixture.DeploymentAcceptance.login
    deploy = fixture.DeploymentAcceptance.deploy

    def legacy(self):
        directory = self.home / 'server'
        directory.mkdir(mode=0o700)
        path = directory / 'identity.sqlite3'
        with sqlite3.connect(path) as db:
            db.executescript(Path(__file__).with_name('legacy-workspace.sql').read_text())
            for user, creator, admin in (('admin', 0, 1), ('creator', 1, 0), ('member', 0, 0)):
                db.execute('INSERT INTO users VALUES(?,?,?,?,?,1,?,?)',
                           ('usr_' + user, user + '@example.test', user + '-sub', user,
                            user + '@example.test', creator, admin))
                db.execute('INSERT INTO credentials VALUES(?,?,?,?,0)',
                           ('cred_' + user, hashlib.sha256((user + '-token').encode()).hexdigest(),
                            'usr_' + user, time.time() + 3600))
                db.execute('INSERT INTO app_sessions VALUES(?,?,?,?)',
                           (hashlib.sha256((user + '-session').encode()).hexdigest(),
                            'a-111111111111111111111111', 'usr_' + user, time.time() + 3600))
            db.execute("INSERT INTO apps(id,name,owner,description,sharing_scope,created) "
                       "VALUES('a-111111111111111111111111','example','usr_creator','Retained board','workspace-wide',1)")
        path.chmod(0o600)
        self.token = 'creator-token'

    def test_legacy_credentials_keep_roles_and_gain_a_saved_workspace_after_restart(self):
        self.legacy()
        self.start_platform()
        for iteration in range(2):
            if iteration:
                self.restart_platform()
            for user, roles in (('admin', ['member', 'administrator']),
                                ('creator', ['member', 'creator']), ('member', ['member'])):
                status, raw = self.http('/api/auth/status', token=user + '-token')
                self.assertEqual(status, 200, raw)
                identity = json.loads(raw)['data']
                self.assertEqual(identity['user']['id'], 'usr_' + user)
                self.assertEqual(identity['roles'], roles)
                self.assertEqual(identity['workspace'], {'id': 'ws-initial', 'name': 'Initial workspace',
                                                       'owner_id': 'usr_admin'})
                self.assertEqual(identity['default_workspace'], 'ws-initial')
                self.assertEqual(identity['platform_administrator'], user == 'admin')

    def test_migrated_publication_directory_and_sharing_keep_app_identity(self):
        self.legacy()
        self.start_platform()
        host = 'a-111111111111111111111111.cloud.example.test'
        for scope in ('workspace-wide', 'creator-only', 'workspace-wide'):
            status, raw = self.http('/api/apps/example/share', {'scope': scope}, token=self.token,
                                   headers={'X-Request-ID': str(uuid.uuid4())})
            self.assertEqual(status, 200, raw)
            for user in ('admin', 'creator', 'member'):
                status, raw = self.http('/api/directory', token=user + '-token')
                self.assertEqual(status, 200, raw)
                apps = json.loads(raw)['data']['apps']
                allowed = user == 'creator' or scope == 'workspace-wide'
                self.assertEqual([app['url'] for app in apps], ['https://' + host] if allowed else [])
                self.assertEqual(self.http('/', token=user + '-token', headers={'Host': host})[0],
                                 503 if allowed else 404)
                self.assertEqual(self.http('/', headers={'Host': host,
                                 'Cookie': '__Host-small-cloud-app=' + user + '-session'})[0],
                                 503 if allowed else 404)
        self.assertEqual(self.deploy()[0], 202)
        status, raw = self.http('/api/apps/example', token=self.token)
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)['data']['url'], 'https://' + host)
        self.assertEqual(self.deploy(name='forbidden', token='admin-token')[0], 403)

    def test_invalid_legacy_state_fails_visibly_and_can_be_repaired_then_retried(self):
        self.legacy()
        path = self.home / 'server' / 'identity.sqlite3'
        for invalid, repair in (
                ("UPDATE users SET administrator=0 WHERE id='usr_admin'",
                 "UPDATE users SET administrator=1 WHERE id='usr_admin'"),
                ("UPDATE apps SET owner='missing'", "UPDATE apps SET owner='usr_creator'")):
            with sqlite3.connect(path) as db:
                db.execute(invalid)
            result = self.operator('bootstrap', 'admin@example.test')
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual(json.loads(result.stdout)['error']['code'], 'MIGRATION_REQUIRED')
            with sqlite3.connect(path) as db:
                db.execute(repair)
        self.assertEqual(self.operator('bootstrap', 'admin@example.test').returncode, 0)
        self.start_platform()
        self.assertEqual(self.http('/api/apps/example', token=self.token)[0], 200)

    def test_membership_is_required_even_for_platform_administration_and_retained_sessions(self):
        self.legacy()
        self.start_platform()
        path = self.home / 'server' / 'identity.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute("UPDATE users SET platform_administrator=1 WHERE id='usr_member'")
        self.assertEqual(self.http('/api/admin/member/add', {'email': 'intruder@example.test'},
                                  token='member-token', headers={'X-Request-ID': str(uuid.uuid4())})[0], 403)
        self.assertEqual(self.deploy(token='member-token')[0], 403)
        with sqlite3.connect(path) as db:
            db.execute("UPDATE memberships SET member=0 WHERE user_id='usr_creator'")
            db.execute("UPDATE users SET platform_administrator=1 WHERE id='usr_creator'")
        for route in ('/api/auth/status', '/api/directory', '/api/apps/example'):
            self.assertEqual(self.http(route, token=self.token)[0], 403)
        self.assertEqual(self.deploy()[0], 403)
        self.assertEqual(self.http('/', headers={'Host': 'a-111111111111111111111111.cloud.example.test',
                              'Cookie': '__Host-small-cloud-app=creator-session'})[0], 401)
        self.assertEqual(self.http('/api/admin/member/add', {'email': 'intruder@example.test'},
                                  token=self.token, headers={'X-Request-ID': str(uuid.uuid4())})[0], 403)
        self.assertEqual(self.http('/api/workspaces/create', {'name': 'Second', 'owner_email': 'new@example.test'},
                                  token='admin-token', headers={'X-Request-ID': str(uuid.uuid4())})[0], 200)

    def test_pending_admissions_and_browser_cli_login_use_the_first_workspace_without_prompting(self):
        self.legacy()
        with sqlite3.connect(self.home / 'server' / 'identity.sqlite3') as db:
            db.execute("INSERT INTO users(id,admission_email,email) VALUES('usr_pending',"
                       "'pending@example.test','pending@example.test')")
        self.start_platform()
        pending = self.http_login('pending@example.test')
        self.assertEqual(pending['user']['id'], 'usr_pending')
        self.assertEqual(pending['roles'], ['member'])
        self.assertEqual(pending['default_workspace'], 'ws-initial')
        logged_in = self.login()
        self.assertEqual(logged_in['workspace']['id'], 'ws-initial')
        self.restart_platform()
        result = self.cli('auth', 'status')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['data']['default_workspace'], 'ws-initial')


if __name__ == '__main__':
    unittest.main()
