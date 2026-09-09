"""Sharing acceptance through the real CLI and authenticated HTTP."""
import json
import unittest
import uuid

from identity.tests import test_deployment_http as deployment_fixture


class SharingAcceptance(unittest.TestCase):
    setUp = deployment_fixture.DeploymentAcceptance.setUp
    operator = deployment_fixture.DeploymentAcceptance.operator
    start_platform = deployment_fixture.DeploymentAcceptance.start_platform
    http = deployment_fixture.DeploymentAcceptance.http
    approve = deployment_fixture.DeploymentAcceptance.approve
    http_login = deployment_fixture.DeploymentAcceptance.http_login
    cli = deployment_fixture.DeploymentAcceptance.cli
    login = deployment_fixture.DeploymentAcceptance.login
    creator = deployment_fixture.DeploymentAcceptance.creator
    deploy = deployment_fixture.DeploymentAcceptance.deploy

    def test_creator_switches_both_directions_and_replays_do_not_restore_old_scope(self):
        self.creator()
        self.login()
        self.assertEqual(self.deploy()[0], 202)
        _, raw = self.http('/api/apps/example', token=self.token)
        self.assertEqual(json.loads(raw)['data']['sharing_scope'], 'creator-only')
        request_id = str(uuid.uuid4())
        for scope in ('workspace-wide', 'creator-only'):
            args = ['app', 'share', 'example', '--scope', scope]
            if scope == 'workspace-wide':
                args += ['--request-id', request_id]
            result = self.cli(*args)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)['data']['sharing_scope'], scope)
        result = self.cli('app', 'share', 'example', '--scope', 'workspace-wide', '--request-id', request_id)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        _, raw = self.http('/api/apps/example', token=self.token)
        self.assertEqual(json.loads(raw)['data']['sharing_scope'], 'creator-only')
        result = self.cli('app', 'share', 'example', '--scope', 'creator-only', '--request-id', request_id)
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)

    def admit(self, email, creator=False):
        status, raw = self.http('/api/admin/member/add', {'email': email}, token=self.token,
                               headers={'X-Request-ID': str(uuid.uuid4())})
        self.assertEqual(status, 200, raw)
        user = self.http_login(email)
        if creator:
            status, raw = self.http('/api/admin/creator/grant', {'user_id': user['user']['id']},
                                   token=self.token, headers={'X-Request-ID': str(uuid.uuid4())})
            self.assertEqual(status, 200, raw)
        return user

    def share(self, token, scope):
        return self.http('/api/apps/example/share', {'scope': scope}, token=token,
                         headers={'X-Request-ID': str(uuid.uuid4())})

    def directory(self, token):
        status, raw = self.http('/api/directory', token=token)
        self.assertEqual(status, 200, raw)
        return json.loads(raw)['data']['apps']

    def test_directory_and_all_app_routes_follow_current_scope_for_every_role(self):
        self.creator()
        owner = self.admit('owner@example.test', creator=True)
        member = self.admit('member@example.test')
        other = self.admit('other@example.test', creator=True)
        owner_token = owner['credential']
        status, result = self.deploy(description='Shared board', token=owner_token)
        self.assertEqual(status, 202, result)
        entry = {'name': 'example', 'description': 'Shared board',
                 'creator': {'id': owner['user']['id'], 'name': 'owner'}, 'url': result['data']['url']}
        self.assertEqual(self.directory(owner_token), [entry])
        audience = (member['credential'], other['credential'], self.token)
        host = result['data']['url'].removeprefix('https://')
        for scope in ('creator-only', 'workspace-wide', 'creator-only'):
            self.assertEqual(self.share(owner_token, scope)[0], 200)
            for token in audience:
                self.assertEqual(self.directory(token), [entry] if scope == 'workspace-wide' else [])
                self.assertEqual(self.share(token, 'workspace-wide')[0], 404)
                for path, body, headers in (('/', None, {}), ('/assets/app.js', None, {}),
                        ('/data', {'value': 'changed'}, {}), ('/', None, {'Upgrade': 'websocket'})):
                    status, raw = self.http(path, body, token=token, headers={'Host': host, **headers})
                    # Authorization precedes both protocol rejection and startup admission.
                    expected = (400 if headers else 503) if scope == 'workspace-wide' else 404
                    self.assertEqual(status, expected, raw)
            self.assertEqual(self.directory(owner_token), [entry])
        self.assertEqual(self.http('/api/directory')[0], 401)
        for path, body in (('/', None), ('/assets/app.js', None), ('/data', {'value': 'no'})):
            self.assertEqual(self.http(path, body, headers={'Host': host})[0], 401)
        self.login()
        result = self.cli('app', 'list')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['data']['apps'], [])

    def test_invalid_sharing_inputs_and_unadmitted_sign_in(self):
        self.creator()
        self.deploy()
        for body in ({}, {'scope': 'public'}, {'scope': ['workspace-wide']},
                     {'scope': 'workspace-wide', 'owner': 'someone-else'}):
            status, raw = self.http('/api/apps/example/share', body, token=self.token,
                                   headers={'X-Request-ID': str(uuid.uuid4())})
            self.assertEqual(status, 400, raw)
        _, raw = self.http('/api/apps/example', token=self.token)
        self.assertEqual(json.loads(raw)['data']['sharing_scope'], 'creator-only')
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.http_login('unadmitted@example.test')
        self.assertEqual(denied.exception.code, 403)

    def test_cli_human_and_json_inspection_preserve_access_boundaries(self):
        import subprocess
        import sys
        self.creator()
        self.login()
        status, deployed = self.deploy(description='Team board\x1b[31m')
        self.assertEqual(status, 202)
        result = subprocess.run([sys.executable, '-m', 'identity.cli', 'app', 'list'],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Team board', result.stdout)
        self.assertIn(deployed['data']['url'], result.stdout)
        self.assertNotIn('\x1b', result.stdout)
        self.assertFalse(result.stdout.startswith('{'))
        state = subprocess.run([sys.executable, '-m', 'identity.cli', 'app', 'status', 'example'],
                               env=self.env, capture_output=True, text=True)
        self.assertEqual(state.returncode, 0, state.stderr)
        self.assertIn('Availability:', state.stdout)
        self.assertIn('Operation:', state.stdout)
        data = json.loads(self.cli('app', 'status', 'example').stdout)
        self.assertEqual(data['schema_version'], 1)
        self.assertIsNone(data['request_id'])
        self.assertEqual(data['data']['app'], 'example')
        self.admit('member@example.test')
        self.login()
        empty = subprocess.run([sys.executable, '-m', 'identity.cli', 'app', 'list'],
                               env=self.env, capture_output=True, text=True)
        self.assertIn('No accessible apps', empty.stdout)
        denied = self.cli('app', 'status', 'example')
        self.assertEqual(denied.returncode, 4)
        self.assertEqual(json.loads(denied.stdout)['error']['code'], 'NOT_FOUND')
        human = subprocess.run([sys.executable, '-m', 'identity.cli', 'app', 'status', 'example'],
                              env=self.env, capture_output=True, text=True)
        self.assertEqual(human.returncode, 4)
        self.assertEqual(human.stdout, '')
        self.assertIn('small-cloud app list', human.stderr)
        self.assertNotIn('Team board', human.stderr)
