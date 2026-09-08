"""Cost-ledger behavior with fixed provider observations and calendar boundaries."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
import spending


class SpendingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)

    def row(self, **changes):
        return {'id': 'server:1', 'created': (self.now - timedelta(minutes=1)).isoformat(),
                'hourly': '0.03', 'monthly': '19', 'traffic_bytes': 0,
                'included_bytes': 1024**4, 'traffic_per_tb': '1', **changes}

    def calculate(self, rows, previous=None, now=None, opening=None):
        return spending.estimate(rows, previous or {}, now or self.now, Decimal('1.2'),
                                 self.now.isoformat(), Decimal('20'), [], opening or {})

    def test_short_resource_rounds_to_hour_and_applies_fx_and_vat(self):
        _, result = self.calculate([self.row(ended=self.now.isoformat())])
        self.assertEqual(result['estimated_eur_net'], 0.03)
        self.assertEqual(result['estimated_usd'], 0.04)
        self.assertEqual(result['forecast_usd'], 0.04)
        self.assertNotIn('actual_usd', result)

    def test_monthly_cap_limits_long_lived_resource(self):
        _, result = self.calculate([self.row(created='2026-08-01T00:00:00Z', hourly='1', monthly='10')])
        self.assertEqual(result['estimated_eur_net'], 10)
        self.assertEqual(result['forecast_eur_net'], 10)

    def test_missing_resource_retains_cost_without_projecting_future_cost(self):
        ledger, _ = self.calculate([self.row()])
        later = self.now + timedelta(minutes=5)
        ledger, first = self.calculate([], ledger, later)
        _, second = self.calculate([], ledger, later + timedelta(days=1))
        self.assertEqual(first['estimated_eur_net'], second['estimated_eur_net'])
        self.assertEqual(first['estimated_eur_net'], first['forecast_eur_net'])

    def test_archived_builder_between_polls_is_counted_once(self):
        row = self.row(ended=self.now.isoformat())
        ledger, first = self.calculate([row])
        _, second = self.calculate([row], ledger)
        self.assertEqual(first['estimated_eur_net'], second['estimated_eur_net'])

    def test_month_rollover_excludes_prior_deleted_resources_and_opening_amount(self):
        row = self.row(ended=self.now.isoformat())
        opening = {'month': '2026-09', 'amount_eur': '0.4678', 'source': 'retained validation estimate upper bound'}
        ledger, september = self.calculate([row], opening=opening)
        self.assertEqual(september['estimated_eur_net'], 0.4978)
        _, october = self.calculate([row], ledger, datetime(2026, 10, 1, tzinfo=timezone.utc), opening)
        self.assertEqual(october['estimated_usd'], 0)

    def test_traffic_above_included_allowance_is_charged(self):
        _, result = self.calculate([self.row(traffic_bytes=2*1024**4, ended=self.now.isoformat())])
        self.assertGreaterEqual(result['estimated_eur_net'], 1.03)
        self.assertLess(result['estimated_eur_net'], 1.031)

    def test_collection_gap_remains_visible_after_recovery(self):
        ledger, _ = self.calculate([self.row()])
        ledger, result = self.calculate([self.row()], ledger, self.now + timedelta(hours=1))
        self.assertTrue(any('Collection gap' in x for x in result['warnings']))
        _, result = self.calculate([self.row()], ledger, self.now + timedelta(hours=1, minutes=5))
        self.assertTrue(any('Collection gap' in x for x in result['warnings']))

    def test_invalid_fx_is_rejected(self):
        with patch.object(spending.urllib.request, 'urlopen') as request:
            request.return_value.__enter__.return_value.read.return_value = b'<Cube time="2020-01-01"><Cube currency="USD" rate="1.2"/></Cube>'
            with self.assertRaisesRegex(ValueError, 'Stale'):
                spending.exchange_rate(self.now)

    def test_atomic_write_keeps_existing_data_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'evidence.json'
            spending.write_json(path, {'previous': True})
            with patch.object(spending.os, 'replace', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    spending.write_json(path, {'previous': False})
            self.assertEqual(json.loads(path.read_text()), {'previous': True})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(path.parent.iterdir()), [path])


if __name__ == '__main__':
    unittest.main()
