#!/usr/bin/env python3
"""Root operator registry release inventory; product promotion remains a separate workflow."""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from artifacts import require_space

GRACE = 23 * 3600  # Hourly sweeps complete retention within the 24-hour contract.


def identifier(value):
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', value) or len(value) > 32:
        raise ValueError('identifier must be at most 32 lowercase letters/digits/hyphens')
    return value


def write_record(path, record):
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix='.record-')
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        Path(name).unlink(missing_ok=True)


def records(root):
    rows = []
    for path in root.glob('*.json'):
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096):
            raise ValueError('unsafe release record')
        row = json.loads(path.read_text())
        tool, release = identifier(row['tool']), identifier(row['release'])
        if path.name != tool + '.' + release + '.json' or row['state'] not in ('pending', 'retained', 'retired'):
            raise ValueError('invalid release record identity/state')
        stamp = row['changed_at']
        if isinstance(stamp, bool) or not isinstance(stamp, (float, int)) or not math.isfinite(stamp) or stamp < 0:
            raise ValueError('invalid release timestamp')
        rows.append((path, row))
        if len(rows) > 256:
            raise ValueError('release backlog requires operator inspection')
    return rows


def command(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)


def repository(row):
    return 'small-cloud/' + row['tool'] + '/' + row['release']


def remove_manifest(row):
    base = 'http://127.0.0.1:5000/v2/' + repository(row) + '/manifests/'
    request = urllib.request.Request(base + 'release', method='HEAD',
        headers={'Accept': 'application/vnd.docker.distribution.manifest.v2+json'})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            digest = response.headers.get('Docker-Content-Digest', '')
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
            raise ValueError('registry returned an invalid digest')
        with urllib.request.urlopen(urllib.request.Request(base + digest, method='DELETE'), timeout=10):
            pass
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise ValueError('registry deletion failed') from None


def publish(root, rows, args):
    tool, release = identifier(args.tool), identifier(args.release)
    path = root / (tool + '.' + release + '.json')
    archive = args.archive
    info = archive.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) & 0o077 or not 0 < info.st_size <= 500 * 1024 * 1024):
        raise ValueError('archive must be a private operator-owned regular file, at most 500 MiB')
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    existing = next((row for candidate, row in rows if candidate == path), None)
    if existing:
        if existing['archive_sha256'] != digest or existing['state'] == 'retired':
            raise ValueError('release identity is immutable; use a new release ID')
        if existing['state'] == 'retained':
            return existing
    else:
        live = [row for _, row in rows if row['state'] != 'retired']
        if (len(rows) >= 256 or len({row['tool'] for row in live} | {tool}) > 30
                or sum(row['tool'] == tool for row in live) >= 2):
            raise ValueError('retain at most thirty apps and current plus candidate/previous release')
    require_space(root)
    row = {'tool': tool, 'release': release, 'archive_sha256': digest,
           'state': 'pending', 'changed_at': time.time()}
    write_record(path, row)
    with tempfile.TemporaryDirectory(dir=root, prefix='.publish-') as temporary:
        digest_path = Path(temporary) / 'digest'
        command('skopeo', 'copy', '--quiet', '--dest-tls-verify=false', '--format=v2s2',
                '--digestfile', str(digest_path), 'docker-archive:' + str(archive.resolve()),
                'docker://127.0.0.1:5000/' + repository(row) + ':release')
        manifest = digest_path.read_text().strip()
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', manifest):
            raise ValueError('registry copy did not produce a valid manifest digest')
    row.update(state='retained', digest=manifest, changed_at=time.time())
    write_record(path, row)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/srv/small-cloud/releases'))
    commands = parser.add_subparsers(dest='command', required=True)
    new = commands.add_parser('publish')
    new.add_argument('tool', metavar='app'); new.add_argument('release'); new.add_argument('archive', type=Path)
    retire = commands.add_parser('retire')
    retire.add_argument('tool', metavar='app'); retire.add_argument('release')
    commands.add_parser('list'); commands.add_parser('prune')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('requires root on the trusted control host')
    os.umask(0o077)
    args.root.mkdir(mode=0o700, exist_ok=True)
    info = args.root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('release inventory must be a private operator-owned directory')
    with (args.root / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = records(args.root)
        if args.command == 'publish':
            result = publish(args.root, rows, args)
        elif args.command == 'retire':
            identity = (identifier(args.tool), identifier(args.release))
            for path, row in rows:
                if (row['tool'], row['release']) == identity and row['state'] != 'retired':
                    row.update(state='retired', changed_at=time.time())
                    write_record(path, row)
            result = {'retired': True}
        elif args.command == 'list':
            result = {'releases': [row for _, row in rows]}
        else:
            expired = [(path, row) for path, row in rows if row['state'] != 'retained'
                       and time.time() - row['changed_at'] >= GRACE]
            for _, row in expired:
                remove_manifest(row)
            if expired:
                # Writers share this lock; registry GC must run while the server is stopped.
                try:
                    command('systemctl', 'stop', 'docker-registry.service')
                    command('docker-registry', 'garbage-collect', '/etc/docker/registry/config.yml')
                finally:
                    command('systemctl', 'start', 'docker-registry.service')
                for path, _ in expired:
                    path.unlink()
            result = {'removed': len(expired)}
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('Release operation failed; inspect private inventory and registry health.', file=sys.stderr)
        sys.exit(1)
