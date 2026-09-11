"""Control-host service readiness and maintenance; never repair application state."""
import argparse
import fcntl
import json
import inspect
import os
from pathlib import Path
import secrets
import shutil
import shlex
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from .common import Failure, read_private

SOCKET = '/run/small-cloud-diagnostics.sock'
MAINTENANCE = Path('/etc/small-cloud/maintenance')
SERVICE_LOCK = Path('/run/small-cloud-services.lock')
UNIT_DIRECTORY = Path('/etc/systemd/system')
UNITS = tuple('small-cloud-' + name + '.service' for name in
              ('identity', 'diagnostics', 'lifecycle', 'publishing'))


def probe(path=SOCKET, timeout=3):
    nonce = secrets.token_hex(16).encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(path)
        connection.sendall(b'PING ' + nonce + b'\n')
        expected = b'PONG ' + nonce + b'\n'
        received = b''
        while len(received) < len(expected):
            chunk = connection.recv(len(expected) - len(received))
            if not chunk:
                break
            received += chunk
        if received != expected:
            raise OSError('diagnostics collector did not acknowledge probe')


def probe_command(infrastructure):
    # The runtime needs only Python's standard library, not the identity package.
    script = 'import socket, secrets\nSOCKET=' + repr(SOCKET) + '\n' + inspect.getsource(probe) + '\nprobe()\n'
    return ['ssh', *infrastructure.options, 'root@' + infrastructure.runtime,
            shlex.join(['python3', '-c', script])]


def identity_ready(config, port=8765, timeout=3):
    request = urllib.request.Request('http://127.0.0.1:' + str(port) + '/health',
        headers={'Host': urllib.parse.urlsplit(config['origin']).netloc})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        if response.status != 200 or json.loads(response.read(4096)).get('data', {}).get('ready') is not True:
            raise OSError('identity is not ready')


def dependencies_ready(config, timeout=10):
    from .worker import Infrastructure
    # The identity account owns this file; privileged workers already trust its
    # root-configured path for platform redaction.
    identity_ready(json.loads(Path(config.get('identity_config', '/etc/small-cloud/identity/server.json')).read_text()),
                   config.get('identity_port', 8765))
    result = subprocess.run(probe_command(Infrastructure(config)), stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
    if result.returncode:
        raise OSError('diagnostics round trip failed')


def systemctl(*arguments, timeout=2100):
    return subprocess.check_output(['systemctl', *arguments], text=True, timeout=timeout)


def wait_ready(check, timeout):
    deadline = time.monotonic() + timeout
    while True:
        try:
            check()
            return
        except (Failure, OSError, ValueError, KeyError, subprocess.SubprocessError):
            if time.monotonic() >= deadline:
                raise OSError('readiness deadline exceeded') from None
            time.sleep(min(1, max(0, deadline - time.monotonic())))


def installation_ready(config):
    if MAINTENANCE.exists():
        raise OSError('maintenance is active')
    dependencies_ready(config)
    for unit in UNITS:
        properties = dict(line.split('=', 1) for line in systemctl('show', unit,
            '--property=ActiveState,SubState,MainPID', timeout=5).splitlines())
        if (properties.get('ActiveState') != 'active' or properties.get('SubState') != 'running'
                or properties.get('MainPID', '0') == '0'):
            raise OSError('required service is unavailable')


def maintenance_stop():
    MAINTENANCE.touch(mode=0o600)
    # Drain first, including when upgrading the old, unordered collector units.
    systemctl('stop', *UNITS[2:])
    systemctl('stop', *UNITS[:2])


def resume(config, timeout):
    MAINTENANCE.unlink(missing_ok=True)
    # Inactive units may already be unloaded; those have no counters to reset.
    subprocess.run(['systemctl', 'reset-failed', *UNITS], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=10, check=False)
    systemctl('start', UNITS[0])
    wait_ready(lambda: installation_ready(config), timeout)
    time.sleep(5)
    installation_ready(config)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('probe', help='Verify an acknowledged collector round trip')
    command.add_argument('--socket', default=SOCKET)
    command.add_argument('--timeout', type=float, default=3)
    command = commands.add_parser('identity', help='Wait for usable identity HTTP')
    command.add_argument('--identity-config', type=Path, default=Path('/etc/small-cloud/identity/server.json'))
    command.add_argument('--port', type=int, default=8765)
    command.add_argument('--timeout', type=float, default=45)
    for name in ('dependencies', 'check', 'maintenance-stop', 'resume', 'deploy'):
        command = commands.add_parser(name)
        command.add_argument('--config', type=Path, default=Path('/etc/small-cloud/publishing.json'))
        command.add_argument('--timeout', type=float, default=45)
        if name == 'deploy':
            command.add_argument('--wheel', type=Path, required=True)
            command.add_argument('--units-directory', type=Path, required=True)
    args = parser.parse_args()
    lock = None
    try:
        if args.timeout <= 0:
            raise ValueError('timeout must be positive')
        if args.command == 'probe':
            probe(args.socket, args.timeout)
        elif args.command == 'identity':
            config = read_private(args.identity_config)
            wait_ready(lambda: identity_ready(config, args.port, min(3, args.timeout)), args.timeout)
        else:
            if os.geteuid() != 0:
                raise OSError('requires control-host root')
            if args.command in ('maintenance-stop', 'resume', 'deploy'):
                lock = SERVICE_LOCK.open('w')
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            config = read_private(args.config)
            if args.command == 'dependencies':
                wait_ready(lambda: dependencies_ready(config), args.timeout)
            elif args.command == 'check':
                wait_ready(lambda: installation_ready(config), args.timeout)
            elif args.command == 'maintenance-stop':
                maintenance_stop()
            else:
                if args.command == 'deploy':
                    if MAINTENANCE.exists():
                        raise OSError('explicitly resume maintenance before deploying')
                    if not args.wheel.is_file() or not all((args.units_directory / unit).is_file() for unit in UNITS):
                        raise OSError('deployment bundle is incomplete')
                    maintenance_stop()
                    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--force-reinstall',
                                    str(args.wheel.resolve())], check=True, timeout=120)
                    for unit in UNITS:
                        shutil.copyfile(args.units_directory / unit, UNIT_DIRECTORY / unit)
                    systemctl('daemon-reload')
                    systemctl('enable', *UNITS)
                resume(config, args.timeout)
        if args.command not in ('probe', 'identity', 'dependencies'):
            print(json.dumps({'ready': args.command != 'maintenance-stop', 'maintenance': MAINTENANCE.exists()}))
        return 0
    except (Failure, OSError, ValueError, KeyError, subprocess.SubprocessError):
        component = 'diagnostics' if args.command == 'probe' else args.command
        print('Unhealthy ' + component + ': readiness or service action failed. Inspect systemctl status '
              'and journalctl for small-cloud services; repair access/configuration, then run '
              'python -m identity.services resume. Application reservations are unchanged.', file=sys.stderr)
        return 1
    finally:
        if lock is not None:
            lock.close()


if __name__ == '__main__':
    raise SystemExit(main())
