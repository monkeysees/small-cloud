"""Publishing limits through authenticated HTTP/CLI and worker execution."""
import json
import subprocess
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import patch

from identity.tests import test_deployment_http as deployment_fixture
from identity.tests import test_identity_cli as identity_fixture
from identity.common import Failure
from identity.worker import Infrastructure, State, Worker


class BuildFixture:
    duration = 12.01
    terminated = True
    fail = False

    def build(self, operation):
        if self.fail:
            raise Failure('BUILD_FAILED', 'Fixture build failed.', 500)
        return {'archive': 'fixture'}

    def build_accounting(self, operation):
        return {'terminated': self.terminated, 'duration_seconds': self.duration}

    def start(self, operation, artifact, app):
        return {'host': '127.0.0.1', 'port': 18080, 'container': 'fixture'}

    def ready(self, target):
        pass

    def promote(self, operation, app, target):
        return target['container']

    def cleanup(self, operation, app, succeeded=False):
        pass

    def build_log(self, operation):
        return 'fixture build', 0


class LimitsAcceptance(unittest.TestCase):
    setUp = deployment_fixture.DeploymentAcceptance.setUp
    operator = deployment_fixture.DeploymentAcceptance.operator
    start_platform = deployment_fixture.DeploymentAcceptance.start_platform
    restart_platform = identity_fixture.IdentityAcceptance.restart_platform
    http = deployment_fixture.DeploymentAcceptance.http
    approve = deployment_fixture.DeploymentAcceptance.approve
    http_login = deployment_fixture.DeploymentAcceptance.http_login
    cli = deployment_fixture.DeploymentAcceptance.cli
    login = deployment_fixture.DeploymentAcceptance.login
    creator = deployment_fixture.DeploymentAcceptance.creator
    deploy = deployment_fixture.DeploymentAcceptance.deploy

    def worker(self, infrastructure=None):
        return Worker(State(self.home / 'server' / 'identity.sqlite3'), infrastructure or BuildFixture())

    def admit_creator(self, email):
        self.http('/api/admin/member/add', {'email': email}, token=self.token,
                  headers={'X-Request-ID': str(uuid.uuid4())})
        member = self.http_login(email)
        status, raw = self.http('/api/admin/creator/grant', {'user_id': member['user']['id']}, token=self.token,
                                headers={'X-Request-ID': str(uuid.uuid4())})
        self.assertEqual(status, 200, raw)
        return member['credential']

    def usage(self, token=None):
        status, raw = self.http('/api/usage', token=token or self.token)
        self.assertEqual(status, 200, raw)
        return json.loads(raw)['data']

    def test_usage_reports_capacity_and_reserves_once_through_cli_and_http(self):
        self.creator()
        self.login()
        result = self.cli('usage')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        usage = json.loads(result.stdout)['data']
        self.assertEqual(usage['creators'], {'used': 1, 'limit': 5})
        self.assertEqual(usage['deployed_apps'], {'used': 0, 'limit': 30})
        self.assertEqual(usage['active_apps'], {'used': 0, 'limit': 5})
        self.assertEqual(usage['build']['limit_seconds'], 60000)
        self.assertEqual(usage['build']['charged_seconds'], 0)
        self.assertEqual(usage['build']['available_seconds'], 60000)
        request_id = str(uuid.uuid4())
        self.assertEqual(self.deploy(request_id=request_id)[0], 202)
        self.assertEqual(self.deploy(request_id=request_id)[0], 202)
        usage = self.usage()
        self.assertEqual(usage['deployed_apps']['used'], 1)
        self.assertEqual(usage['active_apps']['used'], 0)
        self.assertEqual(usage['build']['reserved_seconds'], 600)
        self.assertEqual(usage['build']['available_seconds'], 59400)
        self.restart_platform()
        self.assertEqual(self.usage(), usage)

    def test_confirmed_builds_charge_rounded_execution_and_release_unused_reservation(self):
        self.creator()
        infrastructure = BuildFixture()
        worker = self.worker(infrastructure)
        _, accepted = self.deploy()
        self.assertTrue(worker.once())
        self.assertEqual(self.usage()['build']['charged_seconds'], 13)
        self.assertEqual(self.usage()['build']['reserved_seconds'], 0)
        self.assertEqual(self.usage()['active_apps']['used'], 1)
        infrastructure.duration = 20
        infrastructure.fail = True
        self.assertEqual(self.deploy()[0], 202)
        worker.once()
        self.assertEqual(self.usage()['build']['charged_seconds'], 33)
        self.assertEqual(self.usage()['build']['available_seconds'], 59967)
        self.assertFalse(worker.once())
        _, raw = self.http('/api/apps/example', token=self.token)
        self.assertEqual(json.loads(raw)['data']['active_deployment_id'], accepted['data']['operation_id'])

    def test_uncertain_termination_retains_reservation_and_lock_after_restart(self):
        self.creator()
        infrastructure = BuildFixture()
        infrastructure.terminated = False
        worker = self.worker(infrastructure)
        _, accepted = self.deploy()
        worker.once()
        worker.recover()
        self.assertFalse(worker.once())
        self.assertEqual(self.usage()['build']['reserved_seconds'], 600)
        self.assertEqual(self.usage()['build']['charged_seconds'], 0)
        self.assertEqual(self.usage()['active_apps']['used'], 0)
        self.assertEqual(self.deploy(name='another')[1]['error']['code'], 'BUILD_BUSY')
        _, raw = self.http('/api/operations/' + accepted['data']['operation_id'], token=self.token)
        self.assertTrue(json.loads(raw)['data']['error']['details']['reconciliation_required'])

    def test_unstarted_build_is_free_and_timeout_charge_is_capped(self):
        self.creator()
        infrastructure = BuildFixture()
        infrastructure.fail = True
        infrastructure.duration = 0
        worker = self.worker(infrastructure)
        self.deploy()
        worker.once()
        self.assertEqual(self.usage()['build']['available_seconds'], 60000)
        infrastructure.duration = 600.01
        self.deploy()
        worker.once()
        self.assertEqual(self.usage()['build']['charged_seconds'], 600)
        self.assertEqual(self.usage()['build']['reserved_seconds'], 0)

    def test_worker_requires_trusted_termination_receipt_even_with_successful_artifact(self):
        self.creator()

        class ReceiptInfrastructure(BuildFixture, Infrastructure):
            build_accounting = Infrastructure.build_accounting

        infrastructure = ReceiptInfrastructure({'admin_cidr': '203.0.113.1/32'})
        infrastructure.staging = self.home / 'staging'
        _, accepted = self.deploy()
        output = infrastructure.staging / accepted['data']['operation_id']
        output.mkdir(parents=True)
        (output / 'accounting.json').write_text(json.dumps({'terminated': True, 'duration_seconds': 7.1}))
        (output / 'teardown.json').write_text('{"deleted": false}')
        self.worker(infrastructure).once()
        self.assertEqual(self.usage()['build']['reserved_seconds'], 600)
        _, raw = self.http('/api/apps/example', token=self.token)
        self.assertEqual(json.loads(raw)['data']['availability'], 'unavailable')

    def test_competing_builds_exhaustion_and_new_year_keep_serving_apps(self):
        self.creator()
        publishing = self.platform_server.application.publishing
        december = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp()
        publishing.clock = lambda: december
        infrastructure = BuildFixture()
        infrastructure.duration = 600
        worker = self.worker(infrastructure)
        # Exercise the full ledger through admission and execution, without SQL seeding.
        for _ in range(99):
            self.assertEqual(self.deploy()[0], 202)
            worker.once()
        self.assertEqual(self.usage()['build']['charged_seconds'], 59400)
        other_token = self.admit_creator('other@example.test')
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda item: self.deploy(name=item[0], token=item[1]),
                                   [('first', self.token), ('second', other_token)]))
        self.assertEqual(sorted(status for status, _ in results), [202, 409])
        refused = next(body for status, body in results if status == 409)
        self.assertEqual(refused['error']['code'], 'ALLOWANCE_RESERVED')
        self.assertEqual(self.usage()['deployed_apps']['used'], 2)
        self.assertEqual(self.usage()['build']['reserved_seconds'], 600)
        # The new month's ledger is independent, but the unfinished creator lock survives.
        publishing.clock = lambda: december + 1
        january = self.usage()['build']
        self.assertEqual(january['period_start'], '2027-01-01T00:00:00Z')
        self.assertEqual(january['period_end'], '2027-02-01T00:00:00Z')
        self.assertEqual(january['available_seconds'], 60000)
        winner_token = self.token if results[0][0] == 202 else other_token
        self.assertEqual(self.deploy(name='third', token=winner_token)[1]['error']['code'], 'BUILD_BUSY')
        worker.once()
        self.assertEqual(self.usage()['build']['charged_seconds'], 0)
        publishing.clock = lambda: december
        self.assertEqual(self.usage()['build']['charged_seconds'], 60000)
        self.assertEqual(self.deploy(name='exhausted')[1]['error']['code'], 'ALLOWANCE_EXHAUSTED')
        self.assertEqual(self.usage()['deployed_apps']['used'], 2)
        _, raw = self.http('/api/apps/example', token=self.token)
        self.assertEqual(json.loads(raw)['data']['availability'], 'running')
        publishing.clock = lambda: december + 1
        self.assertEqual(self.deploy(name='next-month')[0], 202)

    def test_usage_denies_members_and_accepts_administrators_without_creator_grant(self):
        self.operator('bootstrap', 'admin@example.test')
        self.start_platform()
        administrator = self.http_login('admin@example.test')
        self.token = administrator['credential']
        self.assertEqual(self.usage()['creators']['used'], 0)
        self.http('/api/admin/member/add', {'email': 'member@example.test'}, token=self.token,
                  headers={'X-Request-ID': str(uuid.uuid4())})
        member = self.http_login('member@example.test')
        self.assertEqual(self.http('/api/usage', token=member['credential'])[0], 403)
        self.assertEqual(self.http('/api/usage')[0], 401)

    def test_competing_requests_cannot_exceed_deployed_capacity_and_updates_still_work(self):
        self.creator()
        infrastructure = BuildFixture()
        infrastructure.fail = True
        worker = self.worker(infrastructure)
        for index in range(29):
            self.assertEqual(self.deploy(name=f'app-{index}')[0], 202)
            worker.once()
        other_token = self.admit_creator('other@example.test')
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda item: self.deploy(name=item[0], token=item[1]),
                                   [('last-one', self.token), ('last-two', other_token)]))
        self.assertEqual(sorted(status for status, _ in results), [202, 409])
        refused = next(body for status, body in results if status == 409)
        self.assertEqual(refused['error']['code'], 'DEPLOYED_CAPACITY')
        self.assertEqual(self.usage()['deployed_apps'], {'used': 30, 'limit': 30})
        worker.once()
        status, refused = self.deploy(name='overflow')
        self.assertEqual(status, 409)
        self.assertEqual(refused['error']['code'], 'DEPLOYED_CAPACITY')
        self.assertEqual(self.deploy(name='app-0')[0], 202)

    def test_sub_ten_minute_remainder_is_unusable_and_reports_actionable_counts(self):
        self.creator()
        infrastructure = BuildFixture()
        infrastructure.duration = 600
        worker = self.worker(infrastructure)
        for _ in range(99):
            self.deploy()
            worker.once()
        infrastructure.duration = 1
        self.deploy()
        worker.once()
        status, refused = self.deploy()
        self.assertEqual(status, 409)
        self.assertEqual(refused['error']['code'], 'ALLOWANCE_EXHAUSTED')
        self.assertEqual(refused['error']['details']['charged_seconds'], 59401)
        self.assertEqual(refused['error']['details']['available_seconds'], 599)

    def test_remote_preflight_refusal_releases_proven_unstarted_build(self):
        self.creator()

        class PreflightInfrastructure(BuildFixture, Infrastructure):
            build = Infrastructure.build
            build_accounting = Infrastructure.build_accounting

        infrastructure = PreflightInfrastructure({'admin_cidr': '203.0.113.1/32'})
        infrastructure.staging = self.home / 'staging'
        self.deploy()
        def external_process(arguments, **kwargs):
            if arguments[1].endswith('remote.py'):
                return subprocess.CompletedProcess(arguments, 7, b'{"error":{"code":"BUILD_NOT_STARTED"}}')
            return subprocess.CompletedProcess(arguments, 0, b'{}')
        with patch('identity.worker.subprocess.run', side_effect=external_process):
            self.worker(infrastructure).once()
        self.assertEqual(self.usage()['build']['available_seconds'], 60000)
        self.assertEqual(self.deploy()[0], 202)
