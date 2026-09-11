"""Deployment observation through the executable and authenticated HTTPS service."""
import json
import os
import select
import shlex
import signal
import socket
import subprocess
import threading
import time
import unittest
import uuid

from identity.common import Failure
from identity.tests import test_identity_cli as identity_fixture
from identity.tests import test_deployment_http as deployment_fixture
from identity.worker import State, Worker


class InfrastructureFixture:
    failure = None
    build_prefix = b''

    def build(self, operation, logs):
        if self.failure == 'UNCERTAIN_BUILD':
            raise Failure('INTERNAL', 'Builder termination requires operator reconciliation.', 500,
                          reconciliation_required=True)
        if self.failure == 'BUILD_FAILED':
            logs.feed(self.build_prefix)
            logs.feed(b'Compiler: missing module fixture_dependency.\n')
            raise Failure(self.failure, 'Fixture build failed.', 500)
        logs.feed(b'Fixture build completed.\n')
        return {}

    def build_accounting(self, operation):
        return {'terminated': True, 'duration_seconds': 1}

    def start(self, operation, artifact, app, register):
        return {'host': '127.0.0.1', 'port': 18080, 'container': operation['id']}

    def ready(self, target):
        if self.failure:
            raise Failure(self.failure, 'Fixture readiness refused.', 500)

    def promote(self, operation, app, target):
        return target['container']

    def cleanup(self, operation, app, succeeded=False):
        pass


class CompletionAcceptance(unittest.TestCase):
    operator = deployment_fixture.DeploymentAcceptance.operator
    start_platform = deployment_fixture.DeploymentAcceptance.start_platform
    restart_platform = identity_fixture.IdentityAcceptance.restart_platform
    http = deployment_fixture.DeploymentAcceptance.http
    approve = deployment_fixture.DeploymentAcceptance.approve
    http_login = deployment_fixture.DeploymentAcceptance.http_login
    cli = deployment_fixture.DeploymentAcceptance.cli
    login = deployment_fixture.DeploymentAcceptance.login
    creator = deployment_fixture.DeploymentAcceptance.creator

    def setUp(self):
        deployment_fixture.DeploymentAcceptance.setUp(self)
        self.creator()
        self.login()
        self.source = self.home / 'source'
        self.source.mkdir()
        (self.source / 'Dockerfile').write_text('FROM scratch\n')
        self.infrastructure = InfrastructureFixture()
        self.worker = Worker(State(self.home / 'server/identity.sqlite3'), self.infrastructure)

    def launch(self, *args, json_mode=True):
        process = subprocess.Popen([*identity_fixture.cli_command(),
            *(['--json'] if json_mode else []), 'app', 'deploy', str(self.source),
            '--name', 'example', '--description', 'Fixture app', *args],
            cwd=identity_fixture.ROOT, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
        self.addCleanup(cleanup)
        return process

    def accepted(self, process):
        # Read bytes to avoid buffered readline hiding a later progress line from select.
        output = b''
        deadline = time.monotonic() + 5
        while b'Deployment: accepted (0s elapsed).\n' not in output:
            remaining = deadline - time.monotonic()
            self.assertGreater(remaining, 0, output)
            self.assertTrue(select.select([process.stderr], [], [], remaining)[0], output)
            byte = process.stderr.read(1)
            self.assertTrue(byte, output)
            output += byte
        return output.decode()

    def finish(self, process, code=0, timeout=10):
        stdout, stderr = process.communicate(timeout=timeout)
        self.assertEqual(process.returncode, code, stdout + stderr)
        return stdout.decode(), stderr.decode()

    def inspect(self, details):
        result = self.cli(*shlex.split(details['next_command'])[1:])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        operation = json.loads(result.stdout)['data']
        self.assertEqual(operation['operation_id'], details['operation_id'])
        self.assertEqual(operation['request_id'], details['request_id'])
        return operation

    def test_default_wait_returns_readable_ready_url_and_terminal_json(self):
        previous_url = None
        for json_mode in (False, True):
            with self.subTest(json=json_mode):
                process = self.launch(json_mode=json_mode)
                self.accepted(process)
                self.assertIsNone(process.poll())
                self.assertTrue(self.worker.once())
                stdout, stderr = self.finish(process)
                status = json.loads(self.cli('app', 'status', 'example').stdout)['data']
                self.assertEqual(status['availability'], 'running')
                self.assertIn('Deployment: succeeded', stderr)
                if json_mode:
                    result = json.loads(stdout)
                    self.assertTrue(result['ok'])
                    self.assertTrue(result['data']['ready'])
                    self.assertEqual(result['data']['state'], 'succeeded')
                    self.assertEqual(result['data']['url'], previous_url)
                    self.assertEqual(result['data']['active_deployment_id'], status['active_deployment_id'])
                    self.assertEqual(self.inspect(result['data'])['state'], 'succeeded')
                else:
                    self.assertIn('Ready: example', stdout)
                    self.assertIn(status['url'], stdout)
                    self.assertNotIn('{', stdout)
                previous_url = status['url']

    def test_identity_outage_times_out_with_the_same_accepted_request_and_operation(self):
        request_id = str(uuid.uuid4())
        process = self.launch('--request-id', request_id, '--timeout', '22')
        self.accepted(process)
        self.platform_server.shutdown()
        self.platform_server.server_close()
        stdout, stderr = self.finish(process, 6, timeout=26)
        result = json.loads(stdout)
        self.assertEqual(result['error']['code'], 'WAIT_TIMEOUT')
        details = result['error']['details']
        self.assertTrue(details['work_continues'])
        self.assertEqual(details['request_id'], request_id)
        self.assertEqual(details['last_observation_error']['code'], 'NETWORK_ERROR')
        self.assertNotIn('Deployment: succeeded', stderr)
        self.assertGreaterEqual(stderr.count('connection unavailable'), 2)
        self.assertIn('elapsed', stderr)
        self.restart_platform()
        self.assertEqual(self.inspect(details)['state'], 'accepted')
        self.assertTrue(self.worker.once())
        self.assertFalse(self.worker.once())
        self.assertEqual(self.inspect(details)['state'], 'succeeded')

    def test_no_wait_is_acceptance_only_and_replay_can_observe_original_completion(self):
        request_id = str(uuid.uuid4())
        stdout, stderr = self.finish(self.launch('--no-wait', '--request-id', request_id))
        accepted = json.loads(stdout)
        self.assertEqual(accepted['request_id'], request_id)
        self.assertEqual(accepted['data']['state'], 'accepted')
        self.assertFalse(accepted['data']['ready'])
        self.assertIsNone(accepted['data']['active_deployment_id'])
        self.assertEqual(self.inspect(accepted['data'])['state'], 'accepted')
        self.assertNotIn('Deployment: succeeded', stderr)
        stdout, _ = self.finish(self.launch('--no-wait', '--request-id', request_id, json_mode=False))
        self.assertIn('Accepted; readiness not confirmed: example', stdout)
        self.assertIn(accepted['data']['next_command'], stdout)
        self.assertTrue(self.worker.once())
        stdout, _ = self.finish(self.launch('--request-id', request_id))
        ready = json.loads(stdout)
        self.assertTrue(ready['data']['ready'])
        self.assertEqual(ready['data']['operation_id'], accepted['data']['operation_id'])
        self.assertEqual(ready['request_id'], request_id)
        self.assertFalse(self.worker.once())
        (self.source / 'Dockerfile').write_text('FROM scratch\n# changed\n')
        stdout, _ = self.finish(self.launch('--request-id', request_id), 5)
        self.assertEqual(json.loads(stdout)['error']['code'], 'REQUEST_CONFLICT')

    def test_terminal_failures_retain_inspection_and_do_not_report_ready(self):
        for code, exit_code in (('BUILD_FAILED', 1), ('STARTUP_FAILED', 1), ('ACTIVE_CAPACITY', 5)):
            with self.subTest(code=code):
                self.infrastructure.failure = code
                process = self.launch()
                self.accepted(process)
                self.assertTrue(self.worker.once())
                stdout, _ = self.finish(process, exit_code)
                result = json.loads(stdout)
                self.assertFalse(result['ok'])
                self.assertIsNone(result['data'])
                self.assertEqual(result['error']['code'], code)
                details = result['error']['details']
                self.assertEqual(details['state'], 'failed')
                self.assertFalse(details['work_continues'])
                self.assertEqual(self.inspect(details)['error']['code'], code)

    def test_failed_build_reports_diagnostics_and_executable_recovery_commands(self):
        self.infrastructure.failure = 'BUILD_FAILED'
        process = self.launch()
        self.accepted(process)
        self.assertTrue(self.worker.once())
        stdout, _ = self.finish(process, 1)
        details = json.loads(stdout)['error']['details']
        self.assertEqual(details['failed_phase'], 'building')
        self.assertEqual(details['diagnostics']['status'], 'available')
        self.assertIn('missing module fixture_dependency', str(details['diagnostics']['entries']))
        self.assertEqual(details['diagnostics']['source'], 'build')
        for command in details['next_steps']:
            result = self.cli(*shlex.split(command)[1:])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        inspected = self.inspect(details)
        self.assertEqual(inspected['recovery']['failed_phase'], 'building')
        self.assertFalse(self.worker.once())

    def test_capacity_failure_reports_starting_phase_without_claiming_build_failure(self):
        self.infrastructure.failure = 'ACTIVE_CAPACITY'
        process = self.launch()
        self.accepted(process)
        self.assertTrue(self.worker.once())
        stdout, _ = self.finish(process, 5)
        details = json.loads(stdout)['error']['details']
        self.assertEqual(details['failed_phase'], 'starting')
        self.assertEqual(details['diagnostics']['source'], 'runtime')

    def test_diagnostic_access_denial_preserves_failure_and_identifies_access_recovery(self):
        original = self.platform_server.RequestHandlerClass
        class DeniedLogs(original):
            def do_GET(handler):
                if '/logs?' in handler.path:
                    from identity.common import envelope
                    handler.respond(404, envelope(failure=Failure('NOT_FOUND', 'App not found.', 404)))
                    return
                super().do_GET()
        self.platform_server.RequestHandlerClass = DeniedLogs
        self.infrastructure.failure = 'BUILD_FAILED'
        process = self.launch()
        self.accepted(process)
        self.assertTrue(self.worker.once())
        stdout, _ = self.finish(process, 1)
        result = json.loads(stdout)
        self.assertEqual(result['error']['code'], 'BUILD_FAILED')
        details = result['error']['details']
        self.assertEqual(details['diagnostics']['status'], 'unavailable')
        self.assertEqual(details['diagnostics']['error_code'], 'NOT_FOUND')
        self.assertEqual(details['diagnostics']['entries'], [])
        self.assertIn('workspace administrator', details['guidance'])
        self.assertEqual(self.inspect(details)['state'], 'failed')
        self.assertFalse(self.worker.once())

    def test_startup_excerpt_is_redacted_bounded_and_reports_interrupted_collection(self):
        from identity.collector import Collector
        self.infrastructure.failure = 'STARTUP_FAILED'
        request_id = str(uuid.uuid4())
        stdout, _ = self.finish(self.launch('--no-wait', '--request-id', request_id))
        operation = json.loads(stdout)['data']['operation_id']
        self.worker.registry.register(operation, ['fixture-confidential'])
        collector = Collector(self.home / 'logs.sock', self.worker.state, self.worker.registry)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.connect(str(self.home / 'logs.sock'))
                collector.poll(.1)
                for index in range(25):
                    message = 'x' * 300 + ' fixture-confidential startup marker ' + str(index)
                    connection.sendall(('<14>1 2026-09-11T00:00:00Z runtime ' + operation +
                                        ' 1 - - ' + message + '\n').encode())
                    collector.poll(.1)
            collector.poll(.1)
        finally:
            collector.close()
        self.assertTrue(self.worker.once())
        stdout, stderr = self.finish(self.launch('--request-id', request_id), 1)
        details = json.loads(stdout)['error']['details']
        self.assertEqual(details['failed_phase'], 'starting')
        diagnostic = details['diagnostics']
        self.assertEqual(diagnostic['status'], 'partial')
        self.assertTrue(diagnostic['collection_interrupted'])
        self.assertTrue(diagnostic['truncated'])
        self.assertLessEqual(len(diagnostic['entries']), 20)
        self.assertLessEqual(sum(len(entry['message']) for entry in diagnostic['entries']), 4096)
        self.assertIn('startup marker 24', str(diagnostic['entries']))
        self.assertIn('[REDACTED]', stdout)
        self.assertNotIn('fixture-confidential', stdout + stderr)
        self.assertIn('operator', details['operator_escalation'])
        stdout, stderr = self.finish(self.launch('--request-id', request_id, json_mode=False), 1)
        self.assertEqual(stdout, '')
        self.assertIn('Failed phase: starting', stderr)
        self.assertIn('startup marker 24', stderr)
        self.assertNotIn('fixture-confidential', stderr)
        self.assertIn(details['next_command'], stderr)
        self.assertFalse(self.worker.once())

    def test_unavailable_publishing_worker_requires_inspection_and_operator_escalation(self):
        stdout, stderr = self.finish(self.launch('--timeout', '1'), 6)
        details = json.loads(stdout)['error']['details']
        self.assertEqual(details['state'], 'accepted')
        self.assertTrue(details['reconciliation_required'])
        self.assertIn('operator', details['operator_escalation'])
        self.assertIn('Do not submit another deployment', details['guidance'])
        self.assertNotIn('succeeded', stderr)
        operation = self.inspect(details)
        self.assertEqual(operation['state'], 'accepted')
        self.assertTrue(operation['recovery']['reconciliation_required'])
        self.assertIn('operator', operation['recovery']['operator_escalation'])
        self.assertTrue(self.worker.once())
        self.assertFalse(self.worker.once())
        self.assertEqual(self.inspect(details)['state'], 'succeeded')

    def test_build_diagnosis_reaches_failure_after_more_than_sixteen_pages_of_progress(self):
        self.infrastructure.failure = 'BUILD_FAILED'
        self.infrastructure.build_prefix = b'ordinary compiler progress\n' * 16020
        process = self.launch()
        self.accepted(process)
        self.assertTrue(self.worker.once())
        stdout, _ = self.finish(process, 1)
        diagnostic = json.loads(stdout)['error']['details']['diagnostics']
        self.assertIn('missing module fixture_dependency', str(diagnostic['entries']))
        self.assertTrue(diagnostic['truncated'])

    def test_recovery_log_command_reads_tail_without_walking_old_progress(self):
        self.infrastructure.failure = 'BUILD_FAILED'
        self.infrastructure.build_prefix = b'ordinary compiler progress\n' * 1100
        process = self.launch()
        self.accepted(process)
        self.assertTrue(self.worker.once())
        stdout, _ = self.finish(process, 1)
        details = json.loads(stdout)['error']['details']
        command = details['next_steps'][1]
        self.assertIn('--tail', command)
        result = self.cli(*shlex.split(command)[1:])
        self.assertEqual(result.returncode, 0, result.stdout)
        logs = json.loads(result.stdout)['data']
        self.assertIn('missing module fixture_dependency', logs['entries'][-1]['message'])
        self.assertLessEqual(len(logs['entries']), 100)
        self.assertIsNone(logs['next_cursor'])
        self.assertTrue(logs['truncated'])
        refused = self.cli('app', 'logs', 'example', '--source', 'build', '--tail', '--cursor', 'invalid')
        self.assertEqual(refused.returncode, 2)

    def test_missing_request_receipt_does_not_advise_a_duplicate_deployment(self):
        request_id = str(uuid.uuid4())
        result = self.cli('operation', 'status', '--request-id', request_id)
        self.assertEqual(result.returncode, 4, result.stdout)
        error = json.loads(result.stdout)['error']
        self.assertEqual(error['code'], 'NOT_FOUND')
        self.assertTrue(error['details']['outcome_unknown'])
        self.assertEqual(error['details']['request_id'], request_id)
        self.assertIn('Do not submit another deployment', error['details']['guidance'])
        self.assertIn('operator', error['details']['operator_escalation'])

    def test_service_side_uncertainty_preserves_error_and_does_not_replay_work(self):
        self.infrastructure.failure = 'UNCERTAIN_BUILD'
        process = self.launch('--timeout', '4')
        self.accepted(process)
        self.assertTrue(self.worker.once())
        stdout, _ = self.finish(process, 1)
        error = json.loads(stdout)['error']
        self.assertEqual(error['code'], 'INTERNAL')
        self.assertIn('Builder termination', error['message'])
        details = error['details']
        self.assertTrue(details['reconciliation_required'])
        self.assertEqual(details['state'], 'building')
        self.assertEqual(details['failed_phase'], 'building')
        self.assertIn('operator', details['operator_escalation'])
        self.assertEqual(self.inspect(details)['error']['code'], 'INTERNAL')
        self.assertFalse(self.worker.once())

    def test_diagnostic_outage_deadline_and_interrupt_never_replace_build_failure(self):
        self.infrastructure.failure = 'BUILD_FAILED'
        request_id = str(uuid.uuid4())
        stdout, _ = self.finish(self.launch('--no-wait', '--request-id', request_id))
        operation_id = json.loads(stdout)['data']['operation_id']
        self.assertTrue(self.worker.once())
        original = self.platform_server.RequestHandlerClass
        for mode in ('timeout', 'interrupt', 'malformed'):
            with self.subTest(mode=mode):
                entered, release = threading.Event(), threading.Event()
                class UnavailableLogs(original):
                    def do_GET(handler):
                        if '/logs?' in handler.path:
                            entered.set()
                            if mode == 'malformed':
                                from identity.common import envelope
                                handler.respond(200, envelope({'entries': None}))
                            else:
                                release.wait(7)
                            return
                        super().do_GET()
                self.platform_server.RequestHandlerClass = UnavailableLogs
                try:
                    process = self.launch('--request-id', request_id)
                    self.assertTrue(entered.wait(5))
                    started = time.monotonic()
                    if mode == 'interrupt':
                        process.send_signal(signal.SIGINT)
                    stdout, _ = self.finish(process, 1, timeout=5)
                    self.assertLess(time.monotonic() - started, 4 if mode == 'timeout' else 2)
                    error = json.loads(stdout)['error']
                    self.assertEqual(error['code'], 'BUILD_FAILED')
                    self.assertEqual(error['message'], 'Fixture build failed.')
                    self.assertEqual(error['details']['operation_id'], operation_id)
                    self.assertEqual(error['details']['state'], 'failed')
                    self.assertEqual(error['details']['diagnostics']['status'], 'unavailable')
                    self.assertEqual(error['details']['diagnostics']['error_code'],
                                     {'timeout': 'WAIT_TIMEOUT', 'interrupt': 'INTERRUPTED',
                                      'malformed': 'INVALID_RESPONSE'}[mode])
                    self.assertIn('operator', error['details']['operator_escalation'])
                finally:
                    release.set()
                    self.platform_server.RequestHandlerClass = original
        self.assertFalse(self.worker.once())

    def test_ctrl_c_stops_only_observation_and_pins_inspection_to_original_workspace(self):
        for json_mode in (True, False):
            with self.subTest(json=json_mode):
                process = self.launch('--workspace', 'ws-initial', json_mode=json_mode)
                self.accepted(process)
                if json_mode:
                    status, raw = self.http('/api/workspaces/create',
                        {'name': 'Other workspace', 'owner_email': 'admin@example.test'}, token=self.token,
                        headers={'X-Request-ID': str(uuid.uuid4())})
                    self.assertEqual(status, 200, raw)
                    workspace = json.loads(raw)['data']['workspace']['id']
                    status, raw = self.http('/api/workspaces/select', {'workspace': workspace}, token=self.token,
                        headers={'X-Request-ID': str(uuid.uuid4())})
                    self.assertEqual(status, 200, raw)
                started = time.monotonic()
                process.send_signal(signal.SIGINT)
                stdout, stderr = self.finish(process, 130)
                self.assertLess(time.monotonic() - started, 2)
                if json_mode:
                    result = json.loads(stdout)
                    self.assertEqual(result['error']['code'], 'INTERRUPTED')
                    details = result['error']['details']
                    self.assertTrue(details['work_continues'])
                    self.assertEqual(details['workspace_id'], 'ws-initial')
                    self.assertEqual(self.inspect(details)['state'], 'accepted')
                else:
                    self.assertEqual(stdout, '')
                    self.assertIn('accepted work continues', stderr)
                    command = next(line.removeprefix('Next: ') for line in stderr.splitlines() if line.startswith('Next: '))
                    inspected = self.cli(*shlex.split(command)[1:])
                    self.assertEqual(inspected.returncode, 0, inspected.stdout)
                    self.assertEqual(json.loads(inspected.stdout)['data']['state'], 'accepted')
                self.assertTrue(self.worker.once())
                self.assertFalse(self.worker.once())

    def test_polling_recovers_after_identity_restart_without_duplicate_submission(self):
        process = self.launch('--timeout', '9')
        self.accepted(process)
        self.platform_server.shutdown()
        self.platform_server.server_close()
        time.sleep(2.2)
        self.assertIsNone(process.poll())
        self.restart_platform()
        self.assertTrue(self.worker.once())
        stdout, stderr = self.finish(process)
        result = json.loads(stdout)
        self.assertTrue(result['data']['ready'])
        self.assertIn('connection unavailable', stderr)
        self.assertEqual(self.inspect(result['data'])['state'], 'succeeded')
        self.assertFalse(self.worker.once())

    def test_lost_acceptance_response_and_upload_interruption_reconcile_before_retry(self):
        original = self.platform_server.RequestHandlerClass
        for interrupt in (False, True):
            with self.subTest(interrupt=interrupt):
                committed, release = threading.Event(), threading.Event()
                class LostResponse(original):
                    def respond(handler, status, body, *args, **kwargs):
                        if handler.path.startswith('/api/deploy?') and status == 202:
                            committed.set()
                            if interrupt:
                                release.wait(10)
                            return
                        return super().respond(status, body, *args, **kwargs)
                self.platform_server.RequestHandlerClass = LostResponse
                request_id = str(uuid.uuid4())
                process = self.launch('--request-id', request_id)
                try:
                    self.assertTrue(committed.wait(5))
                    if interrupt:
                        process.send_signal(signal.SIGINT)
                    stdout, _ = self.finish(process, 130 if interrupt else 6)
                finally:
                    release.set()
                    self.platform_server.RequestHandlerClass = original
                result = json.loads(stdout)
                self.assertEqual(result['error']['code'], 'INTERRUPTED' if interrupt else 'NETWORK_ERROR')
                details = result['error']['details']
                self.assertEqual(details['request_id'], request_id)
                self.assertTrue(details['outcome_unknown'])
                self.assertNotIn('operation_id', details)
                inspected = self.cli(*shlex.split(details['next_command'])[1:])
                self.assertEqual(inspected.returncode, 0, inspected.stdout)
                operation = json.loads(inspected.stdout)['data']
                self.assertEqual(operation['request_id'], request_id)
                self.assertEqual(operation['state'], 'accepted')
                self.assertTrue(self.worker.once())
                self.assertFalse(self.worker.once())

    def test_authentication_loss_stops_observation_with_context_without_cancelling_work(self):
        process = self.launch()
        self.accepted(process)
        status, raw = self.http('/api/auth/revoke', {}, token=self.token,
                                headers={'X-Request-ID': str(uuid.uuid4())})
        self.assertEqual(status, 200, raw)
        stdout, _ = self.finish(process, 3)
        result = json.loads(stdout)
        self.assertEqual(result['error']['code'], 'CREDENTIAL_REVOKED')
        self.assertTrue(result['error']['details']['work_continues'])
        self.assertIn('--workspace ws-initial', result['error']['details']['next_command'])
        self.assertTrue(self.worker.once())
        self.assertFalse(self.worker.once())

    def test_invalid_wait_options_fail_before_mutation(self):
        for args in (('--timeout', '0'), ('--timeout', '-1'), ('--timeout', '1.5'), ('--wait',)):
            with self.subTest(args=args):
                stdout, _ = self.finish(self.launch(*args), 2)
                self.assertEqual(json.loads(stdout)['error']['code'], 'INVALID_ARGUMENT')
                status = self.cli('app', 'status', 'example')
                self.assertEqual(json.loads(status.stdout)['error']['code'], 'NOT_FOUND')

    def test_slow_success_response_cannot_extend_the_observation_deadline(self):
        request_id = str(uuid.uuid4())
        self.finish(self.launch('--no-wait', '--request-id', request_id))
        self.assertTrue(self.worker.once())
        original = self.platform_server.RequestHandlerClass
        release = threading.Event()
        class SlowResponse(original):
            def respond(handler, status, body, *args, **kwargs):
                if handler.path.startswith('/api/operations/') and status == 200:
                    payload = json.dumps(body).encode()
                    handler.send_response(status)
                    handler.send_header('Content-Length', str(len(payload)))
                    handler.end_headers()
                    for byte in payload:
                        handler.wfile.write(bytes([byte]))
                        if release.wait(.1):
                            break
                    return
                return super().respond(status, body, *args, **kwargs)
        self.platform_server.RequestHandlerClass = SlowResponse
        try:
            process = self.launch('--request-id', request_id, '--timeout', '1')
            self.accepted(process)
            started = time.monotonic()
            stdout, _ = self.finish(process, 6, timeout=3)
            self.assertLess(time.monotonic() - started, 2)
            result = json.loads(stdout)
            self.assertEqual(result['error']['code'], 'WAIT_TIMEOUT')
        finally:
            release.set()
            self.platform_server.RequestHandlerClass = original

    def test_interrupt_during_blocked_initial_progress_retains_accepted_identity(self):
        original = self.platform_server.RequestHandlerClass
        committed, release, sent = threading.Event(), threading.Event(), threading.Event()
        class DelayedAcceptance(original):
            def respond(handler, status, body, *args, **kwargs):
                if handler.path.startswith('/api/deploy?') and status == 202:
                    committed.set()
                    release.wait(5)
                    super().respond(status, body, *args, **kwargs)
                    sent.set()
                    return
                return super().respond(status, body, *args, **kwargs)
        self.platform_server.RequestHandlerClass = DelayedAcceptance
        read_fd, write_fd = os.pipe()
        try:
            with subprocess.Popen([*identity_fixture.cli_command(), '--json', 'app', 'deploy', str(self.source),
                    '--name', 'example', '--description', 'Fixture app'], cwd=identity_fixture.ROOT,
                    env=self.env, stdout=subprocess.PIPE, stderr=write_fd) as process:
                try:
                    self.assertTrue(committed.wait(5))
                    os.set_blocking(write_fd, False)
                    for chunk in (b'x' * 4096, b'x'):
                        try:
                            while True:
                                os.write(write_fd, chunk)
                        except BlockingIOError:
                            pass
                    os.set_blocking(write_fd, True)
                    release.set()
                    self.assertTrue(sent.wait(5))
                    time.sleep(.2)
                    process.send_signal(signal.SIGINT)
                    time.sleep(.05)
                    os.read(read_fd, 65536)
                    process.wait(timeout=2)
                    stdout, _ = process.communicate()
                    self.assertEqual(process.returncode, 130, stdout)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()
            details = json.loads(stdout)['error']['details']
            self.assertTrue(details['work_continues'])
            self.assertEqual(self.inspect(details)['state'], 'accepted')
        finally:
            release.set()
            self.platform_server.RequestHandlerClass = original
            os.close(write_fd)
            os.close(read_fd)
