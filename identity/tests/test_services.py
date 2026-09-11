"""Exercise shipped dependency graphs through a real, isolated user systemd manager."""
from pathlib import Path
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid


class ServiceLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get('XDG_RUNTIME_DIR') or not shutil.which('systemctl'):
            raise unittest.SkipTest('Requires a running Linux user systemd manager')
        check = subprocess.run(['systemctl', '--user', 'show', '--property=Version'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        if check.returncode:
            raise unittest.SkipTest('Requires a running Linux user systemd manager')

    def setUp(self):
        self.prefix = 'sc-test-' + uuid.uuid4().hex[:10]
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.fixture = self.home / 'worker.py'
        self.fixture.write_text('''import fcntl, os, pathlib, signal, socket, sys, time
home = pathlib.Path(sys.argv[1])
role = sys.argv[2]
if role == 'dependencies':
    deadline = time.monotonic() + 0.6
    while not (home / 'diagnostics-ready').exists() or (home / 'unavailable').exists():
        if time.monotonic() > deadline:
            sys.exit(1)
        time.sleep(0.02)
    sys.exit(0)
if role == 'identity-ready':
    sys.exit(0)
lock = (home / (role + '.lock')).open('w')
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    (home / 'duplicate').touch()
    sys.exit(1)
running = True
def stop(*_):
    global running
    running = False
signal.signal(signal.SIGTERM, stop)
if role == 'diagnostics':
    while (home / 'delay').exists() and running:
        time.sleep(0.02)
    (home / 'diagnostics-ready').touch()
(home / (role + '.pid')).write_text(str(os.getpid()))
if os.environ.get('NOTIFY_SOCKET'):
    address = os.environ['NOTIFY_SOCKET']
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notification:
        notification.connect(bytes([0]) + address[1:].encode() if address.startswith('@') else address)
        notification.sendall(b'READY=1')
while running:
    time.sleep(0.02)
if role == 'diagnostics':
    (home / 'diagnostics-ready').unlink(missing_ok=True)
''')
        self.units = ['identity', 'diagnostics', 'lifecycle', 'publishing']
        self.directory = Path(os.environ['XDG_RUNTIME_DIR']) / 'systemd/user'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self.cleanup)
        for name in self.units:
            source = (Path(__file__).parents[1] / ('small-cloud-' + name + '.service')).read_text()
            lines = []
            for line in source.splitlines():
                key = line.split('=', 1)[0]
                if key in {'User', 'Group', 'ReadWritePaths', 'ProtectSystem', 'ProtectHome',
                           'PrivateTmp', 'PrivateDevices', 'NoNewPrivileges', 'CapabilityBoundingSet',
                           'RestrictAddressFamilies', 'MemoryMax', 'TasksMax'}:
                    continue
                if key == 'ExecStart':
                    line = 'ExecStart=' + self.fixture_command(name)
                elif key in ('ExecStartPre', 'ExecStartPost'):
                    line = key + '=' + self.fixture_command('identity-ready' if name == 'identity' else 'dependencies')
                elif key == 'ConditionPathExists':
                    line = 'ConditionPathExists=!' + str(self.home / 'maintenance')
                elif key == 'RestartSec':
                    line = 'RestartSec=0.1'
                elif key in ('TimeoutStartSec', 'TimeoutStopSec'):
                    line = key + '=3'
                lines.append(line.replace('small-cloud-', self.prefix + '-'))
            (self.directory / self.unit(name)).write_text('\n'.join(lines) + '\n')
        self.ctl('daemon-reload')

    def fixture_command(self, role):
        return shlex.join(['/usr/bin/python3', str(self.fixture), str(self.home), role])

    def unit(self, name):
        return self.prefix + '-' + name + '.service'

    def ctl(self, *args, check=True):
        return subprocess.run(['systemctl', '--user', *args], capture_output=True,
                              text=True, check=check, timeout=30)

    def cleanup(self):
        self.ctl('stop', *(self.unit(name) for name in self.units), check=False)
        for name in self.units:
            (self.directory / self.unit(name)).unlink(missing_ok=True)
        self.ctl('daemon-reload')
        self.ctl('reset-failed', *(self.unit(name) for name in self.units), check=False)

    def wait_active(self):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if all(self.ctl('is-active', self.unit(name), check=False).returncode == 0 for name in self.units):
                self.assertFalse((self.home / 'duplicate').exists())
                return
            time.sleep(0.05)
        self.fail('required services did not become active')

    def test_identity_restart_restores_required_workers(self):
        self.ctl('start', *(self.unit(name) for name in self.units))
        self.ctl('stop', self.unit('identity'))
        self.ctl('start', self.unit('identity'))
        self.wait_active()
        for name in self.units:
            self.assertEqual(self.ctl('is-active', self.unit(name), check=False).stdout.strip(),
                             'active', name + ' did not recover after identity restart')

    def test_boot_start_and_repeated_identity_restarts_restore_workers(self):
        self.ctl('start', self.unit('identity'))
        self.wait_active()
        for _ in range(2):
            previous = (self.home / 'publishing.pid').read_text()
            self.ctl('restart', self.unit('identity'))
            self.wait_active()
            self.assertNotEqual((self.home / 'publishing.pid').read_text(), previous)

    def test_delayed_diagnostics_prevents_runtime_workers_starting(self):
        (self.home / 'delay').touch()
        self.ctl('start', '--no-block', self.unit('identity'))
        time.sleep(0.3)
        self.assertFalse((self.home / 'publishing.pid').exists())
        self.assertFalse((self.home / 'lifecycle.pid').exists())
        (self.home / 'delay').unlink()
        self.wait_active()

    def test_unavailable_diagnostics_exhausts_recovery_and_stays_failed(self):
        (self.home / 'unavailable').touch()
        self.ctl('start', '--no-block', self.unit('identity'))
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if all(self.ctl('is-active', self.unit(name), check=False).stdout.strip() == 'failed' for name in self.units[1:]):
                break
            time.sleep(0.1)
        for name in self.units[1:]:
            self.assertEqual(self.ctl('is-active', self.unit(name), check=False).stdout.strip(), 'failed')
        self.assertFalse((self.home / 'publishing.pid').exists())
        self.assertFalse((self.home / 'duplicate').exists())

    def test_worker_and_collector_failures_recover_without_duplicate_owners(self):
        self.ctl('start', self.unit('identity'))
        self.wait_active()
        for name in ('publishing', 'diagnostics', 'lifecycle'):
            previous = (self.home / (name + '.pid')).read_text()
            self.ctl('kill', '--signal=KILL', self.unit(name))
            time.sleep(0.2)
            self.wait_active()
            self.assertNotEqual((self.home / (name + '.pid')).read_text(), previous)

    def test_maintenance_stop_survives_start_until_explicit_resume(self):
        self.ctl('start', self.unit('identity'))
        self.wait_active()
        (self.home / 'maintenance').touch()
        self.ctl('stop', *(self.unit(name) for name in self.units[2:]))
        self.ctl('stop', *(self.unit(name) for name in self.units[:2]))
        self.ctl('start', *(self.unit(name) for name in self.units), check=False)
        time.sleep(0.2)
        for name in self.units:
            self.assertEqual(self.ctl('is-active', self.unit(name), check=False).stdout.strip(), 'inactive')
        (self.home / 'maintenance').unlink()
        self.ctl('reset-failed', *(self.unit(name) for name in self.units), check=False)
        self.ctl('start', self.unit('identity'))
        self.wait_active()
