"""Real PostgreSQL acceptance through creator CLI and authenticated app HTTP.

Docker replaces the EU infrastructure boundary; identity, publishing, provisioning,
starter initialization and database authorization run their real implementations.
"""
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
import uuid
import urllib.parse

from identity.tests import test_deployment_http as deployment_fixture
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

    def prepare(self):
        self.creator()
        self.login()
        acceptance = self
        self.runtimes = {}
        self.database_names = {}

        class LocalInfrastructure:
            def build(self, operation):
                return {}

            def start(self, operation, artifact, app):
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
                env = {**os.environ, 'DATABASE_URL': url, 'PORT': str(port)}
                process = subprocess.Popen([sys.executable, str(ROOT / 'identity/fixture/app.py')],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                acceptance.addCleanup(acceptance.stop, process)
                acceptance.runtimes[operation['app_id']] = (process, env)
                return {'host': '127.0.0.1', 'port': port, 'container': operation['id']}

            def ready(self, target):
                acceptance.wait_ready(target['port'])

            def promote(self, operation, app, target):
                return target['container']

            def cleanup(self, operation, app, succeeded=False):
                pass

            def build_log(self, operation):
                return '', 0

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
        result = self.cli('deploy', str(ROOT / 'identity/fixture'), '--name', name, '--description', 'Disposable test')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.worker.once()
        result = self.cli('status', name)
        self.assertEqual(result.returncode, 0, result.stdout)
        app = json.loads(result.stdout)['data']
        self.assertEqual(app['availability'], 'running', app)
        return app

    def app_request(self, app, path='/', body=None, token=True, headers=None):
        return self.http(path, body, token=self.token if token else None,
                         headers={'Host': urllib.parse.urlsplit(app['url']).netloc, **(headers or {})})

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
        result = self.cli('share', 'shared', '--scope', 'workspace-wide')
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
        result = self.cli('share', 'shared', '--scope', 'creator-only')
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


if __name__ == '__main__':
    unittest.main()
