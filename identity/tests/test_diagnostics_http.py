"""Diagnostics acceptance through the authenticated HTTP and creator CLI seams."""
import json
import socket
import subprocess
import sys
import threading
import time
import unittest

from identity.tests import test_limits_http as fixture


class DiagnosticsAcceptance(unittest.TestCase):
    setUp = fixture.LimitsAcceptance.setUp
    operator = fixture.LimitsAcceptance.operator
    start_platform = fixture.LimitsAcceptance.start_platform
    http = fixture.LimitsAcceptance.http
    approve = fixture.LimitsAcceptance.approve
    http_login = fixture.LimitsAcceptance.http_login
    cli = fixture.LimitsAcceptance.cli
    login = fixture.LimitsAcceptance.login
    creator = fixture.LimitsAcceptance.creator
    deploy = fixture.LimitsAcceptance.deploy
    worker = fixture.LimitsAcceptance.worker
    admit_creator = fixture.LimitsAcceptance.admit_creator

    def diagnostic(self, operation, source, content, now=None, action='ingest'):
        arguments = ['--database', str(self.home / 'server/identity.sqlite3'),
                     '--key', str(self.home / 'redaction.key'), action, '--deployment', operation]
        if action == 'ingest':
            arguments += ['--source', source]
        script = ('from identity import diagnostics; diagnostics.main()' if now is None else
                  'from identity import diagnostics; diagnostics.main(clock=lambda: ' + str(now) + ')')
        result = subprocess.run([sys.executable, '-c', script, *arguments], input=content,
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout, b'')

    def logs(self, query='source=runtime', token=None):
        status, raw = self.http('/api/apps/example/logs?' + query, token=token or self.token)
        self.assertEqual(status, 200, raw)
        self.assertLessEqual(len(raw.encode()), 1024 * 1024)
        return json.loads(raw)['data']

    def test_chunk_split_database_values_are_redacted_before_cli_output(self):
        self.creator()
        self.login()
        _, accepted = self.deploy()
        operation = accepted['data']['operation_id']
        password = 'diagnostic-confidential-value'
        url = 'postgresql://app:' + password + '@database/app'
        self.diagnostic(operation, None, json.dumps({'values': [password, url]}).encode(), action='register')
        content = b'x' * (65536 - 10) + url.encode() + b'\n' + password.encode() + b'\nvisible\x1b[2J\n'
        self.diagnostic(operation, 'runtime', content)
        result = self.cli('logs', 'example', '--source', 'runtime')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(password, result.stdout + result.stderr)
        self.assertNotIn('postgresql://', result.stdout)
        self.assertNotIn('\x1b', result.stdout)
        data = json.loads(result.stdout)['data']
        self.assertTrue(data['truncated'])
        self.assertGreater(data['dropped_bytes'], 0)
        self.assertIn('[REDACTED]', str(data['entries']))
        self.assertIn('visible', str(data['entries']))

    def test_creator_and_administrator_can_read_both_sources_but_other_creators_cannot(self):
        self.creator()
        owner = self.admit_creator('owner@example.test')
        other = self.admit_creator('other@example.test')
        _, accepted = self.deploy(token=owner)
        self.worker(fixture.BuildFixture()).once()
        for source in ('build', 'runtime'):
            path = '/api/apps/example/logs?source=' + source
            for token in (owner, self.token):
                status, raw = self.http(path, token=token)
                self.assertEqual(status, 200, raw)
                self.assertIn('entries', json.loads(raw)['data'])
            self.assertEqual(self.http(path, token=other)[0], 404)
        self.assertEqual(self.http('/api/apps/example', token=other)[0], 404)
        self.assertEqual(self.http('/api/operations/' + accepted['data']['operation_id'], token=other)[0], 404)

    def test_cursor_continues_original_build_after_redeployment_and_rejects_other_actor(self):
        self.creator()
        owner = self.admit_creator('owner@example.test')
        _, accepted = self.deploy(token=owner)
        operation = accepted['data']['operation_id']
        self.diagnostic(operation, 'build', b'first\nsecond\nthird\n')
        first = self.logs('source=build&limit=1', owner)
        self.assertEqual(first['entries'][0]['message'], 'first')
        cursor = first['next_cursor']
        self.worker().once()
        self.deploy(token=owner)
        continued = self.logs('source=build&cursor=' + cursor, owner)
        self.assertEqual([entry['message'] for entry in continued['entries']], ['second', 'third'])
        self.assertIsNone(continued['next_cursor'])
        self.assertEqual(self.http('/api/apps/example/logs?source=build&cursor=' + cursor, token=self.token)[0], 400)

    def test_retention_uses_ingestion_time_and_expires_at_seven_days(self):
        self.creator()
        _, accepted = self.deploy()
        operation = accepted['data']['operation_id']
        now = time.time()
        self.diagnostic(operation, 'runtime', b'older\n', now)
        self.diagnostic(operation, 'runtime', b'newer\n', now + 60)
        self.platform_server.application.publishing.clock = lambda: now + 604800
        data = self.logs()
        self.assertEqual([entry['message'] for entry in data['entries']], ['newer'])
        self.assertTrue(data['truncated'])
        self.assertGreater(data['dropped_bytes'], 0)
        self.platform_server.application.publishing.clock = lambda: now + 604860
        self.assertEqual(self.logs()['entries'], [])

    def test_runtime_volume_is_shared_across_deployments_and_snapshots_are_bounded(self):
        self.creator()
        _, accepted = self.deploy()
        first = accepted['data']['operation_id']
        self.diagnostic(first, 'runtime', b'old-record\n' + (b'a' * 14000 + b'\n') * 2000)
        self.worker().once()
        _, accepted = self.deploy()
        self.diagnostic(accepted['data']['operation_id'], 'runtime', (b'b' * 14000 + b'\n') * 2000)
        page = self.logs('source=runtime&limit=1000')
        self.assertTrue(page['truncated'])
        self.assertGreater(page['dropped_bytes'], 0)
        self.assertIsNotNone(page['next_cursor'])
        self.assertNotIn('old-record', str(page['entries']))
        self.assertLess(len(page['entries']), 1000)
        self.assertLessEqual(max(len(json.dumps(entry).encode()) for entry in page['entries']), 16384)

    def test_real_docker_syslog_redacts_database_output_without_a_local_log_cache(self):
        from identity.collector import Collector
        from identity.diagnostics import Registry
        from identity.worker import State

        self.creator()
        _, accepted = self.deploy()
        operation = accepted['data']['operation_id']
        state = State(self.home / 'server/identity.sqlite3')
        registry = Registry(state, self.home / 'redaction.key')
        secret = 'syslog-fixture-confidential-password'
        url = 'postgresql://fixture:' + secret + '@database/app'
        self.diagnostic(operation, None, json.dumps({'values': [secret, url, 'multiline\nconfidential']}).encode(), action='register')
        socket_path = self.home / 'logs.sock'
        collector = Collector(socket_path, state, registry)
        stop = threading.Event()
        def collect():
            while not stop.is_set():
                collector.poll(0.05)
        thread = threading.Thread(target=collect)
        thread.start()
        def cleanup():
            stop.set()
            thread.join(timeout=5)
            collector.close()
        self.addCleanup(cleanup)
        environment = self.home / 'runtime-env'
        environment.write_text('DATABASE_URL=' + url + '\n')
        environment.chmod(0o600)
        result = subprocess.run(['docker', 'run', '--rm', '--log-driver=syslog',
            '--log-opt=syslog-address=unix://' + str(socket_path), '--log-opt=syslog-format=rfc5424micro',
            '--log-opt=tag=' + operation, '--log-opt=cache-disabled=true', '--env-file', str(environment),
            'python:3.12-slim-bookworm', 'python', '-c',
            'import os; print("x" * (16384-10) + os.environ["DATABASE_URL"]); '
            'print("multiline"); print("confidential"); print("runtime-observed")'],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            data = self.logs()
            if 'runtime-observed' in str(data['entries']):
                break
            time.sleep(0.05)
        self.assertIn('runtime-observed', str(data['entries']))
        self.assertIn('[REDACTED]', str(data['entries']))
        self.assertNotIn(secret, str(data))
        self.assertNotIn('postgresql://', str(data))
        self.assertNotIn('multiline', str(data))
        self.assertNotIn('confidential', str(data))

    def test_registration_refreshes_an_open_stream_without_revealing_its_pending_prefix(self):
        from identity.collector import Collector
        from identity.diagnostics import Registry
        from identity.worker import State

        self.creator()
        _, accepted = self.deploy()
        operation = accepted['data']['operation_id']
        self.diagnostic(operation, None, b'{"values":["old-secret-value"]}', action='register')
        state = State(self.home / 'server/identity.sqlite3')
        collector = Collector(self.home / 'logs.sock', state, Registry(state, self.home / 'redaction.key'))
        self.addCleanup(collector.close)
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(connection.close)
        connection.connect(str(self.home / 'logs.sock'))
        collector.poll(0.1)
        def send(message):
            connection.sendall(('<14>1 2026-09-09T00:00:00Z runtime ' + operation + ' 1 - - ' + message + '\n').encode())
            collector.poll(0.1)
        send('old-secret-')
        self.diagnostic(operation, None, b'{"values":["new-secret-value"]}', action='register')
        send('value new-secret-value')
        data = self.logs()
        self.assertNotIn('old-secret-', str(data))
        self.assertNotIn('new-secret-value', str(data))
        self.assertIn('[REDACTED] [REDACTED]', str(data))


if __name__ == '__main__':
    unittest.main()
