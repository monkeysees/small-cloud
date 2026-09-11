"""Multiple workspaces through the executable, verified sign-in and HTTP service."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import unittest
import uuid

from identity.tests import test_deployment_http as fixture
from identity.tests import test_identity_cli as identity_fixture


class WorkspacesAcceptance(unittest.TestCase):
    setUp = fixture.DeploymentAcceptance.setUp
    operator = fixture.DeploymentAcceptance.operator
    start_platform = fixture.DeploymentAcceptance.start_platform
    restart_platform = identity_fixture.IdentityAcceptance.restart_platform
    http = fixture.DeploymentAcceptance.http
    http_login = fixture.DeploymentAcceptance.http_login
    approve = fixture.DeploymentAcceptance.approve
    cli = fixture.DeploymentAcceptance.cli
    login = fixture.DeploymentAcceptance.login
    creator = fixture.DeploymentAcceptance.creator

    def result(self, *args):
        result = self.cli(*args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)['data']

    def test_platform_creation_retries_and_pending_owner_sign_in(self):
        self.creator()
        self.login()
        request_id = str(uuid.uuid4())
        args = ('workspace', 'create', 'Second workspace', '--owner', 'owner@example.test',
                '--request-id', request_id)
        created = self.result(*args)
        self.assertEqual(self.result(*args), created)
        self.assertNotEqual(created['workspace']['id'], 'ws-initial')
        owner = self.http_login('owner@example.test')
        self.assertEqual(owner['workspace'], created['workspace'])
        self.assertEqual(owner['default_workspace'], created['workspace']['id'])
        self.assertEqual(owner['roles'], ['member', 'creator', 'administrator'])
        self.assertFalse(owner['platform_administrator'])
        status, raw = self.http('/api/workspaces/create', {'name': 'Third', 'owner_email': 'third@example.test'},
                               token=owner['credential'], headers={'X-Request-ID': str(uuid.uuid4())})
        self.assertEqual(status, 403, raw)
        self.restart_platform()
        self.assertEqual(self.result(*args), created)
        self.assertEqual(len(self.result('workspace', 'list')['workspaces']), 1)
        changed = self.cli('workspace', 'create', 'Changed', '--owner', 'owner@example.test',
                           '--request-id', request_id)
        self.assertEqual(json.loads(changed.stdout)['error']['code'], 'REQUEST_CONFLICT')

    def test_selected_workspace_roles_are_independent_and_retries_bind_the_target(self):
        self.creator()
        initial = self.login()
        second = self.result('workspace', 'create', 'Second', '--owner', 'admin@example.test')['workspace']['id']
        self.assertEqual(len(self.result('workspace', 'list')['workspaces']), 2)
        self.assertEqual(self.result('auth', 'status')['default_workspace'], 'ws-initial')
        self.assertEqual(self.result('auth', 'status', '--workspace', second)['roles'], ['member', 'creator', 'administrator'])
        self.result('workspace', 'select', second)
        self.assertEqual(self.result('auth', 'status')['workspace']['id'], second)
        self.assertIn('creator', self.result('auth', 'status', '--workspace', 'ws-initial')['roles'])
        request_id = str(uuid.uuid4())
        args = ('workspace', 'member', 'add', 'member@example.test', '--request-id', request_id)
        member = self.result(*args, '--workspace', 'ws-initial')
        conflict = self.cli(*args, '--workspace', second)
        self.assertEqual(json.loads(conflict.stdout)['error']['code'], 'REQUEST_CONFLICT')
        admitted = self.result('workspace', 'member', 'add', 'member@example.test', '--workspace', second)
        self.assertEqual(admitted['user_id'], member['user_id'])
        login = self.http_login('member@example.test')
        self.assertEqual(login['default_workspace'], 'ws-initial')
        self.result('workspace', 'creator', 'grant', login['user']['id'], '--workspace', second)
        self.assertEqual(self.http('/api/auth/status', token=login['credential'],
                                  headers={'X-Workspace': second})[0], 200)
        self.result('workspace', 'creator', 'grant', initial['user']['id'], '--workspace', second)
        source = self.home / 'source'
        source.mkdir()
        (source / 'Dockerfile').write_text('FROM scratch\n')
        request_id = str(uuid.uuid4())
        deploy = ('app', 'deploy', str(source), '--name', 'example', '--description', '', '--request-id', request_id)
        accepted = self.result(*deploy, '--workspace', 'ws-initial')
        conflict = self.cli(*deploy, '--workspace', second)
        self.assertEqual(json.loads(conflict.stdout)['error']['code'], 'REQUEST_CONFLICT')
        self.assertEqual(self.result('app', 'list', '--workspace', second)['apps'], [])
        status, raw = self.http('/api/operations/' + accepted['operation_id'] + '?request_id=' + str(uuid.uuid4()),
                               token=self.token, headers={'X-Workspace': 'ws-initial'})
        self.assertEqual(status, 400, raw)
        self.assertEqual(self.http('/api/apps/example?app_id=foreign', token=self.token,
                                  headers={'X-Workspace': 'ws-initial'})[0], 400)

    def test_owner_can_publish_using_first_default_without_grant_or_override(self):
        self.operator('bootstrap', 'admin@example.test')
        self.start_platform()
        self.login()
        created = self.result('workspace', 'create', 'Owner team', '--owner', 'owner@example.test')
        self.http_login('owner@example.test')
        self.login()
        owner = self.result('auth', 'status')
        self.assertEqual(owner['default_workspace'], created['workspace']['id'])
        source = self.home / 'source'
        source.mkdir()
        (source / 'Dockerfile').write_text('FROM scratch\n')
        self.result('app', 'deploy', str(source), '--name', 'owner-app', '--description', '')
        self.assertEqual([app['name'] for app in self.result('app', 'list')['apps']], ['owner-app'])

    def test_owner_grants_enforce_capacity_atomically_and_allow_receipt_replay(self):
        self.operator('bootstrap', 'admin@example.test')
        self.start_platform()
        self.login()
        args = ('workspace', 'create', 'Last team', '--owner', 'last@example.test',
                '--request-id', str(uuid.uuid4()))
        for number in range(3):
            self.result('workspace', 'create', str(number), '--owner', f'owner{number}@example.test')
        created = self.result(*args)
        self.assertEqual(self.result(*args), created)
        failed = self.cli('workspace', 'create', 'Overflow', '--owner', 'overflow@example.test')
        self.assertEqual(json.loads(failed.stdout)['error']['code'], 'CREATOR_CAPACITY')
        with sqlite3.connect(self.home / 'server' / 'identity.sqlite3') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM workspaces').fetchone()[0], 5)
            self.assertIsNone(db.execute("SELECT id FROM users WHERE admission_email='overflow@example.test'").fetchone())

    def test_lost_default_and_ambiguous_names_require_explicit_selection(self):
        self.creator()
        self.login()
        second = self.result('workspace', 'create', 'Duplicate', '--owner', 'admin@example.test')['workspace']['id']
        third = self.result('workspace', 'create', 'Duplicate', '--owner', 'admin@example.test')['workspace']['id']
        ambiguous = self.cli('auth', 'status', '--workspace', 'Duplicate')
        self.assertEqual(json.loads(ambiguous.stdout)['error']['code'], 'INVALID_ARGUMENT')
        inaccessible = self.result('workspace', 'create', 'Private', '--owner', 'other@example.test')['workspace']['id']
        self.result('workspace', 'create', inaccessible, '--owner', 'admin@example.test')
        self.assertEqual(self.cli('workspace', 'select', inaccessible).returncode, 4)
        self.assertEqual(self.cli('app', 'list', '--workspace', inaccessible).returncode, 4)
        for workspace in ('ws-initial', second, third):
            self.result('workspace', 'member', 'add', 'member@example.test', '--workspace', workspace)
        member = self.http_login('member@example.test')
        self.login()
        with sqlite3.connect(self.home / 'server' / 'identity.sqlite3') as db:
            db.execute("UPDATE memberships SET member=0 WHERE workspace_id='ws-initial' AND user_id=?", (member['user']['id'],))
        self.assertEqual(self.cli('auth', 'status').returncode, 4)
        self.assertEqual(self.cli('app', 'list').returncode, 4)
        self.assertEqual(len(self.result('workspace', 'list')['workspaces']), 2)
        self.restart_platform()
        self.assertIsNone(self.login()['workspace'])
        self.assertEqual(self.result('auth', 'status', '--workspace', second)['workspace']['id'], second)
        self.result('workspace', 'select', second)
        self.assertEqual(self.result('auth', 'status')['workspace']['id'], second)

    def test_additional_workspaces_do_not_multiply_installation_build_allowance(self):
        self.creator()
        initial = self.login()
        second = self.result('workspace', 'create', 'Second', '--owner', 'admin@example.test')['workspace']['id']
        self.result('workspace', 'creator', 'grant', initial['user']['id'], '--workspace', second)
        from identity.allowance import period
        import time
        start, end = period(time.time())
        with sqlite3.connect(self.home / 'server' / 'identity.sqlite3') as db:
            db.executemany('INSERT INTO build_allowance VALUES(?,?,?,?,?)',
                          [(str(i), 'ws-initial', start, end, 600) for i in range(100)])
        source = self.home / 'source'
        source.mkdir()
        (source / 'Dockerfile').write_text('FROM scratch\n')
        result = self.cli('app', 'deploy', str(source), '--name', 'example', '--description', '', '--workspace', second)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'ALLOWANCE_EXHAUSTED')
        self.assertEqual(self.result('app', 'list', '--workspace', second)['apps'], [])

    def test_concurrent_creation_and_browser_onboarding_preserve_exact_admission(self):
        self.creator()
        self.login()
        request_id = str(uuid.uuid4())
        def create(_):
            return self.http('/api/workspaces/create', {'name': '東京 team', 'owner_email': 'admin@example.test'},
                             token=self.token, headers={'X-Request-ID': request_id})
        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(create, range(2)))
        self.assertEqual([status for status, _ in responses], [200, 200])
        self.assertEqual(responses[0], responses[1])
        second = json.loads(responses[0][1])['data']['workspace']['id']
        self.assertEqual(len(self.result('workspace', 'list')['workspaces']), 2)
        self.assertEqual(self.result('auth', 'status', '--workspace', '東京 team')['workspace']['id'], second)
        self.result('workspace', 'create', second, '--owner', 'admin@example.test')
        self.assertEqual(self.result('auth', 'status', '--workspace', second)['workspace']['id'], second)
        import http.cookiejar
        import urllib.request
        import urllib.parse
        browser = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.client_tls),
                                              urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        with sqlite3.connect(self.home / 'server' / 'identity.sqlite3') as db:
            db.executemany('INSERT INTO oauth VALUES(?,?,?,?,?,?)',
                          [(str(i), 'expired', 'nonce', 'pkce', '/directory', 0) for i in range(200)])
        status, page = self.http('/directory?workspace=' + second, browser=browser)
        self.assertEqual(status, 200, page)
        self.assertIn('<h1>東京 team</h1>', page)
        self.identity = {'sub': 'uninvited', 'email': 'uninvited@example.test', 'email_verified': True, 'name': 'Uninvited'}
        stranger = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.client_tls),
                                               urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.assertEqual(self.http('/directory', browser=stranger)[0], 403)


if __name__ == '__main__':
    unittest.main()
