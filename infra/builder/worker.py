#!/usr/bin/env python3
"""Trusted disposable-builder entry point. No provider or registry credentials."""

import hashlib
import fcntl
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import time

ROOT = Path('/var/lib/small-cloud-build')
CONTEXT_LIMIT = 100 * 1024 * 1024
IMAGE_LIMIT = 500 * 1024 * 1024
LOG_LIMIT = 10 * 1024 * 1024
DOCKER = ['/usr/bin/docker', '--host=unix:///run/sc-build.sock']
EXECUTION_STARTED_AT: str | None = None
EXECUTION_STARTED_MONOTONIC: float | None = None


def execution_timing():
    if EXECUTION_STARTED_AT is None or EXECUTION_STARTED_MONOTONIC is None:
        return {}
    return {
        'execution_started_at': EXECUTION_STARTED_AT,
        'execution_completed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'execution_duration_seconds': round(time.monotonic() - EXECUTION_STARTED_MONOTONIC, 3),
    }


def terminate():
    with (ROOT / 'termination.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt = ROOT / 'output/accounting.json'
        if receipt.exists():
            return
        group = subprocess.check_output([
            '/usr/bin/systemctl', 'show', '--property=ControlGroup', '--value',
            'small-cloud-build.slice',
        ], text=True, timeout=5).strip()
        started = ROOT / 'output/execution.json'
        if not group and not started.exists():
            receipt.write_text(json.dumps({'terminated': True, 'duration_seconds': 0}) + '\n')
            return
        if not group.endswith('/small-cloud-build.slice') or '..' in group.split('/'):
            raise RuntimeError('Cannot locate build cgroup; controller must delete VM')
        cgroup = Path('/sys/fs/cgroup') / group.lstrip('/')
        # Kill every descendant, then confirm the group is empty before issuing evidence.
        (cgroup / 'cgroup.kill').write_text('1\n')
        deadline = time.monotonic() + 5
        while (cgroup / 'cgroup.events').exists() and 'populated 1' in (cgroup / 'cgroup.events').read_text():
            if time.monotonic() >= deadline:
                raise RuntimeError('Build cgroup termination is unconfirmed')
            time.sleep(0.01)
        duration = time.monotonic() - json.loads(started.read_text())['monotonic'] if started.exists() else 0
        temporary = receipt.with_suffix('.tmp')
        temporary.write_text(json.dumps({'terminated': True, 'duration_seconds': duration}) + '\n')
        temporary.replace(receipt)


def daemon(arguments):
    # ip netns exec remounts /sys and hides cgroup2. Keep it visible to dockerd,
    # changing only the resolver in the caller's private mount namespace.
    subprocess.run(['/usr/bin/mount', '--bind', '/etc/netns/sc-build/resolv.conf',
                    '/etc/resolv.conf'], check=True)
    process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert process.stdout is not None
    written = 0
    with (ROOT / 'output/daemon.log').open('wb', buffering=0) as output:
        while chunk := os.read(process.stdout.fileno(), 65536):
            retained = chunk[:max(0, LOG_LIMIT - written)]
            output.write(retained)
            written += len(retained)
    return process.wait()


def prepare(archive, management):
    addresses = [str(ipaddress.IPv4Address(value)) for value in management]
    if not addresses:
        raise ValueError('Supply all platform management and database IPv4 addresses')
    if Path(archive).stat().st_size > CONTEXT_LIMIT + 16 * 1024 * 1024:
        raise ValueError('Archive exceeds upload bound')
    context = ROOT / 'context'
    context.mkdir(mode=0o700)
    total = 0
    seen = set()
    # No extractall: archive links, device nodes, permissions and owners are untrusted.
    with tarfile.open(archive, mode='r|') as source:
        for count, member in enumerate(source, 1):
            path = PurePosixPath(member.name)
            parts = path.parts
            if member.isdir() and member.name in ('.', './'):
                continue
            if (count > 10000 or not parts or path.is_absolute() or '..' in parts
                    or member.name in seen or not (member.isfile() or member.isdir())):
                raise ValueError('Unsafe source archive')
            if any(part in ('.git', '.small-cloud') or part == '.env'
                   or part.startswith('.env.') for part in parts):
                raise ValueError('Source contains a mandatory exclusion')
            if any(parts[i:i + 2] == ('.config', 'small-cloud')
                   or parts[i:i + 3] == ('.local', 'state', 'small-cloud')
                   for i in range(len(parts))):
                raise ValueError('Source contains platform configuration')
            seen.add(member.name)
            total += member.size
            if total > CONTEXT_LIMIT:
                raise ValueError('Source exceeds 100 MiB')
            destination = context.joinpath(*parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True, mode=0o755)
                destination.chmod(member.mode & 0o777)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                incoming = source.extractfile(member)
                if incoming is None:
                    raise ValueError('Archive file has no readable content')
                with incoming, destination.open('xb') as output:
                    while chunk := incoming.read(64 * 1024):
                        output.write(chunk)
                destination.chmod(member.mode & 0o777)
    if not (context / 'Dockerfile').is_file():
        raise ValueError('Root Dockerfile required')
    blocked = ', '.join([
        '0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
        '169.254.0.0/16', '172.16.0.0/12', '192.0.0.0/24', '192.0.2.0/24',
        '192.168.0.0/16', '198.18.0.0/15', '198.51.100.0/24', '203.0.113.0/24',
        '224.0.0.0/4', '240.0.0.0/4', *addresses,
    ])
    (ROOT / 'policy.nft').write_text('''table inet sc_build {
 set forbidden { type ipv4_addr; flags interval; auto-merge; elements = { ''' + blocked + ''' } }
 chain input { type filter hook input priority -200; policy accept;
  iifname "sc-host" drop
 }
 chain forward { type filter hook forward priority -200; policy drop;
  iifname "sc-host" meta nfproto ipv6 drop
  iifname "sc-host" ip daddr @forbidden drop
  iifname "sc-host" accept
  oifname "sc-host" ct state established,related accept
 }
}
table ip sc_build_nat {
 chain postrouting { type nat hook postrouting priority srcnat; policy accept;
  ip saddr 192.0.2.2 masquerade
 }
}
''')


def execute():
    global EXECUTION_STARTED_AT, EXECUTION_STARTED_MONOTONIC
    EXECUTION_STARTED_AT = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    EXECUTION_STARTED_MONOTONIC = time.monotonic()
    (ROOT / 'output/execution.json').write_text(json.dumps({'monotonic': EXECUTION_STARTED_MONOTONIC}) + '\n')
    env = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': '/nonexistent',
           'DOCKER_CONFIG': '/nonexistent', 'DOCKER_BUILDKIT': '1'}
    for _ in range(120):
        if subprocess.run(DOCKER + ['info'], env=env, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=5).returncode == 0:
            break
        time.sleep(0.25)
    else:
        raise RuntimeError('Isolated build daemon did not become ready')
    (ROOT / 'output/result.json').write_text(json.dumps({
        'ok': False, 'error': 'ExecutionNotCompleted',
        'execution_started_at': EXECUTION_STARTED_AT,
        'execution_completed_at': None, 'execution_duration_seconds': None,
    }) + '\n')
    dropped = 0
    with (ROOT / 'output/build.log').open('wb') as log:
        process = subprocess.Popen(DOCKER + ['build', '--progress=plain', '--no-cache',
                                             '--tag=sc-artifact:build', str(ROOT / 'context')],
                                   env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert process.stdout is not None
        written = 0
        while chunk := os.read(process.stdout.fileno(), 64 * 1024):
            retained = chunk[:max(0, LOG_LIMIT - written)]
            log.write(retained)
            log.flush()
            written += len(retained)
            dropped += len(chunk) - len(retained)
        if process.wait() != 0:
            raise RuntimeError('Dockerfile build failed; inspect bounded build.log')
    # Stream and bound export; a declared image size does not bound a tar stream.
    digest = hashlib.sha256()
    size = 0
    with (ROOT / 'output/image.tar').open('xb') as artifact:
        process = subprocess.Popen(DOCKER + ['save', 'sc-artifact:build'], env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        assert process.stdout is not None
        try:
            while chunk := process.stdout.read(64 * 1024):
                size += len(chunk)
                if size > IMAGE_LIMIT:
                    raise ValueError('Image export exceeds 500 MiB')
                digest.update(chunk)
                artifact.write(chunk)
            if process.wait() != 0:
                raise RuntimeError('Image export failed')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    (ROOT / 'output/result.json').write_text(json.dumps({
        'ok': True, 'image_archive_sha256': digest.hexdigest(), 'image_bytes': size,
        'dropped_log_bytes': dropped,
        **execution_timing(),
    }) + '\n')


if __name__ == '__main__':
    try:
        if len(sys.argv) >= 4 and sys.argv[1] == 'prepare':
            prepare(sys.argv[2], sys.argv[3:])
        elif sys.argv[1:] == ['execute']:
            execute()
        elif sys.argv[1:] == ['terminate']:
            terminate()
        elif len(sys.argv) >= 3 and sys.argv[1] == 'daemon':
            sys.exit(daemon(sys.argv[2:]))
        else:
            raise ValueError('Usage: worker.py prepare ARCHIVE MANAGEMENT_IPV4... | execute')
    except (OSError, ValueError, RuntimeError, tarfile.TarError, subprocess.SubprocessError) as error:
        # Raw daemon output is retained only in bounded, private build logs.
        if (ROOT / 'output').is_dir():
            (ROOT / 'output/result.json').write_text(json.dumps({
                'ok': False, 'error': type(error).__name__,
                **execution_timing(),
            }) + '\n')
        print(f'Builder failed: {type(error).__name__}', file=sys.stderr)
        sys.exit(1)
