#!/usr/bin/env python3
"""Prune only marked operator build staging files; never traverse caller directories."""
import argparse
import json
import math
import os
import re
import shutil
from pathlib import Path
import stat
import sys
import time

MARKER = '.small-cloud-build.json'
ARTIFACTS = ('image.tar', 'source.tar')
DIAGNOSTICS = ('admission.log', 'builder.json', 'build.log', 'daemon.log', 'result.json', 'teardown.json', 'resources.json', 'accounting.json')
MAX_JOB_ENTRIES = 64
MAX_MARKER_BYTES = 4096


def require_space(path: Path) -> None:
    if shutil.disk_usage(path).free < 10 * 1024 ** 3:
        raise ValueError('control storage pressure: require 10 GiB free before admitting new work')


def owned_directory(path: Path) -> None:
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ValueError('staging directory must be owned by the operator with mode 0700')


def bounded_entries(path: Path, limit: int) -> list[Path]:
    entries = []
    with os.scandir(path) as scanner:
        for entry in scanner:
            if len(entries) == limit:
                raise ValueError('staging entry scan limit exceeded')
            entries.append(path / entry.name)
    return entries


def prune_job(job: Path, now: float) -> list[str]:
    owned_directory(job)
    entries = bounded_entries(job, MAX_JOB_ENTRIES)
    metadata = {path.name: path.lstat() for path in entries}
    if any(stat.S_ISLNK(value.st_mode) or (stat.S_ISREG(value.st_mode) and value.st_nlink != 1)
           for value in metadata.values()):
        raise ValueError('staging links are refused')
    if MARKER not in metadata:
        return []
    # Validate every deletable entry before removing any file from this job.
    for name in (MARKER, *ARTIFACTS, *DIAGNOSTICS):
        value = metadata.get(name)
        if value and (not stat.S_ISREG(value.st_mode) or value.st_uid != os.getuid()
                      or stat.S_IMODE(value.st_mode) & 0o077 or value.st_nlink != 1):
            raise ValueError('managed files must be private operator-owned regular files without links')
    descriptor = os.open(job / MARKER, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        payload = stream.read(MAX_MARKER_BYTES + 1)
    if len(payload) > MAX_MARKER_BYTES:
        raise ValueError('marker exceeds bounded metadata size')
    created = json.loads(payload)['created_at']
    if isinstance(created, bool) or not isinstance(created, (int, float)) or not math.isfinite(created) or not 0 <= created <= now:
        raise ValueError('invalid marker creation timestamp')
    age = now - created
    names: list[str] = list(ARTIFACTS) if age >= 23 * 3600 else []
    if age >= 7 * 86400:
        names.extend((*DIAGNOSTICS, MARKER))
    removed = []
    for name in names:
        if name in metadata:
            (job / name).unlink()
            removed.append(name)
    # Unknown files and directories, including original caller contexts, remain untouched.
    if age >= 7 * 86400 and not bounded_entries(job, MAX_JOB_ENTRIES):
        job.rmdir()
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/srv/small-cloud/source'))
    parser.add_argument('--stage', metavar='JOB', help='receive a bounded source archive from stdin into managed staging')
    args = parser.parse_args()
    owned_directory(args.root)
    if args.stage:
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', args.stage):
            raise ValueError('invalid upload job identifier')
        os.umask(0o077)
        require_space(args.root)
        job = args.root / ('upload-' + args.stage)
        job.mkdir(mode=0o700)
        source = job / 'source.tar'
        marker = job / MARKER
        try:
            marker.write_text(json.dumps({'created_at': time.time(), 'job': args.stage}))
            total = 0
            with source.open('xb') as output:
                while chunk := sys.stdin.buffer.read(65536):
                    total += len(chunk)
                    if total > 116 * 1024 * 1024:
                        raise ValueError('source upload exceeds 116 MiB')
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if not total:
                raise ValueError('source upload is empty')
        except BaseException:
            source.unlink(missing_ok=True)
            marker.unlink(missing_ok=True)
            job.rmdir()
            raise
        print(json.dumps({'source': str(source), 'bytes': total}))
        return 0
    now = time.time()
    removed = 0
    refused = 0
    # Stream the trusted root so a large backlog cannot disable its own cleanup.
    with os.scandir(args.root) as jobs:
        for entry in jobs:
            try:
                metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(metadata.st_mode):
                    refused += 1
                    continue
                if not stat.S_ISDIR(metadata.st_mode):
                    continue
                removed += len(prune_job(args.root / entry.name, now))
            except (OSError, ValueError, KeyError, TypeError):
                refused += 1
    print(json.dumps({'removed_files': removed, 'refused_jobs': refused}))
    return 1 if refused else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError):
        print('Staging cleanup refused: inspect ownership, links and bounded marker metadata.', file=sys.stderr)
        sys.exit(1)
