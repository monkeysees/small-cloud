"""Runtime syslog collection over a root-only Unix socket and pinned SSH forwarding."""
import argparse
import json
import os
from pathlib import Path
import re
import selectors
import socket
import subprocess
import time

from . import diagnostics
from .common import Failure, read_private
from .worker import Infrastructure, State, platform_redaction, seed_redaction

HEADER = re.compile(rb'^<\d{1,3}>1 \S+ \S+ (d-[0-9a-f]{24}) \S+ \S+ - (?:\xef\xbb\xbf)?(.*)$', re.DOTALL)
SOCKET = '/run/small-cloud-diagnostics.sock'


class Connection:
    def __init__(self, state, registry):
        self.state, self.registry = state, registry
        self.buffer = b''
        self.writer = None
        self.deployment = None

    def feed(self, data):
        self.buffer += data
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            match = HEADER.fullmatch(line)
            if match is None or len(line) > 65536:
                raise ValueError('Malformed runtime diagnostic frame')
            deployment = match[1].decode('ascii')
            if self.writer is None:
                self.deployment = deployment
                self.writer = diagnostics.Writer(self.state, self.registry, deployment, 'runtime')
            elif self.deployment != deployment:
                raise ValueError('Runtime diagnostic connection changed deployment')
            # Syslog frames can split Docker's long lines; redact across frames before
            # treating the available safe prefix as a record.
            self.writer.feed(match[2], record=True)
        if len(self.buffer) > 65536:
            raise ValueError('Runtime diagnostic frame exceeds bound')

    def close(self):
        if self.writer:
            self.writer.feed(b'', final=True)
            self.writer.append('[collection interrupted or container stopped; output may be missing]', interrupted=True)


class Collector:
    def __init__(self, path, state, registry):
        self.state, self.registry = state, registry
        self.path = Path(path)
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(path))
        self.path.chmod(0o600)
        self.listener.listen(8)
        self.listener.setblocking(False)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.listener, selectors.EVENT_READ, None)

    def poll(self, timeout=1):
        for key, _ in self.selector.select(timeout):
            assert isinstance(key.fileobj, socket.socket)
            if key.fileobj is self.listener:
                connection, _ = self.listener.accept()
                if len(self.selector.get_map()) >= 9:
                    connection.close()
                    continue
                connection.setblocking(False)
                self.selector.register(connection, selectors.EVENT_READ, Connection(self.state, self.registry))
            else:
                try:
                    data = key.fileobj.recv(65536)
                    if not data:
                        raise EOFError()
                    key.data.feed(data)
                except (EOFError, OSError, ValueError):
                    self.selector.unregister(key.fileobj)
                    key.fileobj.close()
                    key.data.close()

    def close(self):
        for key in list(self.selector.get_map().values()):
            assert isinstance(key.fileobj, socket.socket)
            if key.data:
                key.data.close()
            key.fileobj.close()
        self.selector.close()
        self.path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Requires control-host root')
    os.umask(0o077)
    config = read_private(args.config)
    state = State(config['database'])
    registry = diagnostics.Registry(state, config.get('redaction_key', '/srv/small-cloud/secrets/diagnostics.key'))
    infrastructure = Infrastructure(config)
    # Systemd owns the service lifecycle; a separate lock prevents manual duplicate daemons.
    import fcntl
    with open('/run/small-cloud-diagnostics.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        Path(SOCKET).unlink(missing_ok=True)
        seed_redaction(registry, config)
        with state.connect() as db:
            active = db.execute('SELECT active_deployment_id AS id FROM apps WHERE active_deployment_id IS NOT NULL '
                                "UNION SELECT id FROM deployments WHERE state IN ('starting','cleaning')").fetchall()
        for row in active:
            diagnostics.Writer(state, registry, row['id'], 'runtime').append(
                '[collector restarted; output during the interruption may be missing]', interrupted=True)
        collector = Collector(SOCKET, state, registry)
        tunnel = None
        last_maintenance = 0
        try:
            while True:
                if time.monotonic() - last_maintenance >= 30:
                    platform_redaction(registry, config)
                    registry.maintain()
                    for key in collector.selector.get_map().values():
                        if key.data and key.data.writer:
                            key.data.writer.refresh()
                    last_maintenance = time.monotonic()
                if tunnel is None or tunnel.poll() is not None:
                    if tunnel is not None:
                        # Allow Docker to reconnect to the replacement forwarded socket.
                        time.sleep(1)
                    try:
                        infrastructure.ssh('rm', '-f', '--', SOCKET, timeout=15)
                    except Failure:
                        collector.poll()
                        continue
                    tunnel = subprocess.Popen(['ssh', *infrastructure.options, '-N',
                        '-o', 'ExitOnForwardFailure=yes', '-o', 'StreamLocalBindUnlink=yes',
                        '-R', SOCKET + ':' + SOCKET, 'root@' + infrastructure.runtime],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                collector.poll()
        finally:
            if tunnel is not None:
                tunnel.terminate()
                tunnel.wait(timeout=10)
            collector.close()


if __name__ == '__main__':
    main()
