"""CLI contracts against an in-memory HTTP transport; never contact providers."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import builders
import cloud


LABELS = {'managed-by': 'small-cloud', 'issue': '17'}
PUBLIC_KEY = 'ssh-ed25519 fixture-public-key'


class Provider:
    def __init__(self):
        self.rows = {name: [] for name in ('servers', 'networks', 'firewalls', 'ssh_keys', 'primary_ips', 'volumes')}
        self.rows['ssh_keys'] = [{'id': 1, 'name': 'small-cloud-operator',
                                 'labels': dict(LABELS), 'public_key': PUBLIC_KEY}]
        self.available = True
        self.fail_firewall = False
        self.reject_creates = []
        self.lose_delete_response = False
        self.calls = []
        self.next_id = 100

    def response(self, value):
        return io.BytesIO(json.dumps(copy.deepcopy(value)).encode())

    def __call__(self, request, timeout):
        parsed = urllib.parse.urlsplit(request.full_url)
        if parsed.hostname != 'api.hetzner.cloud':
            raise AssertionError('Unexpected provider host; real networking is prohibited')
        method = request.get_method()
        path = parsed.path.removeprefix('/v1/')
        body = json.loads(request.data) if request.data else None
        self.calls.append((method, path, copy.deepcopy(body)))
        pieces = path.split('/')
        resource = pieces[0]
        if method == 'GET' and resource == 'pricing':
            return self.response({'pricing': {'currency': 'EUR', 'vat_rate': '19.0',
                                             'primary_ips': [], 'volume': {}}})
        if method == 'GET' and resource == 'server_types':
            return self.response({'server_types': [
                {'id': number, 'name': name, 'cores': 2, 'memory': 4, 'disk': 40,
                 'locations': [{'name': place, 'available': self.available}
                               for place in ('nbg1', 'fsn1', 'hel1', 'ash')],
                 'prices': [{'location': place, 'price_hourly': {'net': '0.01'},
                             'price_monthly': {'net': '6.00'}}
                            for place in ('nbg1', 'fsn1', 'hel1', 'ash')]}
                for number, name in enumerate(('cx33', 'cx43', 'cx23', 'cpx22', 'cpx32', 'cpx42'))]})
        if method == 'GET' and resource == 'actions':
            return self.response({'action': {'id': int(pieces[1]), 'status': 'error'}})
        if method == 'GET':
            if len(pieces) == 2:
                row = next(row for row in self.rows[resource] if row['id'] == int(pieces[1]))
                return self.response({{'servers': 'server'}[resource]: row})
            rows = self.rows[resource]
            selector = urllib.parse.parse_qs(parsed.query).get('label_selector', [''])[0]
            for item in filter(None, selector.split(',')):
                key, value = item.split('=', 1)
                rows = [row for row in rows if row.get('labels', {}).get(key) == value]
            return self.response({resource: rows, 'meta': {'pagination': {'next_page': None}}})
        if method == 'POST' and len(pieces) == 1:
            if resource == 'servers' and self.reject_creates:
                rejection = self.reject_creates.pop(0)
                if rejection == 'unknown':
                    raise OSError('fixture-private-provider-detail')
                raise urllib.error.HTTPError(request.full_url, 412, 'rejected', {},
                    io.BytesIO(json.dumps({'error': {'code': rejection,
                                                  'message': 'fixture-private-provider-detail'}}).encode()))
            self.next_id += 1
            row = {'id': self.next_id, **body}
            if resource == 'servers':
                row = {'id': self.next_id, 'name': body['name'], 'labels': body['labels'],
                       'server_type': {'name': body['server_type']},
                       'location': {'name': body['location']}, 'private_net': [],
                       'created': datetime.now(timezone.utc).isoformat(),
                       'public_net': {'ipv4': {'id': self.next_id + 1000, 'ip': '198.51.100.10'},
                                      'ipv6': None, 'firewalls': [
                                          {'id': item['firewall'], 'status': 'applied'} for item in body['firewalls']]}}
                self.rows['primary_ips'].append({'id': self.next_id + 1000, 'assignee_id': self.next_id})
            self.rows[resource].append(row)
            singular = {'servers': 'server', 'networks': 'network', 'firewalls': 'firewall', 'ssh_keys': 'ssh_key'}[resource]
            return self.response({singular: row, 'action': {'id': 700, 'status': 'success'}})
        if method == 'POST' and 'actions' in pieces:
            if resource == 'firewalls':
                if pieces[-1] == 'set_rules':
                    next(row for row in self.rows[resource] if row['id'] == int(pieces[1]))['rules'] = body['rules']
                elif pieces[-1] == 'apply_to_resources':
                    firewall_id = int(pieces[1])
                    for target in body['apply_to']:
                        server = next(row for row in self.rows['servers'] if row['id'] == target['server']['id'])
                        if any(item['id'] == firewall_id for item in server['public_net']['firewalls']):
                            raise urllib.error.HTTPError(request.full_url, 422, 'already applied', {},
                                io.BytesIO(b'{"error":{"code":"invalid_input"}}'))
                        server['public_net']['firewalls'].append({'id': firewall_id, 'status': 'applied'})
                return self.response({'actions': [{'id': 701, 'status': 'running' if self.fail_firewall else 'success'}]})
            if resource == 'servers' and pieces[-1] == 'attach_to_network':
                next(row for row in self.rows['servers'] if row['id'] == int(pieces[1]))['private_net'] = [body]
                return self.response({'action': {'id': 702, 'status': 'success'}})
        if method == 'DELETE':
            target = int(pieces[1])
            self.rows[resource] = [row for row in self.rows[resource] if row['id'] != target]
            if resource == 'servers':
                for address in self.rows['primary_ips']:
                    if address['assignee_id'] == target:
                        address['assignee_id'] = None
                if self.lose_delete_response:
                    self.lose_delete_response = False
                    raise OSError('fixture-private-provider-detail')
            return self.response({'action': {'id': 703, 'status': 'success'}})
        raise AssertionError(f'Unexpected fixture request: {method} {path}')

    @property
    def mutations(self):
        return [call for call in self.calls if call[0] != 'GET']


class CloudCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / 'state'
        self.secrets = self.root / 'secrets'
        self.state.mkdir(mode=0o700)
        self.secrets.mkdir(mode=0o700)
        for path, value in ((self.secrets / 'hetzner-token', 'fixture-provider-token'),
                            (self.state / 'operator_ed25519', 'fixture-private-key'),
                            (self.state / 'operator_ed25519.pub', PUBLIC_KEY)):
            path.write_text(value)
            path.chmod(0o600)
        self.provider = Provider()
        self.controller = {}

    def cli(self, module, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        original_is_file = Path.is_file
        original_read_text = Path.read_text
        with ExitStack() as stack:
            stack.enter_context(patch.object(cloud, 'SECRET_DIR', self.secrets))
            stack.enter_context(patch.object(cloud, 'STATE_DIR', self.state))
            stack.enter_context(patch.object(cloud.urllib.request, 'urlopen', self.provider))
            stack.enter_context(patch.object(cloud.time, 'sleep', lambda _: None))
            stack.enter_context(patch.object(sys, 'argv', [module.__name__, *arguments]))
            # Simulate only the installed-controller OS boundary; CLI logic remains real.
            if module is builders:
                stack.enter_context(patch.object(builders.os, 'geteuid', return_value=0))
                stack.enter_context(patch.object(Path, 'is_file', lambda path:
                    True if str(path) == '/etc/small-cloud/controller' else original_is_file(path)))
                stack.enter_context(patch.object(Path, 'read_text', lambda path, *args, **kwargs:
                    json.dumps(self.controller) if str(path) == '/etc/small-cloud/controller.json'
                    else original_read_text(path, *args, **kwargs)))
            stack.enter_context(redirect_stdout(stdout))
            stack.enter_context(redirect_stderr(stderr))
            code = module.main()
        output, errors = stdout.getvalue(), stderr.getvalue()
        for secret in ('fixture-provider-token', 'fixture-private-key', 'fixture-private-provider-detail'):
            self.assertNotIn(secret, output + errors)
        return code, json.loads(output) if output else None, errors

    def apply(self):
        return self.cli(cloud, 'apply', '--admin-cidr', '203.0.113.1/32')

    def create(self, job='fixture'):
        return self.cli(builders, 'create', '--admin-cidr', '203.0.113.1/32', '--job', job)

    def test_unavailable_foundation_does_not_mutate(self):
        self.provider.available = False
        code, output, errors = self.apply()
        self.assertEqual(code, 1)
        self.assertIsNone(output)
        self.assertIn('CAPACITY_UNAVAILABLE', errors)
        self.assertEqual(self.provider.mutations, [])

    def test_quote_includes_only_approved_eu_locations(self):
        code, output, _ = self.cli(cloud, 'quote')
        self.assertEqual(code, 0)
        self.assertEqual({row['location'] for row in output['servers']}, {'nbg1', 'fsn1', 'hel1'})
        self.assertEqual(self.provider.mutations, [])

    def test_validation_requires_cleanup_expiry_before_mutation(self):
        code, _, errors = self.cli(cloud, 'apply', '--validation', '--admin-cidr', '203.0.113.1/32')
        self.assertEqual(code, 1)
        self.assertIn('cleanup timer', errors)
        self.assertEqual(self.provider.mutations, [])

    def test_validation_uses_temporary_cpx_pair_and_bounded_expiry(self):
        expiry = str(int(time.time()) + 3600)
        (self.state / 'validation-expiry').write_text(expiry)
        code, output, _ = self.cli(cloud, 'apply', '--validation', '--admin-cidr', '203.0.113.1/32')
        self.assertEqual(code, 0)
        self.assertEqual({row['type'] for row in output['servers'].values()}, {'cpx32', 'cpx42'})
        self.assertEqual(output['validation-expires'], expiry)
        self.assertTrue(all(server['labels']['validation'] == 'true' for server in self.provider.rows['servers']))

    def test_apply_again_keeps_server_identity_and_data_resources(self):
        code, first, _ = self.apply()
        self.assertEqual(code, 0)
        self.provider.calls.clear()
        code, second, _ = self.apply()
        self.assertEqual(code, 0)
        self.assertEqual(first, second)
        self.assertFalse(any(method == 'DELETE' or (method == 'POST' and '/' not in path)
                             for method, path, _ in self.provider.mutations))
        self.assertFalse(any(path.endswith('/apply_to_resources') for _, path, _ in self.provider.calls))

    def test_permanent_cpx_has_no_validation_expiry_and_reapplies(self):
        args = ('apply', '--admin-cidr', '203.0.113.1/32', '--cpx')
        code, first, _ = self.cli(cloud, *args)
        self.assertEqual(code, 0)
        self.assertEqual({row['type'] for row in first['servers'].values()}, {'cpx32', 'cpx42'})
        self.assertTrue(all('validation' not in row['labels'] for row in self.provider.rows['servers']))
        self.assertEqual(self.cli(cloud, *args)[1], first)
        self.assertEqual(len(self.provider.rows['servers']), 2)

    def test_permanent_cpx_cannot_be_temporary_validation(self):
        code, _, _ = self.cli(cloud, 'apply', '--admin-cidr', '203.0.113.1/32', '--cpx', '--validation')
        self.assertEqual(code, 1)
        self.assertEqual(self.provider.mutations, [])

    def test_unowned_network_is_not_adopted(self):
        self.provider.rows['networks'].append({'id': 8, 'name': 'small-cloud-private', 'labels': {}})
        code, _, errors = self.apply()
        self.assertEqual(code, 1)
        self.assertIn('unowned', errors)
        self.assertEqual(self.provider.mutations, [])

    def test_role_or_extra_firewall_drift_fails_reapplication(self):
        for drift in ('role', 'firewall'):
            with self.subTest(drift=drift):
                self.provider = Provider()
                self.assertEqual(self.apply()[0], 0)
                server = self.provider.rows['servers'][0]
                if drift == 'role':
                    server['labels']['role'] = 'builder'
                else:
                    server['public_net']['firewalls'].append({'id': 999, 'status': 'applied'})
                self.assertEqual(self.apply()[0], 1)
                self.assertEqual(len(self.provider.rows['servers']), 2)

    def test_failed_plural_firewall_action_stops_before_server_creation(self):
        self.provider.fail_firewall = True
        code, _, errors = self.apply()
        self.assertEqual(code, 1)
        self.assertIn('action 701 failed', errors)
        self.assertEqual(self.provider.rows['servers'], [])

    def test_builder_known_capacity_fallback_reaches_helsinki(self):
        self.provider.reject_creates = ['resource_unavailable', 'resource_unavailable']
        code, output, _ = self.create()
        self.assertEqual(code, 0)
        self.assertEqual((output['type'], output['location']), ('cx23', 'hel1'))
        attempts = [body['location'] for method, path, body in self.provider.calls
                    if method == 'POST' and path == 'servers']
        self.assertEqual(attempts, ['nbg1', 'fsn1', 'hel1'])

    def test_unknown_builder_create_outcome_never_retries(self):
        self.provider.reject_creates = ['unknown']
        code, _, errors = self.create()
        self.assertEqual(code, 1)
        self.assertIn('outcome unknown', errors)
        self.assertEqual(sum(method == 'POST' and path == 'servers'
                             for method, path, _ in self.provider.calls), 1)

    def test_builder_falls_back_to_cpx_after_all_eu_cx_rejections(self):
        self.provider.reject_creates = ['resource_unavailable'] * 3
        code, output, _ = self.create()
        self.assertEqual(code, 0)
        self.assertEqual((output['type'], output['location']), ('cpx22', 'nbg1'))

    def test_unavailable_builder_does_not_mutate(self):
        self.provider.available = False
        code, _, errors = self.create()
        self.assertEqual(code, 1)
        self.assertIn('CAPACITY_UNAVAILABLE', errors)
        self.assertEqual(self.provider.mutations, [])

    def test_expired_validation_does_not_create_resources(self):
        self.controller = {'validation': 'true', 'validation-expires': '1'}
        code, _, errors = self.create()
        self.assertEqual(code, 1)
        self.assertIn('Validation session ends too soon', errors)
        self.assertEqual(self.provider.mutations, [])

    def test_five_builders_reject_sixth_without_mutation(self):
        for number in range(5):
            self.assertEqual(self.create(f'fixture-{number}')[0], 0)
        self.provider.calls.clear()
        code, _, errors = self.create('sixth')
        self.assertEqual(code, 1)
        self.assertIn('BUILD_BUSY', errors)
        self.assertEqual(self.provider.mutations, [])

    def test_cleanup_removes_server_and_address(self):
        code, created, _ = self.create()
        self.assertEqual(code, 0)
        code, deleted, _ = self.cli(builders, 'delete', str(created['id']))
        self.assertEqual(code, 0)
        self.assertTrue(deleted['addresses_removed'])
        self.assertEqual(self.provider.rows['servers'], [])
        self.assertEqual(self.provider.rows['primary_ips'], [])

    def test_reconcile_finishes_addresses_after_lost_server_delete_response(self):
        self.assertEqual(self.create()[0], 0)
        server = self.provider.rows['servers'][0]
        self.provider.lose_delete_response = True
        self.assertEqual(self.cli(builders, 'delete', str(server['id']))[0], 1)
        self.assertEqual(self.provider.rows['servers'], [])
        self.assertEqual(len(self.provider.rows['primary_ips']), 1)
        code, output, _ = self.cli(builders, 'reconcile')
        self.assertEqual(code, 0)
        self.assertEqual(output['failures'], [])
        self.assertEqual(self.provider.rows['primary_ips'], [])

    def test_reconcile_preserves_reassigned_orphan_address(self):
        self.assertEqual(self.create()[0], 0)
        server = self.provider.rows['servers'][0]
        self.provider.lose_delete_response = True
        self.assertEqual(self.cli(builders, 'delete', str(server['id']))[0], 1)
        self.provider.rows['primary_ips'][0]['assignee_id'] = 999
        code, output, _ = self.cli(builders, 'reconcile')
        self.assertEqual(code, 1)
        self.assertIn('reassigned', output['failures'][0]['error'])
        self.assertEqual(self.provider.rows['primary_ips'][0]['assignee_id'], 999)

    def test_malformed_builder_journal_does_not_starve_valid_orphan(self):
        (self.state / 'deleting-builder-1.json').write_text('{broken')
        (self.state / 'deleting-builder-2.json').write_text(json.dumps({'server': 2, 'addresses': [1002]}))
        self.provider.rows['primary_ips'].append({'id': 1002, 'assignee_id': None})
        code, output, _ = self.cli(builders, 'reconcile')
        self.assertEqual(code, 1)
        self.assertIsNotNone(output, 'CLI must summarize the failed journal')
        self.assertTrue(output['failures'])
        self.assertEqual(self.provider.rows['primary_ips'], [])
        self.assertFalse((self.state / 'deleting-builder-2.json').exists())

    def test_local_journal_failure_does_not_starve_another_expired_builder(self):
        self.assertEqual(self.create('first')[0], 0)
        self.assertEqual(self.create('second')[0], 0)
        first, second = self.provider.rows['servers']
        for server in (first, second):
            server['labels']['expires'] = '1'
        replace = builders.os.replace

        def fail_first_journal(source, destination):
            if Path(destination).name == f"deleting-builder-{first['id']}.json":
                raise PermissionError('fixture-private-provider-detail')
            return replace(source, destination)

        with patch.object(builders.os, 'replace', side_effect=fail_first_journal):
            code, output, _ = self.cli(builders, 'reconcile')
        self.assertEqual(code, 1)
        self.assertTrue(output['failures'])
        self.assertEqual([server['id'] for server in self.provider.rows['servers']], [first['id']])
        self.assertEqual([entry['id'] for entry in output['removed']], [second['id']])


if __name__ == '__main__':
    unittest.main()
