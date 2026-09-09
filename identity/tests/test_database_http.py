"""Real PostgreSQL acceptance through creator CLI and authenticated app HTTP.

Docker replaces the EU infrastructure boundary; identity, publishing, provisioning,
starter initialization and database authorization run their real implementations.
"""
import http.client
import json
import os
from pathlib import Path
import socket
import shutil
import sqlite3
import subprocess
import sys
import time
import unittest
import uuid
import urllib.parse

from identity.tests import test_deployment_http as deployment_fixture
from identity.tests import test_identity_cli as identity_fixture
from identity.common import Failure
from identity.worker import State, Worker

ROOT = Path(__file__).resolve().parents[2]


def command(*args, data=None):
    result = subprocess.run(args, input=data, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError('Acceptance infrastructure command failed: ' + args[0])
    return result.stdout


class DatabaseAcceptance(unittest.TestCase):
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

    @classmethod
    def setUpClass(cls):
        command('docker', 'build', '-q', '-t', 'small-cloud-database-acceptance',
                '-f', str(ROOT / 'identity/tests/database.Dockerfile'), str(ROOT))
        cls.database = command('docker', 'run', '-d', '--rm', '-p', '127.0.0.1::5432',
                               '-e', 'POSTGRES_PASSWORD=fixture-admin',
                               'small-cloud-database-acceptance').decode().strip()
        cls.addClassCleanup(command, 'docker', 'rm', '-f', '-v', cls.database)
        for _ in range(60):
            result = subprocess.run(['docker', 'exec', cls.database, 'pg_isready', '-U', 'postgres'],
                                    capture_output=True)
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('PostgreSQL did not start')
        cls.database_port = command('docker', 'port', cls.database, '5432').decode().strip().split(':')[-1]
        command('docker', 'exec', cls.database, 'sh', '-c',
                'mkdir -p /srv/small-cloud/secrets && chmod 700 /srv/small-cloud/secrets && '
                'age-keygen -o /srv/small-cloud/secrets/identity.age')
        command('docker', 'exec', '-i', cls.database, 'psql', '-U', 'postgres', '-v', 'ON_ERROR_STOP=1',
                data=b'REVOKE ALL ON DATABASE postgres, template1 FROM PUBLIC;')

    def prepare(self, build_source=False):
        self.creator()
        self.login()
        acceptance = self
        self.runtimes = {}
        self.database_names = {}
        containers = set()

        class LocalInfrastructure:
            def build(self, operation, logs):
                if build_source:
                    image = 'small-cloud-acceptance:' + operation['id']
                    result = subprocess.run(['docker', 'build', '-q', '-t', image, '-'],
                        input=bytes(operation['source']), capture_output=True, timeout=180)
                    logs.feed(result.stdout + result.stderr)
                    if result.returncode:
                        raise Failure('BUILD_FAILED', 'Dockerfile build failed; inspect build logs.', 500)
                    acceptance.addCleanup(command, 'docker', 'image', 'rm', '-f', image)
                    return {'image': image}
                return {}

            def build_accounting(self, operation):
                return {'terminated': True, 'duration_seconds': 1}

            def start(self, operation, artifact, app, register):
                provisioned = json.loads(command('docker', 'exec', acceptance.database, 'python3',
                    '/usr/local/bin/app-database.py', operation['app_id']))
                saved = json.loads(command('docker', 'exec', acceptance.database, 'age', '--decrypt',
                    '-i', '/srv/small-cloud/secrets/identity.age', provisioned['encrypted_credentials']))
                acceptance.database_names[operation['app_id']] = saved['database']
                # Only transport differs locally: the production URL pins the private TLS CA.
                url = (f"postgresql://{saved['user']}:{saved['password']}@127.0.0.1:"
                       f"{acceptance.database_port}/{saved['database']}?sslmode=disable")
                with socket.socket() as listener:
                    listener.bind(('127.0.0.1', 0))
                    port = listener.getsockname()[1]
                env = {**os.environ, **app.get('runtime_environment', {}), 'DATABASE_URL': url, 'PORT': str(port)}
                if build_source:
                    name = operation['id']
                    result = subprocess.run(['docker', 'run', '-d', '--network', 'host', '--name', name,
                        '-e', 'DATABASE_URL', '-e', 'PORT', artifact['image']],
                        env=env, capture_output=True, timeout=30)
                    acceptance.addCleanup(command, 'docker', 'rm', '-f', name)
                    containers.add(name)
                    if result.returncode:
                        raise Failure('STARTUP_FAILED', 'Acceptance container could not start.', 500)
                    return {'host': '127.0.0.1', 'port': port, 'container': name}
                process = subprocess.Popen([sys.executable, str(ROOT / 'identity/fixture/app.py')],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                acceptance.addCleanup(acceptance.stop, process)
                acceptance.runtimes[operation['app_id']] = (process, env)
                return {'host': '127.0.0.1', 'port': port, 'container': operation['id']}

            def ready(self, target):
                try:
                    acceptance.wait_ready(target['port'])
                except RuntimeError:
                    raise Failure('STARTUP_FAILED', 'App did not answer HTTP readiness with HTTP 200.', 500) from None

            def promote(self, operation, app, target):
                return target['container']

            def stop(self, app):
                process, _ = acceptance.runtimes[app['id']]
                acceptance.stop(process)

            def wake(self, app, register):
                return self.start({'id': app['active_deployment_id'], 'app_id': app['id']}, {}, app, register)

            def cleanup(self, operation, app, succeeded=False):
                if build_source:
                    name = app['container'] if succeeded else operation['id']
                    if name in containers:
                        command('docker', 'stop', '-t', '1', name)


        self.worker = Worker(State(self.home / 'server/identity.sqlite3'), LocalInfrastructure())

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)

    @staticmethod
    def wait_ready(port):
        for _ in range(100):
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
            try:
                connection.request('GET', '/_small-cloud/ready')
                if connection.getresponse().status == 200:
                    return
            except OSError:
                pass
            finally:
                connection.close()
            time.sleep(.05)
        raise RuntimeError('Starter did not become ready')

    def publish(self, name):
        result = self.cli('app', 'deploy', str(ROOT / 'identity/fixture'), '--name', name, '--description', 'Disposable test')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.worker.once()
        result = self.cli('app', 'status', name)
        self.assertEqual(result.returncode, 0, result.stdout)
        app = json.loads(result.stdout)['data']
        self.assertEqual(app['availability'], 'running', app)
        return app

    def app_request(self, app, path='/', body=None, token=True, headers=None):
        return self.http(path, body, token=self.token if token else None,
                         headers={'Host': urllib.parse.urlsplit(app['url']).netloc, **(headers or {})})

    def source(self, version):
        source = self.home / version
        shutil.copytree(ROOT / 'identity/fixture', source)
        path = source / 'app.py'
        path.write_text(path.read_text().replace("'small-cloud-publishing'", repr(version)))
        return source

    def deploy_source(self, name, source):
        result = self.cli('app', 'deploy', str(source), '--name', name, '--description', 'Redeployment acceptance')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.worker.once()
        result = self.cli('app', 'status', name)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)['data']

    def test_updates_preserve_url_sharing_and_data_in_both_scopes(self):
        self.prepare(build_source=True)
        app = self.deploy_source('updates', self.source('release-one'))
        self.assertEqual(json.loads(self.app_request(app)[1])['fixture'], 'release-one')
        self.assertEqual(self.app_request(app, '/data', {'value': 'Retained across updates'})[0], 201)
        entries = json.loads(self.app_request(app, '/data')[1])['entries']
        owner_token = self.token
        self.http('/api/admin/member/add', {'email': 'reader@example.test'}, token=owner_token,
                  headers={'X-Request-ID': str(uuid.uuid4())})
        member_token = self.http_login('reader@example.test')['credential']
        for scope, version in [('creator-only', 'release-two'), ('workspace-wide', 'release-three')]:
            with self.subTest(scope=scope):
                self.assertEqual(self.cli('app', 'share', 'updates', '--scope', scope).returncode, 0)
                updated = self.deploy_source('updates', self.source(version))
                self.assertEqual(updated['latest_operation']['state'], 'succeeded', updated)
                self.assertNotEqual(updated['active_deployment_id'], app['active_deployment_id'])
                self.assertEqual(updated['url'], app['url'])
                self.assertEqual(updated['sharing_scope'], scope)
                self.assertEqual(json.loads(self.app_request(updated)[1])['fixture'], version)
                self.assertEqual(json.loads(self.app_request(updated, '/data')[1])['entries'], entries)
                self.token = member_token
                self.assertEqual(self.app_request(updated, '/data')[0],
                                 404 if scope == 'creator-only' else 200)
                self.token = owner_token
                app = updated

    def test_build_and_startup_failures_keep_the_previous_release_and_data(self):
        self.prepare(build_source=True)
        app = self.deploy_source('failures', self.source('working-release'))
        self.assertEqual(self.app_request(app, '/data', {'value': 'Survives failed updates'})[0], 201)
        entries = json.loads(self.app_request(app, '/data')[1])['entries']
        for failure in ('BUILD_FAILED', 'STARTUP_FAILED'):
            with self.subTest(failure=failure):
                source = self.source(failure.lower())
                if failure == 'BUILD_FAILED':
                    dockerfile = source / 'Dockerfile'
                    dockerfile.write_text(dockerfile.read_text() + '\nRUN false\n')
                else:
                    path = source / 'app.py'
                    path.write_text(path.read_text().replace('        initialize()',
                        "        raise SystemExit('Deliberate startup failure')"))
                failed = self.deploy_source('failures', source)
                self.assertEqual(failed['latest_operation']['state'], 'failed', failed)
                self.assertEqual(failed['latest_operation']['error']['code'], failure)
                self.assertTrue(failed['latest_operation']['error']['message'])
                self.assertEqual(failed['availability'], 'running')
                self.assertEqual(failed['active_deployment_id'], app['active_deployment_id'])
                self.assertEqual(failed['url'], app['url'])
                self.assertEqual(failed['sharing_scope'], app['sharing_scope'])
                self.assertEqual(json.loads(self.app_request(failed)[1])['fixture'], 'working-release')
                self.assertEqual(json.loads(self.app_request(failed, '/data')[1])['entries'], entries)
                result = self.cli('operation', 'status', '--request-id', failed['latest_operation']['request_id'])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)['data']['error']['code'], failure)
        recovered = self.deploy_source('failures', self.source('fixed-release'))
        self.assertEqual(recovered['latest_operation']['state'], 'succeeded', recovered)
        self.assertEqual(json.loads(self.app_request(recovered)[1])['fixture'], 'fixed-release')
        self.assertEqual(json.loads(self.app_request(recovered, '/data')[1])['entries'], entries)

    def test_failed_committed_migration_needs_creator_repair_not_container_rollback(self):
        self.prepare(build_source=True)
        app = self.deploy_source('schema', self.source('old-schema-release'))
        self.assertEqual(self.app_request(app, '/data', {'value': 'Recover through schema repair'})[0], 201)
        entries = json.loads(self.app_request(app, '/data')[1])['entries']
        source = self.source('incompatible-migration')
        path = source / 'app.py'
        path.write_text(path.read_text().replace('        initialize()',
            "        with connect() as database:\n"
            "            database.execute('ALTER TABLE entries RENAME COLUMN value TO incompatible_value')\n"
            "        raise SystemExit('Failed after committing incompatible migration')"))
        failed = self.deploy_source('schema', source)
        self.assertEqual(failed['latest_operation']['state'], 'failed', failed)
        self.assertEqual(failed['latest_operation']['error']['code'], 'STARTUP_FAILED')
        self.assertEqual(failed['active_deployment_id'], app['active_deployment_id'])
        self.assertEqual(json.loads(self.app_request(failed)[1])['fixture'], 'old-schema-release')
        self.assertEqual(self.app_request(failed, '/data')[0], 503)
        self.assertEqual(self.app_request(failed, '/data', {'value': 'Cannot use the changed schema'})[0], 503)

        source = self.source('repaired-schema-release')
        path = source / 'app.py'
        path.write_text(path.read_text().replace('        initialize()',
            "        with connect() as database:\n"
            "            database.execute('ALTER TABLE entries RENAME COLUMN incompatible_value TO value')\n"
            "        initialize()"))
        repaired = self.deploy_source('schema', source)
        self.assertEqual(repaired['latest_operation']['state'], 'succeeded', repaired)
        self.assertEqual(repaired['url'], app['url'])
        self.assertEqual(json.loads(self.app_request(repaired)[1])['fixture'], 'repaired-schema-release')
        self.assertEqual(json.loads(self.app_request(repaired, '/data')[1])['entries'], entries)

    def test_shared_members_read_and_modify_the_same_app_database(self):
        self.prepare()
        app = self.publish('shared')
        owner_token = self.token
        self.assertEqual(self.app_request(app, '/data', {'value': 'Owner entry'})[0], 201)
        self.http('/api/admin/member/add', {'email': 'member@example.test'}, token=owner_token,
                  headers={'X-Request-ID': str(uuid.uuid4())})
        member = self.http_login('member@example.test')['credential']
        self.token = member
        self.assertEqual(self.app_request(app, '/data')[0], 404)
        result = self.cli('app', 'share', 'shared', '--scope', 'workspace-wide')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        status, raw = self.app_request(app, '/data')
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)['entries'][0]['value'], 'Owner entry')
        self.assertEqual(self.app_request(app, '/data', {'value': 'Member contribution'})[0], 201)
        # Follow the app's real browser sign-in while mapping its hostname to local TLS.
        def browser_get(path, cookie='', app_host=True):
            platform = urllib.parse.urlsplit(self.endpoint)
            connection = http.client.HTTPSConnection(platform.hostname, platform.port, context=self.client_tls)
            try:
                connection.request('GET', path, headers={
                    'Host': urllib.parse.urlsplit(app['url']).netloc if app_host else platform.netloc,
                    'Accept': 'text/html', 'Cookie': cookie})
                response = connection.getresponse()
                return response.status, response.read(), dict(response.getheaders())
            finally:
                connection.close()

        status, _, headers = browser_get('/data')
        self.assertEqual(status, 302)
        flow_cookie = headers['Set-Cookie'].split(';')[0]
        provider = urllib.parse.urlsplit(headers['Location'])
        connection = http.client.HTTPSConnection(provider.hostname, provider.port, context=self.client_tls)
        try:
            connection.request('GET', provider.path + '?' + provider.query)
            response = connection.getresponse()
            response.read()
            callback = urllib.parse.urlsplit(response.getheader('Location'))
        finally:
            connection.close()
        status, _, headers = browser_get(callback.path + '?' + callback.query, app_host=False)
        self.assertEqual(status, 302)
        finish = urllib.parse.urlsplit(headers['Location'])
        status, _, headers = browser_get(finish.path + '?' + finish.query, flow_cookie)
        self.assertEqual(status, 302)
        app_cookie = headers['Set-Cookie'].split(';')[0]
        self.assertEqual(browser_get('/data', app_cookie)[0], 200)
        self.token = owner_token
        entries = json.loads(self.app_request(app, '/data')[1])['entries']
        self.assertEqual([entry['value'] for entry in entries], ['Owner entry', 'Member contribution'])
        result = self.cli('app', 'share', 'shared', '--scope', 'creator-only')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(browser_get('/data', app_cookie)[0], 404)
        self.token = member
        self.assertEqual(self.app_request(app, '/data')[0], 404)
        self.assertEqual(self.app_request(app, '/data', {'value': 'Denied'})[0], 404)
        self.token = owner_token
        self.assertEqual(json.loads(self.app_request(app, '/data')[1])['entries'], entries)

    def test_rows_survive_restart_and_repeated_publication(self):
        self.prepare()
        app = self.publish('persistence')
        value = "A colleague's priority: 東京 </script>; DROP TABLE entries; --"
        status, raw = self.app_request(app, '/data', {'value': value})
        self.assertEqual(status, 201, raw)
        entry = json.loads(raw)
        self.assertEqual(entry['value'], value)
        process, env = self.runtimes[app['app_id']]
        self.stop(process)
        restarted = subprocess.Popen([sys.executable, str(ROOT / 'identity/fixture/app.py')],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop, restarted)
        self.wait_ready(int(env['PORT']))
        status, raw = self.app_request(app, '/data')
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)['entries'], [entry])

        updated = self.publish('persistence')
        self.assertEqual(updated['url'], app['url'])
        status, raw = self.app_request(updated, '/data')
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)['entries'], [entry])

    def test_http_idle_threshold_and_on_demand_start_preserve_database(self):
        from identity.lifecycle import LifecycleWorker

        self.prepare()
        now = [time.time()]
        self.worker.clock = lambda: now[0]
        self.platform_server.application.publishing.clock = lambda: now[0]
        lifecycle = LifecycleWorker(self.worker.state, self.worker.infrastructure, clock=lambda: now[0])
        app = self.publish('idle')
        status, raw = self.app_request(app, '/data', {'value': 'Survives idle stop'})
        self.assertEqual(status, 201, raw)
        entry = json.loads(raw)
        now[0] += 1799
        lifecycle.once()
        self.assertEqual(json.loads(self.cli('app', 'status', 'idle').stdout)['data']['availability'], 'running')
        now[0] += 1
        lifecycle.once()
        self.assertEqual(json.loads(self.cli('app', 'status', 'idle').stdout)['data']['availability'], 'stopped')
        self.assertEqual(self.app_request(app, '/data', token=False)[0], 401)
        status, page = self.app_request(app, '/data', headers={'Accept': 'text/html'})
        self.assertEqual(status, 503, page)
        self.assertIn('Starting', page)
        self.assertEqual(json.loads(self.cli('app', 'status', 'idle').stdout)['data']['availability'], 'starting')
        lifecycle.once()
        status, raw = self.app_request(app, '/data')
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)['entries'], [entry])
        self.assertEqual(json.loads(self.cli('app', 'status', 'idle').stdout)['data']['active_deployment_id'],
                         app['active_deployment_id'])

    def test_legacy_control_migration_preserves_database_cli_and_redeployment(self):
        self.prepare()
        app = self.publish('migrated')
        self.assertEqual(self.app_request(app, '/data', {'value': 'Before workspace migration'})[0], 201)
        self.assertEqual(self.cli('app', 'share', 'migrated', '--scope', 'workspace-wide').returncode, 0)
        self.platform_server.shutdown()
        self.platform_server.server_close()
        # Serialize realistic running state into the frozen pre-workspace schema.
        path = self.home / 'server' / 'identity.sqlite3'
        legacy = self.home / 'legacy.sqlite3'
        with sqlite3.connect(path) as current, sqlite3.connect(legacy) as old:
            current.row_factory = sqlite3.Row
            old.executescript(Path(__file__).with_name('legacy-workspace.sql').read_text())
            for table in ('users', 'credentials', 'browser_sessions', 'logins', 'oauth', 'requests', 'apps', 'deployments'):
                columns = [row[1] for row in old.execute('PRAGMA table_info(' + table + ')')]
                source = 'workspace_users' if table == 'users' else table
                for row in current.execute('SELECT * FROM ' + source):
                    legacy_diagnostics = {'build_log': 'Legacy build output\n', 'dropped_bytes': 0} if table == 'deployments' else {}
                    old.execute('INSERT INTO ' + table + ' VALUES(' + ','.join('?' for _ in columns) + ')',
                                [legacy_diagnostics[column] if column in legacy_diagnostics else row[column] for column in columns])
        legacy.chmod(0o600)
        legacy.replace(path)
        self.restart_platform()
        self.worker.recover()
        logs = self.cli('app', 'logs', 'migrated', '--source', 'build')
        self.assertEqual(logs.returncode, 0, logs.stdout + logs.stderr)
        self.assertEqual(json.loads(logs.stdout)['data']['entries'][0]['message'], 'Legacy build output')
        result = self.cli('auth', 'status')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['data']['default_workspace'], 'ws-initial')
        self.assertEqual(json.loads(self.app_request(app, '/data')[1])['entries'][0]['value'],
                         'Before workspace migration')
        updated = self.publish('migrated')
        self.assertEqual(updated['url'], app['url'])
        self.assertEqual(updated['sharing_scope'], 'workspace-wide')
        self.assertEqual(json.loads(self.app_request(updated, '/data')[1])['entries'][0]['value'],
                         'Before workspace migration')

    def test_other_database_and_role_are_denied_on_the_same_server(self):
        self.prepare()
        first = self.publish('first')
        second = self.publish('second')
        self.assertEqual(self.app_request(second, '/data', {'value': 'Only the second app'})[0], 201)
        for app, other in ((first, second), (second, first)):
            database = self.database_names[other['app_id']]
            status, raw = self.app_request(app, '/database/isolation?database=' + database)
            self.assertEqual(status, 200, raw)
            self.assertEqual(json.loads(raw), {'own_database': 'reachable',
                'other_database': 'denied', 'other_role': 'denied',
                'maintenance_database': 'denied'})
        self.assertEqual(json.loads(self.app_request(first, '/data')[1])['entries'], [])

    def test_notice_input_validation_and_authentication(self):
        self.prepare()
        app = self.publish('notice')
        status, page = self.app_request(app, headers={'Accept': 'text/html'})
        self.assertEqual(status, 200, page)
        self.assertIn('Data is disposable', page)
        self.assertIn('No backup or recovery guarantee', page)
        for body in ({'value': ''}, {'value': 'a' * 4097}, {'value': '\x00'}, [], {'value': 42}):
            status, raw = self.app_request(app, '/data', body)
            self.assertEqual(status, 400, raw)
        for path, body in (('/data', None), ('/data', {'value': 'unauthenticated'}),
                           ('/database/isolation?database=tool_' + 'a' * 24, None)):
            self.assertEqual(self.app_request(app, path, body, token=False)[0], 401)
        self.assertEqual(self.app_request(app, '/database/isolation?database=postgresql://evil.invalid/db')[0], 400)
        self.assertEqual(self.app_request(app, '/_small-cloud/ready')[0], 404)
        self.assertEqual(json.loads(self.app_request(app, '/data')[1])['entries'], [])

    def test_secret_replacement_and_deletion_apply_to_owning_runtime_external_actions(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        from identity.lifecycle import LifecycleWorker
        expected = ['first-disposable-token\n']

        class ExternalService(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(204 if body == {'token': expected[0]} else 403)
                self.send_header('Content-Length', '0')
                self.end_headers()

        service = ThreadingHTTPServer(('127.0.0.1', 0), ExternalService)
        threading.Thread(target=service.serve_forever, daemon=True).start()
        self.addCleanup(service.server_close)
        self.addCleanup(service.shutdown)
        self.prepare()
        app, other = self.publish('secrets'), self.publish('other')
        lifecycle = LifecycleWorker(self.worker.state, self.worker.infrastructure)

        def set_value(name, value):
            result = subprocess.run([sys.executable, '-m', 'identity.cli', '--json', 'app', 'secrets', 'set',
                                     'secrets', name, '--stdin'], env=self.env, capture_output=True,
                                    text=True, input=value, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn(value, result.stdout + result.stderr)
            lifecycle.once()
            status = json.loads(self.cli('app', 'status', 'secrets').stdout)['data']
            self.assertEqual(status['availability'], 'running', status)
            self.assertEqual(status['active_deployment_id'], app['active_deployment_id'])

        set_value('SERVICE_URL', 'http://127.0.0.1:' + str(service.server_port))
        set_value('SERVICE_TOKEN', expected[0])
        self.assertEqual(json.loads(self.app_request(app, '/secret-probe', {})[1]),
                         {'configured': True, 'external_action': True})
        self.assertEqual(json.loads(self.app_request(other, '/secret-probe', {})[1]),
                         {'configured': False, 'external_action': False})
        expected[0] = 'replacement-disposable-token\n\n'
        set_value('SERVICE_TOKEN', expected[0])
        self.assertTrue(json.loads(self.app_request(app, '/secret-probe', {})[1])['external_action'])
        self.assertEqual(self.cli('app', 'secrets', 'delete', 'secrets', 'SERVICE_TOKEN').returncode, 0)
        lifecycle.once()
        self.assertEqual(json.loads(self.app_request(app, '/secret-probe', {})[1]),
                         {'configured': False, 'external_action': False})


if __name__ == '__main__':
    unittest.main()
