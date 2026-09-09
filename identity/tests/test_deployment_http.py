"""Publishing acceptance through authenticated HTTP requests."""
import io
import json
import tarfile
import unittest
import urllib.error
import urllib.request
import uuid

from identity.tests import test_identity_cli as identity_fixture


class DeploymentAcceptance(unittest.TestCase):
    setUp = identity_fixture.IdentityAcceptance.setUp
    operator = identity_fixture.IdentityAcceptance.operator
    start_platform = identity_fixture.IdentityAcceptance.start_platform
    http = identity_fixture.IdentityAcceptance.http
    approve = identity_fixture.IdentityAcceptance.approve
    http_login = identity_fixture.IdentityAcceptance.http_login
    cli = identity_fixture.IdentityAcceptance.cli
    login = identity_fixture.IdentityAcceptance.login

    def test_wait_reports_progress_on_stderr_and_preserves_json_stdout(self):
        self.creator()
        self.login()
        source = self.home / 'source'
        source.mkdir()
        (source / 'Dockerfile').write_text('FROM scratch\n')
        result = self.cli('deploy', str(source), '--name', 'progress', '--description', '',
                          '--wait', '--timeout', '1')
        self.assertEqual(result.returncode, 6, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'WAIT_TIMEOUT')
        self.assertIn('Uploading validated source', result.stderr)
        self.assertIn('Deployment: accepted', result.stderr)

    def creator(self):
        self.operator('bootstrap', 'admin@example.test')
        self.start_platform()
        login = self.http_login('admin@example.test')
        self.token = login['credential']
        status, body = self.http('/api/admin/creator/grant', {'user_id': login['user']['id']},
            token=self.token, headers={'X-Request-ID': str(uuid.uuid4())})
        self.assertEqual(status, 200, body)

    def deploy(self, name='example', description='', request_id=None, token=None, raw_archive=None):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w') as output:
            entry = tarfile.TarInfo('Dockerfile')
            content = b'FROM scratch\n'
            entry.size = len(content)
            output.addfile(entry, io.BytesIO(content))
        request = urllib.request.Request(self.endpoint + '/api/deploy?' +
            __import__('urllib.parse', fromlist=['urlencode']).urlencode({'name': name, 'description': description}),
            data=archive.getvalue() if raw_archive is None else raw_archive, headers={'Content-Type': 'application/x-tar',
                'Authorization': 'Bearer ' + (token or self.token), 'X-Request-ID': request_id or str(uuid.uuid4())})
        try:
            response = urllib.request.urlopen(request, context=self.client_tls, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read())

    def test_acceptance_is_durable_and_replay_preserves_operation(self):
        self.creator()
        request_id = str(uuid.uuid4())
        status, accepted = self.deploy(request_id=request_id)
        self.assertEqual(status, 202, accepted)
        data = accepted['data']
        self.assertEqual(data['state'], 'accepted')
        self.assertIsNone(data['active_deployment_id'])
        self.assertEqual(self.deploy(request_id=request_id)[1], accepted)
        status, raw = self.http('/api/operations?request_id=' + request_id, token=self.token)
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)['data']['operation_id'], data['operation_id'])
        status, conflict = self.deploy(description='changed', request_id=request_id)
        self.assertEqual(status, 409, conflict)
        self.assertEqual(conflict['error']['code'], 'REQUEST_CONFLICT')

    def test_member_and_other_creator_cannot_manage_apps(self):
        self.creator()
        _, accepted = self.deploy()
        operation = accepted['data']['operation_id']
        self.http('/api/admin/member/add', {'email': 'other@example.test'}, token=self.token,
                  headers={'X-Request-ID': str(uuid.uuid4())})
        other = self.http_login('other@example.test')
        status, result = self.deploy(name='other', token=other['credential'])
        self.assertEqual(status, 403, result)
        for path in ['/api/apps/example', '/api/operations/' + operation, '/api/apps/example/logs?source=build']:
            status, raw = self.http(path, token=other['credential'])
            self.assertEqual(status, 404, raw)
        self.http('/api/admin/creator/grant', {'user_id': other['user']['id']}, token=self.token,
                  headers={'X-Request-ID': str(uuid.uuid4())})
        status, result = self.deploy(token=other['credential'])
        self.assertEqual(status, 404, result)

    def test_worker_readiness_and_failed_update_preserve_stable_selected_release(self):
        # External infrastructure is controlled here; live EU isolation is separate evidence.
        from identity.common import Failure
        from identity.worker import State, Worker

        class InfrastructureFixture:
            fail = False
            def build(self, operation, logs):
                logs.feed(b'fixture build completed\n')
                return {'archive': 'fixture-archive'}
            def build_accounting(self, operation):
                return {'terminated': True, 'duration_seconds': 1}
            def start(self, operation, artifact, app, register):
                return {'host': '127.0.0.1', 'port': 18080, 'container': 'fixture-container'}
            def ready(self, target):
                if self.fail:
                    raise Failure('STARTUP_FAILED', 'Fixture readiness refused.', 500)
            def promote(self, operation, app, target):
                return target['container']
            def cleanup(self, operation, app, succeeded=False):
                pass

        self.creator()
        infrastructure = InfrastructureFixture()
        worker = Worker(State(self.home / 'server' / 'identity.sqlite3'), infrastructure)
        _, first = self.deploy()
        worker.once()
        _, raw = self.http('/api/apps/example', token=self.token)
        selected = json.loads(raw)['data']
        self.assertEqual(selected['availability'], 'running')
        self.assertEqual(selected['active_deployment_id'], first['data']['operation_id'])
        _, raw = self.http('/api/apps/example/logs?source=build', token=self.token)
        self.assertEqual(json.loads(raw)['data']['entries'][0]['message'], 'fixture build completed')
        infrastructure.fail = True
        _, update = self.deploy(description='updated')
        worker.once()
        _, raw = self.http('/api/apps/example', token=self.token)
        after = json.loads(raw)['data']
        self.assertEqual(after['url'], selected['url'])
        self.assertEqual(after['active_deployment_id'], selected['active_deployment_id'])
        self.assertEqual(after['latest_operation']['state'], 'failed')
        self.assertEqual(after['latest_operation']['error']['code'], 'STARTUP_FAILED')
        self.assertNotEqual(after['latest_operation']['id'], first['data']['operation_id'])
        self.assertEqual(after['latest_operation']['id'], update['data']['operation_id'])

    def test_server_independently_refuses_unsafe_archive_without_reserving_name(self):
        self.creator()
        for path, kind in [('../outside', tarfile.REGTYPE), ('.env', tarfile.REGTYPE),
                           ('linked', tarfile.SYMTYPE), ('.config/small-cloud/config.json', tarfile.REGTYPE)]:
            with self.subTest(path=path):
                archive = io.BytesIO()
                with tarfile.open(fileobj=archive, mode='w') as output:
                    for name in ['Dockerfile', path]:
                        entry = tarfile.TarInfo(name)
                        entry.type = tarfile.REGTYPE if name == 'Dockerfile' else kind
                        entry.size = 0
                        if entry.type == tarfile.SYMTYPE:
                            entry.linkname = 'Dockerfile'
                        output.addfile(entry, io.BytesIO())
                status, result = self.deploy(raw_archive=archive.getvalue())
                self.assertEqual(status, 400, result)
                self.assertEqual(result['error']['code'], 'UPLOAD_REJECTED')
                status, raw = self.http('/api/apps/example', token=self.token)
                self.assertEqual(status, 404, raw)
        self.assertEqual(self.deploy()[0], 202)

    def test_worker_loss_retains_creator_lock_without_replaying_build(self):
        from identity.worker import State, Worker

        class LostInfrastructure:
            def build(self, operation, logs):
                raise KeyboardInterrupt()

        self.creator()
        _, accepted = self.deploy()
        state = State(self.home / 'server' / 'identity.sqlite3')
        worker = Worker(state, LostInfrastructure())
        with self.assertRaises(KeyboardInterrupt):
            worker.once()
        worker.recover()
        _, raw = self.http('/api/operations/' + accepted['data']['operation_id'], token=self.token)
        result = json.loads(raw)['data']
        self.assertEqual(result['state'], 'building')
        self.assertTrue(result['error']['details']['reconciliation_required'])
        self.assertEqual(self.deploy()[1]['error']['code'], 'OPERATION_CONFLICT')
        self.assertFalse(worker.once())

    def test_imported_image_normalization_does_not_break_deployment(self):
        import hashlib
        from pathlib import Path
        import shlex
        import subprocess
        from unittest.mock import patch
        from identity.worker import Infrastructure, State, Worker
        from identity.lifecycle import LifecycleWorker

        self.creator()
        archive = self.home / 'exported-image.tar'
        with tarfile.open(archive, 'w') as output:
            configuration = b'{"architecture":"amd64","os":"linux"}'
            exported_id = hashlib.sha256(configuration).hexdigest()
            for name, content in [(exported_id + '.json', configuration), ('manifest.json',
                    json.dumps([{'Config': exported_id + '.json', 'RepoTags': ['sc-artifact:build'], 'Layers': []}]).encode())]:
                entry = tarfile.TarInfo(name)
                entry.size = len(content)
                output.addfile(entry, io.BytesIO(content))
        archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        imported_id = 'sha256:' + 'a' * 64

        class InfrastructureFixture(Infrastructure):
            def build(self, operation, logs):
                return {'archive': str(archive), 'sha256': archive_digest}
            def build_accounting(self, operation):
                return {'terminated': True, 'duration_seconds': 1}
            def ready(self, target):
                pass

        def external_process(arguments, **kwargs):
            args = list(arguments)
            output = b''
            if args[0] == 'ssh':
                args = shlex.split(args[-1])
                if args[0] == 'sha256sum':
                    output = (archive_digest + '  image.tar').encode()
                elif args[:2] == ['docker', 'load']:
                    output = b'Loaded image: sc-artifact:build\n'
                elif args[:3] == ['docker', 'image', 'inspect']:
                    if args[3] not in ('sc-artifact:build', imported_id):
                        return subprocess.CompletedProcess(arguments, 1, b'')
                    output = json.dumps([{'Id': imported_id, 'Architecture': 'amd64', 'Os': 'linux'}]).encode()
                elif args[:2] == ['python3', '/opt/small-cloud/runtime/sandbox.py']:
                    if args[4] in ('start', 'resume'):
                        output = json.dumps({'container': 'fixture-container', 'private_port': 18080}).encode()
                elif args[:3] == ['docker', 'ps', '-aq']:
                    output = b''
            elif args[0] == 'python3' and args[1].endswith('tool_database.py'):
                output = b'{"encrypted_credentials":"/protected/fixture.age"}'
            elif args[0] == 'age':
                output = b'{"database_url":"postgresql://fixture:confidential@example.invalid/db","password":"confidential"}'
            elif Path(args[0]).name == 'python' and len(args) > 1 and args[1].endswith('releases.py'):
                output = b'{}'
            return subprocess.CompletedProcess(arguments, 0, output)

        worker = Worker(State(self.home / 'server' / 'identity.sqlite3'),
                        InfrastructureFixture({'admin_cidr': '203.0.113.1/32'}))
        _, accepted = self.deploy()
        with patch('identity.worker.subprocess.run', side_effect=external_process):
            worker.once()
        _, raw = self.http('/api/operations/' + accepted['data']['operation_id'], token=self.token)
        self.assertEqual(json.loads(raw)['data']['state'], 'succeeded', raw)
        self.assertNotIn('confidential', raw)
        _, raw = self.http('/api/apps/example', token=self.token)
        app = json.loads(raw)['data']
        now = [__import__('time').time() + 1800]
        self.platform_server.application.publishing.clock = lambda: now[0]
        lifecycle = LifecycleWorker(worker.state, worker.infrastructure, clock=lambda: now[0], registry=worker.registry)
        with patch('identity.worker.subprocess.run', side_effect=external_process):
            lifecycle.once()
            _, raw = self.http('/api/apps/example', token=self.token)
            self.assertEqual(json.loads(raw)['data']['availability'], 'stopped')
            status, raw = self.http('/', token=self.token, headers={'Host': __import__('urllib.parse', fromlist=['urlsplit']).urlsplit(app['url']).netloc})
            self.assertEqual(status, 503, raw)
            lifecycle.once()
        _, raw = self.http('/api/apps/example', token=self.token)
        self.assertEqual(json.loads(raw)['data']['availability'], 'running', raw)
        self.assertEqual(json.loads(raw)['data']['active_deployment_id'], app['active_deployment_id'])
        self.assertNotIn('confidential', raw)
