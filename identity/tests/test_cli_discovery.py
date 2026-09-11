"""Offline discovery through actual CLI invocations."""
import json
import os
import subprocess
import sys
import tempfile
import unittest


class DiscoveryAcceptance(unittest.TestCase):
    def run_cli(self, *args, production=False):
        with tempfile.TemporaryDirectory() as home:
            return subprocess.run([sys.executable, '-m', 'identity.cli' if production else 'identity.tests.cli', *args],
                env={**os.environ, 'HOME': home, 'XDG_CONFIG_HOME': home,
                     'XDG_STATE_HOME': home, 'SMALL_CLOUD_ENDPOINT': 'invalid',
                     'SMALL_CLOUD_TEST_ORIGIN': 'https://127.0.0.1:1'},
                text=True, capture_output=True)

    def test_bare_and_nested_help_are_offline_and_take_precedence(self):
        for args in ((), ('--help',), ('app', '--help'),
                     ('app', 'deploy', '--help'), ('app', 'secrets', 'set', '--help'),
                     ('--request-id', 'auth', 'app', 'status', '--help', '--request-id')):
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('--json', result.stdout)
                self.assertIn('small-cloud guide', result.stdout)
                self.assertIn('small-cloud catalog', result.stdout)
                if 'status' in args:
                    self.assertIn('usage: small-cloud app status', result.stdout)

    def test_service_is_fixed_without_endpoint_setup(self):
        result = self.run_cli('auth', 'status', '--json', production=True)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'AUTH_REQUIRED')
        for args in (('--endpoint', 'https://example.test'), ('--endpoint=https://example.test',)):
            result = self.run_cli(*args, 'auth', 'status', '--json')
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        result = self.run_cli('catalog', '--json')
        self.assertNotIn('--endpoint', result.stdout)

    def test_catalog_queries_and_guides_only_advertise_delivered_commands(self):
        result = self.run_cli('catalog', 'app', '--json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        envelope = json.loads(result.stdout)
        self.assertIsNone(envelope['request_id'])
        catalog = envelope['data']
        self.assertEqual(catalog['catalog_version'], 1)
        paths = {item['path'] for item in catalog['commands']}
        self.assertIn('app list', paths)
        self.assertIn('app check', paths)
        self.assertNotIn('app delete', paths)
        leaf = self.run_cli('catalog', 'app status', '--json')
        commands = json.loads(leaf.stdout)['data']['commands']
        self.assertEqual([item['path'] for item in commands], ['app status'])
        self.assertIn('administrator', commands[0]['permissions'])
        self.assertEqual(commands[0]['inputs'][0]['name'], 'app')
        self.assertEqual(commands[0]['inputs'][0]['type'], 'string')
        self.assertTrue(commands[0]['inputs'][0]['required'])
        guide = self.run_cli('guide', 'getting-started', '--json')
        self.assertEqual(guide.returncode, 0, guide.stdout)
        self.assertIn('small-cloud app list --json', json.loads(guide.stdout)['data']['content'])
        unknown = self.run_cli('catalog', 'app', 'invented', '--json')
        self.assertEqual(unknown.returncode, 2)
        self.assertEqual(json.loads(unknown.stdout)['error']['code'], 'INVALID_ARGUMENT')
        for old in ('directory', 'deploy', 'status', 'logs', 'secret', 'share', 'usage', 'admin'):
            result = self.run_cli(old, '--json')
            self.assertEqual(result.returncode, 2)

    def test_every_catalog_example_has_matching_help_and_accepted_syntax(self):
        import shlex
        result = self.run_cli('catalog', '--json')
        for definition in json.loads(result.stdout)['data']['commands']:
            with self.subTest(command=definition['path']):
                args = shlex.split(definition['examples'][0])[1:]
                help_result = self.run_cli(*args, '--help')
                self.assertEqual(help_result.returncode, 0, help_result.stderr)
                self.assertIn(definition['description'], help_result.stdout.replace('\n', ' ').replace('  ', ' '))
                self.assertIn(definition['examples'][0], help_result.stdout)
                # No usable endpoint or credential: online examples must parse but cannot mutate.
                invocation = self.run_cli(*args, '--no-input')
                if invocation.returncode:
                    message = json.loads(invocation.stdout)['error']['message']
                    self.assertNotIn('unrecognized arguments', message)
                    self.assertNotIn('invalid choice', message)
                    self.assertNotIn('the following arguments are required', message)
        listing = self.run_cli('guide', '--json')
        for item in json.loads(listing.stdout)['data']['guides']:
            guide = self.run_cli('guide', item['topic'])
            self.assertEqual(guide.returncode, 0, guide.stderr)
            self.assertFalse(guide.stdout.startswith('{'))
            if item['topic'] == 'publishing':
                self.assertIn('GET /_small-cloud/ready', guide.stdout)
                self.assertIn('200', guide.stdout)
            for line in guide.stdout.splitlines():
                if not line.startswith('small-cloud '):
                    continue
                args = shlex.split(line)[1:]
                invocation = self.run_cli(*args, '--json', '--no-input')
                if invocation.returncode:
                    message = json.loads(invocation.stdout)['error']['message']
                    self.assertNotIn('unrecognized arguments', message)
                    self.assertNotIn('invalid choice', message)
                    self.assertNotIn('the following arguments are required', message)

    def test_missing_inputs_are_prompt_free_and_json_errors_are_single_results(self):
        for args in (('app', 'status'), ('app', 'deploy', '.'),
                     ('workspace', 'member', 'add'), ('app', 'secrets', 'set')):
            result = self.run_cli(*args, '--json')
            self.assertEqual(result.returncode, 2)
            data = json.loads(result.stdout)
            self.assertFalse(data['ok'])
            self.assertIsNone(data['request_id'])
            self.assertIn('--help', data['error']['message'])
