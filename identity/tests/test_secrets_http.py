"""Creator secret configuration through authenticated CLI and HTTP."""
import json
import subprocess
import sys
import unittest
import uuid

from identity.tests import test_lifecycle_http as lifecycle_fixture


class SecretsAcceptance(unittest.TestCase):
    for _name in ('setUp', 'operator', 'start_platform', 'restart_platform', 'http', 'approve', 'http_login',
                  'cli', 'login', 'creator', 'deploy', 'usage', 'prepare', 'publish', 'status', 'request', 'stop_all'):
        locals()[_name] = getattr(lifecycle_fixture.LifecycleAcceptance, _name)

    def change(self, action, value=None, name='SERVICE_TOKEN', request_id=None, **extra):
        body = {'name': name, **extra}
        if value is not None:
            body['value'] = value
        status, raw = self.http('/api/apps/secrets/secrets/' + action, body, token=self.token,
                                headers={'X-Request-ID': request_id or str(uuid.uuid4())})
        return status, json.loads(raw)

    def test_saved_configuration_has_name_only_reads_and_reconciles_retries(self):
        self.prepare()
        self.publish('secrets')
        request_id = str(uuid.uuid4())
        status, result = self.change('set', 'first-private-value\n', request_id=request_id)
        self.assertEqual(status, 202, result)
        self.assertNotIn('first-private-value', json.dumps(result))
        self.assertEqual(self.change('set', 'first-private-value\n', request_id=request_id)[1], result)
        self.assertEqual(self.change('set', 'different', request_id=request_id)[1]['error']['code'], 'REQUEST_CONFLICT')
        status, raw = self.http('/api/apps/secrets/secrets', token=self.token)
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)['data'], {'names': ['SERVICE_TOKEN']})
        self.assertEqual(self.http('/api/apps/secrets/secrets/SERVICE_TOKEN', token=self.token)[0], 404)

    def test_replacement_deletion_and_failed_restart_keep_saved_configuration(self):
        self.prepare()
        app = self.publish('secrets')
        for action, value, names in [('set', 'old-token', ['SERVICE_TOKEN']),
                                     ('set', 'new-token\n', ['SERVICE_TOKEN']), ('delete', None, [])]:
            status, result = self.change(action, value)
            self.assertEqual(status, 202, result)
            self.assertEqual(self.request(app)[0], 503)
            self.lifecycle.once()
            operation = json.loads(self.http('/api/operations/' + result['data']['operation_id'], token=self.token)[1])['data']
            self.assertEqual(operation['kind'], 'secret-change')
            self.assertEqual(operation['state'], 'succeeded', operation)
            self.assertEqual(self.request(app)[0], 200)
            self.assertEqual(json.loads(self.http('/api/apps/secrets/secrets', token=self.token)[1])['data']['names'], names)
        self.assertFalse(self.change('delete')[1]['data']['changed'])
        self.infrastructure.fail_wake = True
        self.change('set', 'saved-despite-failure')
        self.lifecycle.once()
        operation = self.status('secrets')['latest_operation']
        self.assertEqual(operation['state'], 'failed')
        self.assertTrue(operation['error']['details']['configuration_saved'])
        self.assertEqual(self.usage()['active_apps']['used'], 0)

    def test_cli_input_and_sharing_authority_notice(self):
        self.prepare()
        self.publish('secrets')
        self.login()
        result = subprocess.run([sys.executable, '-m', 'identity.cli', '--json', 'app', 'secrets', 'set',
                                 'secrets', 'SERVICE_TOKEN', '--stdin'], env=self.env, capture_output=True,
                                text=True, input='cli-value\n', timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('cli-value', result.stdout + result.stderr)
        self.lifecycle.once()
        result = self.cli('app', 'secrets', 'list', 'secrets')
        self.assertEqual(json.loads(result.stdout)['data'], {'names': ['SERVICE_TOKEN']})
        result = self.cli('app', 'share', 'secrets', '--scope', 'workspace-wide')
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('credential-backed', result.stdout)
        result = self.cli('app', 'share', 'secrets', '--scope', 'workspace-wide', '--acknowledge-secret-authority')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(json.loads(result.stdout)['data']['secret_authority_acknowledged'])
        self.assertEqual(self.change('set', 'other')[1]['error']['code'], 'ACKNOWLEDGEMENT_REQUIRED')

    def test_boundaries_validation_capacity_and_retained_redaction(self):
        from identity.tests import test_diagnostics_http as diagnostics_fixture
        from identity.tests import test_limits_http as limits_fixture
        self.prepare()
        app = self.publish('secrets')
        other = limits_fixture.LimitsAcceptance.admit_creator(self, 'other@example.test')
        for route, body in [('/api/apps/secrets/secrets', None),
                            ('/api/apps/secrets/secrets/set', {'name': 'TOKEN', 'value': 'unauthorized'}),
                            ('/api/apps/secrets/secrets/delete', {'name': 'TOKEN'})]:
            self.assertEqual(self.http(route, body, token=other,
                headers={'X-Request-ID': str(uuid.uuid4())})[0], 404)
        for name, value in [('PORT', 'v'), ('SMALL_CLOUD_AUTH', 'v'), ('lower', 'v'),
                            ('TOKEN', ''), ('TOKEN', '\0'), ('TOKEN', 'x' * 16385)]:
            self.assertEqual(self.change('set', value, name=name)[0], 400)
        self.assertEqual(self.change('set', '\n' * 16384)[0], 202)
        self.lifecycle.once()
        self.change('set', 'original-sensitive-token')
        self.lifecycle.once()
        self.change('set', 'replacement-sensitive-token')
        self.lifecycle.once()
        self.change('delete')
        self.lifecycle.once()
        diagnostics_fixture.DiagnosticsAcceptance.diagnostic(self, app['active_deployment_id'], 'runtime',
            b'original-sensitive-token replacement-sensitive-token\n', now=self.now + 604799)
        status, raw = self.http('/api/apps/secrets/logs?source=runtime', token=self.token)
        self.assertEqual(status, 200, raw)
        self.assertNotIn('original-sensitive-token', raw)
        self.assertNotIn('replacement-sensitive-token', raw)
        self.assertIn('[REDACTED]', raw)
        self.stop_all()
        for i in range(5):
            self.publish('capacity-' + str(i))
        refused = self.change('set', 'must-not-save', name='REFUSED')
        self.assertEqual(refused[1]['error']['code'], 'ACTIVE_CAPACITY')
        self.assertEqual(json.loads(self.http('/api/apps/secrets/secrets', token=self.token)[1])['data']['names'], [])

    def test_configuration_can_repair_a_failed_first_deployment(self):
        self.prepare()
        self.infrastructure.fail = True
        self.publish('secrets')
        self.assertIsNone(self.status('secrets')['active_deployment_id'])
        status, result = self.change('set', 'required-startup-token')
        self.assertEqual(status, 202, result)
        self.lifecycle.once()
        operation = self.status('secrets')['latest_operation']
        self.assertEqual(operation['state'], 'failed')
        self.assertTrue(operation['error']['details']['configuration_saved'])
        self.infrastructure.fail = False
        self.publish('secrets')
        self.assertEqual(self.status('secrets')['availability'], 'running')
        self.assertEqual(json.loads(self.http('/api/apps/secrets/secrets', token=self.token)[1])['data']['names'], ['SERVICE_TOKEN'])

    def test_secret_restart_does_not_take_the_creators_build_lock(self):
        self.prepare()
        self.publish('secrets')
        self.assertEqual(self.change('set', 'pending-runtime-token')[0], 202)
        status, result = self.deploy(name='independent-build')
        self.assertEqual(status, 202, result)

    def test_interrupted_restart_retains_configuration_until_recovery(self):
        self.prepare()
        self.publish('secrets')
        self.change('set', 'retained-through-process-loss')
        self.infrastructure.lose_wake = True
        with self.assertRaises(KeyboardInterrupt):
            self.lifecycle.once()
        self.assertEqual(self.usage()['active_apps']['used'], 1)
        self.restart_platform()
        self.lifecycle.recover()
        self.infrastructure.lose_wake = False
        self.lifecycle.once()
        status = self.status('secrets')
        self.assertEqual(status['availability'], 'running')
        self.assertEqual(status['latest_operation']['state'], 'succeeded')
        self.assertEqual(json.loads(self.http('/api/apps/secrets/secrets', token=self.token)[1])['data']['names'], ['SERVICE_TOKEN'])
