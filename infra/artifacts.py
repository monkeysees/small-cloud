#!/usr/bin/env python3
"""Prune only marked operator build staging files; never traverse caller directories."""
import argparse
import json
import math
import os
from pathlib import Path
import stat
import sys
import time

MARKER = '.small-cloud-build.json'
ARTIFACTS = ('image.tar', 'source.tar')
DIAGNOSTICS = ('admission.log', 'builder.json', 'build.log', 'daemon.log', 'result.json', 'teardown.json')
MAX_JOB_ENTRIES = 64
MAX_MARKER_BYTES = 4096


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
    names: list[str] = list(ARTIFACTS) if age >= 86400 else []
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
    args = parser.parse_args()
    owned_directory(args.root)
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
