"""Run operator commands with isolated host paths, real systemd and readiness IO."""
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

from identity.collector import Collector
from identity.tests import test_services as fixture


class OperatorCommands(fixture.SystemdFixture):
    def setUp(self):
        super().setUp()
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.staged = self.home / 'staged'
        self.staged.mkdir()
        for name in self.units:
            shutil.copyfile(self.directory / self.unit(name), self.staged / self.unit(name))
        self.wheel = self.home / 'package.whl'
        self.wheel.touch()
        wrappers = {
            'systemctl': 'import os,sys; os.execv(' + repr(shutil.which('systemctl')) +
                ', ["systemctl", "--user", *sys.argv[1:]])',
            'ssh': 'import os,shlex,sys; args=shlex.split(sys.argv[-1]); os.execvp(args[0],args)',
            'installer': 'import pathlib,sys; home=pathlib.Path(' + repr(str(self.home)) + '); '
                '(home/"install-invoked").touch(); sys.exit(int((home/"install-fails").exists()))',
        }
        for name, body in wrappers.items():
            path = self.bin / name
            path.write_text('#!/usr/bin/python3\n' + body + '\n')
            path.chmod(0o700)
        class Health(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"data":{"ready":true}}')
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Health)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.socket = self.home / 'collector.sock'
        collector = Collector(str(self.socket), None, None)
        stop = threading.Event()
        def serve():
            while not stop.is_set():
                collector.poll(0.02)
        collector_thread = threading.Thread(target=serve)
        collector_thread.start()
        self.addCleanup(collector.close)
        self.addCleanup(collector_thread.join)
        self.addCleanup(stop.set)
        identity = self.home / 'identity.json'
        identity.write_text(json.dumps({'origin': 'https://cloud.example.test'}))
        self.config = self.home / 'publishing.json'
        self.config.write_text(json.dumps({'admin_cidr': '203.0.113.1/32',
            'identity_config': str(identity), 'identity_port': server.server_port}))
        self.config.chmod(0o600)
        self.launcher = self.home / 'operator_fixture.py'
        self.launcher.write_text('''from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, ROOT)
from identity import services
services.MAINTENANCE = Path(HOME) / 'maintenance'
services.SERVICE_LOCK = Path(HOME) / 'operator.lock'
services.UNIT_DIRECTORY = Path(UNIT_DIRECTORY)
services.SOCKET = SOCKET
services.UNITS = UNITS
sys.executable = str(Path(HOME) / 'bin/installer')
with patch('os.geteuid', return_value=0):
    raise SystemExit(services.main())
'''.replace('UNIT_DIRECTORY)', repr(str(self.directory)) + ')')
            .replace('ROOT', repr(str(Path(__file__).parents[2])))
            .replace('HOME', repr(str(self.home)))
            .replace('= SOCKET', '= ' + repr(str(self.socket)))
            .replace('= UNITS', '= ' + repr(tuple(self.unit(name) for name in self.units))))

    def operator(self, *args):
        return subprocess.run([sys.executable, str(self.launcher), *args, '--config', str(self.config),
                               '--timeout', '0.5'], capture_output=True, text=True, timeout=20,
                              env={**os.environ, 'PATH': str(self.bin) + os.pathsep + os.environ['PATH']})

    def test_deploy_installs_bundle_and_returns_full_readiness(self):
        result = self.operator('deploy', '--wheel', str(self.wheel), '--units-directory', str(self.staged))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['ready'])
        self.assertTrue((self.home / 'install-invoked').exists())
        self.wait_active()

    def test_failed_installation_stays_in_maintenance_until_explicit_resume(self):
        (self.home / 'install-fails').touch()
        result = self.operator('deploy', '--wheel', str(self.wheel), '--units-directory', str(self.staged))
        self.assertEqual(result.returncode, 1)
        self.assertTrue((self.home / 'maintenance').exists())
        self.assertEqual(self.operator('check').returncode, 1)
        self.assertEqual(self.operator('resume').returncode, 0)
        self.wait_active()

    def test_operator_maintenance_blocks_start_and_deploy_until_resume(self):
        self.assertEqual(self.operator('resume').returncode, 0)
        result = self.operator('maintenance-stop')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['maintenance'])
        self.ctl('start', self.unit('identity'), check=False)
        self.assertEqual(self.operator('check').returncode, 1)
        self.assertEqual(self.operator('deploy', '--wheel', str(self.wheel),
                                       '--units-directory', str(self.staged)).returncode, 1)
        self.assertFalse((self.home / 'install-invoked').exists())
        self.assertEqual(self.operator('resume').returncode, 0)
        self.wait_active()

    def test_check_fails_when_required_worker_is_stopped(self):
        self.assertEqual(self.operator('resume').returncode, 0)
        self.ctl('stop', self.unit('publishing'))
        self.assertEqual(self.operator('check').returncode, 1)

    def test_concurrent_operator_command_is_refused_without_stopping_services(self):
        self.assertEqual(self.operator('resume').returncode, 0)
        with (self.home / 'operator.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.operator('maintenance-stop').returncode, 1)
        self.assertFalse((self.home / 'maintenance').exists())
        self.wait_active()
