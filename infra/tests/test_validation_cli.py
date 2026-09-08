"""Validation cleanup CLI must continue after individual resource failures."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import runpy
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error

from test_cloud_cli import Provider, LABELS
import cloud


class ValidationProvider(Provider):
    def __init__(self):
        super().__init__()
        self.blocked_server = None

    def __call__(self, request, timeout):
        if request.get_method() == 'DELETE' and request.full_url.endswith(f'/servers/{self.blocked_server}'):
            raise urllib.error.HTTPError(request.full_url, 423, 'protected', {},
                                        io.BytesIO(b'{"error":{"code":"protected"}}'))
        return super().__call__(request, timeout)


class ValidationCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / 'state'
        self.secrets = self.root / 'secrets'
        self.state.mkdir(mode=0o700)
        self.secrets.mkdir(mode=0o700)
        token = self.secrets / 'hetzner-token'
        token.write_text('fixture-provider-token')
        token.chmod(0o600)
        self.provider = ValidationProvider()

    def host(self, number, role, expired=True):
        self.provider.rows['servers'].append({
            'id': number, 'name': f'fixture-{role}',
            'labels': {**LABELS, 'role': role, 'validation': 'true',
                       'validation-expires': '1' if expired else str(int(time.time()) + 3600)},
            'public_net': {'ipv4': {'id': number + 1000}, 'ipv6': None}})
        self.provider.rows['primary_ips'].append({'id': number + 1000, 'assignee_id': number})

    def cli(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch.object(cloud, 'SECRET_DIR', self.secrets))
            stack.enter_context(patch.object(cloud, 'STATE_DIR', self.state))
            stack.enter_context(patch.object(cloud.urllib.request, 'urlopen', self.provider))
            stack.enter_context(patch.object(sys, 'argv', ['validation.py']))
            stack.enter_context(redirect_stdout(stdout))
            stack.enter_context(redirect_stderr(stderr))
            try:
                runpy.run_module('validation', run_name='__main__')
                code = 0
            except SystemExit as error:
                code = error.code
            except cloud.Failure:
                code = 1
        self.assertNotIn('fixture-provider-token', stdout.getvalue() + stderr.getvalue())
        return code, json.loads(stdout.getvalue()) if stdout.getvalue() else None

    def test_failed_builder_does_not_starve_expired_control_and_runtime(self):
        self.host(1, 'builder')
        self.host(2, 'control')
        self.host(3, 'runtime')
        self.provider.blocked_server = 1
        code, output = self.cli()
        self.assertEqual(code, 1)
        self.assertIsNotNone(output, 'CLI must summarize resource failures')
        self.assertEqual({row['id'] for row in self.provider.rows['servers']}, {1})
        self.assertEqual({row['id'] for row in self.provider.rows['primary_ips']}, {1001})
        self.assertEqual(set(output['removed']), {2, 3})
        self.assertEqual(output['failures'][0]['id'], 1)

    def test_bad_journal_does_not_starve_another_orphan_cleanup(self):
        (self.state / 'validation-delete-1.json').write_text('{broken')
        (self.state / 'validation-delete-2.json').write_text(json.dumps({'server': 2, 'addresses': [1002]}))
        self.provider.rows['primary_ips'].append({'id': 1002, 'assignee_id': None})
        code, output = self.cli()
        self.assertEqual(code, 1)
        self.assertEqual(self.provider.rows['primary_ips'], [])
        self.assertTrue(output['failures'])
        self.assertFalse((self.state / 'validation-delete-2.json').exists())

    def test_reassigned_address_preserved_while_other_journal_completes(self):
        for number, assignee in ((1, 99), (2, None)):
            (self.state / f'validation-delete-{number}.json').write_text(json.dumps(
                {'server': number, 'addresses': [number + 1000]}))
            self.provider.rows['primary_ips'].append({'id': number + 1000, 'assignee_id': assignee})
        code, output = self.cli()
        self.assertEqual(code, 1)
        self.assertEqual(self.provider.rows['primary_ips'], [{'id': 1001, 'assignee_id': 99}])
        self.assertTrue(output['failures'])

    def test_unexpired_validation_host_is_not_deleted(self):
        self.host(1, 'control', expired=False)
        code, output = self.cli()
        self.assertEqual(code, 0)
        self.assertEqual(output['removed'], [])
        self.assertEqual(len(self.provider.rows['servers']), 1)
        self.assertEqual(self.provider.mutations, [])


if __name__ == '__main__':
    unittest.main()
