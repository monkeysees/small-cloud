"""Monitor CLI behavior with only privileged OS/network boundaries replaced."""
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('monitor_cli', Path(__file__).parents[1] / 'monitor.py')
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


def root_metadata(result):
    return SimpleNamespace(st_uid=0, st_mode=result.st_mode, st_mtime=result.st_mtime, st_size=result.st_size)


class MonitorCLI(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({'disks': ['/'], 'services': ['docker.service'],
                                           'smtp': {'password': 'fixture-secret-never-print'}}))
        self.config.chmod(0o600)
        self.output = self.root / 'reports'
        self.spend = self.root / 'spend.json'
        now = datetime.now(timezone.utc)
        self.evidence = {'actual_usd': 0, 'forecast_usd': 0, 'actual_basis': 'provider-metered',
                         'as_of': now.isoformat(), 'source': 'fixture metering; September',
                         'fx_source': 'fixture USD identity rate 1', 'fx_as_of': now.isoformat()}

    def invoke(self, extra=()):
        self.spend.write_text(json.dumps(self.evidence))
        original_fstat, original_lstat = os.fstat, Path.lstat
        stdout = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'argv', ['monitor', '--config', str(self.config),
                '--spend', str(self.spend), '--output', str(self.output), *extra]))
            stack.enter_context(patch.object(os, 'fstat', side_effect=lambda fd: root_metadata(original_fstat(fd))))
            stack.enter_context(patch.object(Path, 'lstat', lambda path: root_metadata(original_lstat(path))))
            stack.enter_context(patch.object(monitor.shutil, 'disk_usage', return_value=SimpleNamespace(total=100, used=20, free=80)))
            stack.enter_context(patch.object(monitor.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)))
            smtp = stack.enter_context(patch.object(monitor.smtplib, 'SMTP', side_effect=AssertionError('unexpected SMTP')))
            smtps = stack.enter_context(patch.object(monitor.smtplib, 'SMTP_SSL', side_effect=AssertionError('unexpected SMTP TLS')))
            stack.enter_context(redirect_stdout(stdout))
            self.assertEqual(monitor.main(), 0)
            smtp.assert_not_called()
            smtps.assert_not_called()
        self.assertNotIn('fixture-secret-never-print', stdout.getvalue())
        return json.loads(stdout.getvalue())

    def test_actual_and_forecast_thresholds_are_independent(self):
        for actual, forecast, expected in [(49.99, 49.99, []), (50, 79.99, [50, 50]),
                                           (80, 100, [80, 100]), (110, 81, [100, 80])]:
            with self.subTest(actual=actual, forecast=forecast):
                self.evidence.update(actual_usd=actual, forecast_usd=forecast)
                report = self.invoke()
                alerts = report['alerts']
                self.assertEqual(len(alerts), len(expected))
                for message, threshold in zip(alerts, expected):
                    self.assertIn(f'USD {threshold} threshold', message)
                self.assertEqual(report['delivery'], 'not requested')

    def test_stale_or_estimated_actuals_close_spending_evidence(self):
        for changes in ({'as_of': (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()},
                        {'actual_basis': 'list-price-estimate'}, {'actual_usd': float('nan')},
                        {'fx_as_of': (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()}):
            with self.subTest(changes=changes):
                original = self.evidence.copy()
                self.evidence.update(changes)
                report = self.invoke()
                self.assertNotIn('spending', report)
                self.assertIn('cost monitoring unavailable', report['alerts'][0])
                self.evidence = original

    def test_world_readable_configuration_is_refused(self):
        self.config.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'mode 0600'):
            self.invoke()
        self.assertFalse(self.output.exists())

    def test_symlink_configuration_is_refused(self):
        link = self.root / 'linked.json'
        link.symlink_to(self.config)
        self.config = link
        with self.assertRaises(OSError):
            self.invoke()

    def test_delivery_check_without_send_does_not_contact_smtp(self):
        report = self.invoke(['--delivery-check'])
        self.assertIn('receipt must be independently confirmed', report['alerts'][0])

    def test_old_reports_are_removed_and_current_report_is_retained(self):
        self.output.mkdir(mode=0o700)
        old = self.output / 'report-20000101T000000Z.json'
        old.write_text('{}')
        stale = (datetime.now(timezone.utc) - timedelta(days=8)).timestamp()
        os.utime(old, (stale, stale))
        self.invoke()
        self.assertFalse(old.exists())
        reports = list(self.output.glob('report-*.json'))
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
