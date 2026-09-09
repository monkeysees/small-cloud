"""Idle lifecycle acceptance through authenticated HTTP and creator observations."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import threading
import time
import unittest
import urllib.parse
import uuid

from identity.common import Failure
from identity.lifecycle import LifecycleWorker
from identity.worker import State, Worker
from identity.tests import test_limits_http as limits_fixture


class LifecycleAcceptance(unittest.TestCase):
    setUp = limits_fixture.LimitsAcceptance.setUp
    operator = limits_fixture.LimitsAcceptance.operator
    start_platform = limits_fixture.LimitsAcceptance.start_platform
    restart_platform = limits_fixture.LimitsAcceptance.restart_platform
    http = limits_fixture.LimitsAcceptance.http
    approve = limits_fixture.LimitsAcceptance.approve
    http_login = limits_fixture.LimitsAcceptance.http_login
    cli = limits_fixture.LimitsAcceptance.cli
    login = limits_fixture.LimitsAcceptance.login
    creator = limits_fixture.LimitsAcceptance.creator
    deploy = limits_fixture.LimitsAcceptance.deploy
    usage = limits_fixture.LimitsAcceptance.usage

    def prepare(self):
        self.creator()
        self.now = time.time()
        self.platform_server.application.publishing.clock = lambda: self.now
        self.entered, self.release = threading.Event(), threading.Event()
        self.addCleanup(self.release.set)
        fixture = self

        class Runtime(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                if self.path == '/slow':
                    fixture.entered.set()
                    fixture.release.wait(10)
                self.send_response(200)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'OK')

        runtime = ThreadingHTTPServer(('127.0.0.1', 0), Runtime)
        threading.Thread(target=runtime.serve_forever, daemon=True).start()
        self.addCleanup(runtime.server_close)
        self.addCleanup(runtime.shutdown)

        class Infrastructure(limits_fixture.BuildFixture):
            fail_wake = False
            fail_stop = False
            lose_wake = False

            def start(self, operation, artifact, app, register):
                return {'host': '127.0.0.1', 'port': runtime.server_port, 'container': 'sc-' + app['id'] + '-active'}

            def stop(self, app):
                if self.fail_stop:
                    raise Failure('INTERNAL', 'Fixture stop failed', 500)

            def wake(self, app, register):
                if self.lose_wake:
                    raise KeyboardInterrupt()
                if self.fail_wake:
                    raise Failure('STARTUP_FAILED', 'Fixture startup failed', 503)
                return self.start({}, {}, app, register)

        self.infrastructure = Infrastructure()
        state = State(self.home / 'server' / 'identity.sqlite3')
        self.publisher = Worker(state, self.infrastructure, clock=lambda: self.now)
        self.lifecycle = LifecycleWorker(state, self.infrastructure, clock=lambda: self.now)

    def publish(self, name):
        status, body = self.deploy(name=name)
        self.assertEqual(status, 202, body)
        self.publisher.once()
        return self.status(name)

    def status(self, name):
        status, body = self.http('/api/apps/' + name, token=self.token)
        self.assertEqual(status, 200, body)
        return json.loads(body)['data']

    def request(self, app, path='/', token=True, headers=None, body=None):
        return self.http(path, body=body, token=self.token if token else None,
                         headers={'Host': urllib.parse.urlsplit(app['url']).netloc, **(headers or {})})

    def stop_all(self):
        self.now += 1800
        while self.lifecycle.once():
            pass

    def test_competing_starts_reserve_five_slots_and_retry_without_eviction(self):
        self.prepare()
        apps = []
        for i in range(7):
            apps.append(self.publish('app-' + str(i)))
            self.stop_all()
        with ThreadPoolExecutor(7) as pool:
            outcomes = list(pool.map(lambda app: self.request(app), apps))
        codes = [json.loads(raw)['error']['code'] for _, raw in outcomes]
        self.assertEqual(codes.count('STARTING'), 5)
        self.assertEqual(codes.count('ACTIVE_CAPACITY'), 2)
        self.assertEqual(self.usage()['active_apps']['used'], 5)
        refused = self.publish('deployment-at-capacity')
        self.assertEqual(refused['latest_operation']['error']['code'], 'ACTIVE_CAPACITY')
        self.assertEqual(refused['latest_operation']['state'], 'failed')
        self.assertEqual(self.usage()['active_apps']['used'], 5)
        full = apps[codes.index('ACTIVE_CAPACITY')]
        status, page = self.request(full, headers={'Accept': 'text/html'})
        self.assertEqual(status, 503)
        self.assertIn('Workspace at capacity', page)
        self.assertIn('Retry</button>', page)
        self.assertNotIn('http-equiv="refresh"', page)
        while self.lifecycle.once():
            pass
        running = [app for app, code in zip(apps, codes) if code == 'STARTING']
        for app in running:
            self.assertEqual(self.request(app)[0], 200)
        self.now += 1799
        for app in running[1:]:
            self.assertEqual(self.request(app)[0], 200)
        self.now += 1
        self.lifecycle.once()
        self.assertEqual(self.usage()['active_apps']['used'], 4)
        self.assertEqual(json.loads(self.request(full)[1])['error']['code'], 'STARTING')
        self.lifecycle.once()
        self.assertEqual(self.request(full)[0], 200)
        for app in running[1:]:
            self.assertEqual(self.request(app)[0], 200)

    def test_only_forwarded_requests_reset_idle_and_inflight_requests_prevent_stop(self):
        self.prepare()
        app = self.publish('requests')
        self.now += 1799
        self.assertEqual(self.request(app, token=False)[0], 401)
        self.assertEqual(self.request(app, '/_small-cloud/ready')[0], 404)
        self.assertEqual(self.request(app, headers={'Content-Length': '-1'})[0], 400)
        self.now += 1
        self.lifecycle.once()
        self.assertEqual(self.status('requests')['availability'], 'stopped')
        for headers in ({'Content-Length': '-1'}, {'Transfer-Encoding': 'chunked'}):
            self.assertEqual(self.request(app, headers=headers)[0], 400)
            self.assertEqual(self.usage()['active_apps']['used'], 0)
        self.request(app)
        self.lifecycle.once()
        with ThreadPoolExecutor(1) as pool:
            request = pool.submit(self.request, app, '/slow')
            self.assertTrue(self.entered.wait(5))
            self.now += 1800
            self.lifecycle.once()
            self.assertEqual(self.status('requests')['availability'], 'running')
            self.release.set()
            self.assertEqual(request.result()[0], 200)
        self.now += 1799
        self.lifecycle.once()
        self.assertEqual(self.status('requests')['availability'], 'running')
        self.now += 1
        self.lifecycle.once()
        self.assertEqual(self.status('requests')['availability'], 'stopped')

    def test_failed_start_releases_capacity_and_requires_explicit_retry(self):
        self.prepare()
        app = self.publish('failure')
        self.stop_all()
        status, page = self.request(app, body={'change': 'never replay'}, headers={'Accept': 'text/html'})
        self.assertEqual(status, 503)
        self.assertNotIn('http-equiv="refresh"', page)
        self.infrastructure.fail_wake = True
        self.lifecycle.once()
        self.assertEqual(self.usage()['active_apps']['used'], 0)
        self.assertEqual(json.loads(self.request(app)[1])['error']['code'], 'STARTUP_FAILED')
        self.assertEqual(self.usage()['active_apps']['used'], 0)
        self.infrastructure.fail_wake = False
        self.assertEqual(json.loads(self.request(app, '/_small-cloud/retry?return=%2F')[1])['error']['code'], 'STARTING')
        self.lifecycle.once()
        self.assertEqual(self.request(app)[0], 200)

    def test_restart_preserves_reservations_and_reconciles_interrupted_wake(self):
        self.prepare()
        app = self.publish('restart')
        self.stop_all()
        self.request(app)
        self.restart_platform()
        self.platform_server.application.publishing.clock = lambda: self.now
        self.assertEqual(self.usage()['active_apps']['used'], 1)
        self.infrastructure.lose_wake = True
        with self.assertRaises(KeyboardInterrupt):
            self.lifecycle.once()
        self.assertEqual(self.usage()['active_apps']['used'], 1)
        self.lifecycle.recover()
        self.infrastructure.fail_stop = True
        self.lifecycle.once()
        self.assertEqual(self.usage()['active_apps']['used'], 1)
        status = self.status('restart')
        self.assertEqual(status['availability'], 'unavailable')
        self.assertTrue(status['runtime_error']['details']['reconciliation_required'])
        self.assertEqual(json.loads(self.request(app)[1])['error']['code'], 'STARTUP_FAILED')
        self.assertEqual(self.deploy(name='restart')[1]['error']['code'], 'OPERATION_CONFLICT')
        self.infrastructure.fail_stop = False
        self.infrastructure.lose_wake = False
        self.lifecycle.recover()
        self.lifecycle.once()
        self.assertEqual(self.usage()['active_apps']['used'], 0)
        self.assertIsNone(self.status('restart')['runtime_error'])
        self.assertEqual(json.loads(self.request(app)[1])['error']['code'], 'STARTING')
        self.lifecycle.once()
        self.assertEqual(self.request(app)[0], 200)

    def test_private_denial_does_not_wake_and_browser_signin_completes_while_stopped(self):
        self.prepare()
        app = self.publish('private')
        self.stop_all()
        self.http('/api/admin/member/add', {'email': 'member@example.test'}, token=self.token,
                  headers={'X-Request-ID': str(uuid.uuid4())})
        member = self.http_login('member@example.test')['credential']
        status, _ = self.request(app, token=False, headers={'Authorization': 'Bearer ' + member})
        self.assertEqual(status, 404)
        self.assertEqual(self.usage()['active_apps']['used'], 0)
        self.identity = {'sub': 'admin@example.test', 'email': 'admin@example.test', 'email_verified': True, 'name': 'Admin'}

        def get(url, cookie='', host=None):
            parsed = urllib.parse.urlsplit(url)
            conn = http.client.HTTPSConnection(parsed.hostname, parsed.port, context=self.client_tls)
            try:
                conn.request('GET', parsed.path + ('?' + parsed.query if parsed.query else ''),
                             headers={'Host': host or parsed.netloc, 'Accept': 'text/html', 'Cookie': cookie})
                response = conn.getresponse()
                return response.status, response.read(), dict(response.getheaders())
            finally:
                conn.close()

        host = urllib.parse.urlsplit(app['url']).netloc
        status, _, headers = get(self.endpoint + '/', host=host)
        self.assertEqual(status, 302)
        flow_cookie = headers['Set-Cookie'].split(';')[0]
        status, _, headers = get(headers['Location'])
        self.assertEqual(status, 302)
        callback = urllib.parse.urlsplit(headers['Location'])
        status, _, headers = get(self.endpoint + callback.path + '?' + callback.query)
        self.assertEqual(status, 302)
        finish = urllib.parse.urlsplit(headers['Location'])
        status, _, headers = get(self.endpoint + finish.path + '?' + finish.query, flow_cookie, host)
        self.assertEqual(status, 302)
        self.assertEqual(self.usage()['active_apps']['used'], 0)
        session = headers['Set-Cookie'].split(';')[0]
        status, page, headers = get(self.endpoint + '/', session, host)
        self.assertEqual(status, 503)
        self.assertEqual(headers['Retry-After'], '2')
        self.assertIn(b'Starting your app', page)
        self.assertIn(b'http-equiv="refresh"', page)
        self.lifecycle.once()
        self.assertEqual(get(self.endpoint + '/', session, host)[0], 200)
