"""Procurement retries against the real foundation with an in-memory provider."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cloud
import cx_watch
from test_cloud_cli import Provider, PUBLIC_KEY


class WatchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.root.chmod(0o700)
        self.path = self.root / 'cx-watch.json'
        for name, value in [('operator_ed25519', 'private'), ('operator_ed25519.pub', PUBLIC_KEY), ('hetzner-token', 'test')]:
            target = self.root / name
            target.write_text(value)
            target.chmod(0o600)
        self.provider = Provider()
        self.ip_price = '0.50'
        self.ip_hourly = '0.0008'
        self.lost = False
        self.reject_runtime = False
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(cloud, 'STATE_DIR', self.root))
        self.stack.enter_context(patch.object(cloud, 'SECRET_DIR', self.root))
        self.stack.enter_context(patch.object(cloud.urllib.request, 'urlopen', self.transport))
        self.api = cloud.API('hetzner')
        self.state = {}

    def transport(self, request, timeout):
        if request.full_url.endswith('/pricing'):
            return self.provider.response({'pricing': {'currency': 'EUR', 'vat_rate': '19', 'volume': {},
                'primary_ips': [{'type': 'ipv4', 'prices': [{'location': loc, 'price_monthly': {'net': self.ip_price}, 'price_hourly': {'net': self.ip_hourly}} for loc in cloud.LOCATIONS]}]}})
        if self.reject_runtime and request.get_method() == 'POST' and request.full_url.endswith('/servers') and json.loads(request.data)['name'].endswith('runtime'):
            self.reject_runtime = False
            self.provider.reject_creates = ['resource_unavailable']
        result = self.provider(request, timeout)
        if self.lost and request.get_method() == 'POST' and request.full_url.endswith('/servers'):
            self.lost = False
            raise OSError('secret response detail')
        return result

    def cycle(self, check=False):
        return cx_watch.cycle(self.api, self.state, self.path, '198.51.100.1/32', check)

    def test_wait_and_check_do_not_provision(self):
        self.provider.available = False
        self.assertEqual(self.cycle()['status'], 'waiting')
        self.assertFalse(self.provider.mutations)
        self.provider.available = True
        self.assertEqual(self.cycle(check=True)['status'], 'ready')
        self.assertFalse(self.provider.mutations)

    def test_completed_run_is_terminal_even_after_hosts_removed(self):
        self.assertEqual(self.cycle()['status'], 'complete')
        self.provider.rows['servers'] = []
        count = len(self.provider.calls)
        self.assertEqual(self.cycle()['status'], 'complete')
        self.assertEqual(len(self.provider.calls), count)

    def test_lost_create_response_adopts_visible_server_without_duplicate(self):
        self.lost = True
        with self.assertRaises(cloud.Failure):
            self.cycle()
        self.assertIn('pending', self.state)
        self.assertEqual(self.cycle()['status'], 'complete')
        self.assertEqual(len(self.provider.rows['servers']), 2)
        self.assertNotIn('pending', self.state)

    def test_unknown_absent_outcome_blocks_retries(self):
        self.provider.reject_creates = ['unknown']
        with self.assertRaises(cloud.Failure):
            self.cycle()
        for _ in range(2):
            with self.assertRaisesRegex(cloud.Failure, 'manual inventory'):
                self.cycle()
        creates = [c for c in self.provider.calls if c[:2] == ('POST', 'servers')]
        self.assertEqual(len(creates), 1)

    def test_partial_pair_keeps_location_and_waits_for_missing_type(self):
        self.reject_runtime = True
        with self.assertRaises(cloud.Failure):
            self.cycle()
        self.assertEqual(self.state['location'], 'nbg1')
        self.assertNotIn('pending', self.state)
        self.provider.available = False
        self.assertEqual(self.cycle()['status'], 'waiting')
        self.assertEqual(len(self.provider.rows['servers']), 1)
        self.provider.available = True
        self.assertEqual(self.cycle()['status'], 'complete')
        self.assertEqual({s['location']['name'] for s in self.provider.rows['servers']}, {'nbg1'})

    def test_price_ceiling_blocks_before_any_create(self):
        self.ip_price = '0.51'
        self.assertEqual(self.cycle()['status'], 'blocked')
        self.assertFalse(self.provider.mutations)

    def test_cpx_existing_host_is_not_adopted(self):
        self.provider.rows['servers'].append({'id': 123, 'name': 'small-cloud-control', 'labels': {**cloud.OWNER, 'role': 'control'},
                                            'server_type': {'name': 'cpx32'}, 'location': {'name': 'nbg1'}})
        with self.assertRaisesRegex(cloud.Failure, 'authorized permanent CX'):
            self.cycle()
        self.assertFalse(self.provider.mutations)

    def test_hourly_ceiling_blocks_even_when_monthly_price_is_approved(self):
        self.ip_hourly = '0.0009'
        self.assertEqual(self.cycle()['status'], 'blocked')
        self.assertFalse(self.provider.mutations)

    def test_notification_is_deduplicated_and_failed_delivery_retries(self):
        self.state.update(status='complete')
        config = self.root / 'smtp.json'
        config.write_text(json.dumps({'smtp': {'password': 'private'}}))
        config.chmod(0o600)
        with patch.object(cx_watch, 'send_alert', side_effect=OSError):
            with self.assertRaises(OSError):
                cx_watch.notify(self.state, self.path, config)
        self.assertNotIn('notified', self.state)
        with patch.object(cx_watch, 'send_alert') as send:
            cx_watch.notify(self.state, self.path, config)
            cx_watch.notify(self.state, self.path, config)
        self.assertEqual(send.call_count, 1)
        self.assertNotIn('private', self.path.read_text())


if __name__ == '__main__':
    unittest.main()
