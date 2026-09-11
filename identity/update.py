"""Checksum-verified, atomic replacement of an explicitly invoked standalone CLI."""
import hashlib
import http.client
import io
import os
from pathlib import Path
import platform
import re
import signal
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request

import certifi

from .commands import VERSION
from .common import Failure
from .google import NoRedirect


def download(opener, url, stream, limit, deadline):
    def expired(_signal, _frame):
        raise TimeoutError('Release download exceeded its two-minute time limit.')

    # A socket timeout alone cannot bound slowly delivered HTTP headers.
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, max(.001, deadline - time.monotonic()))
    try:
        return read_download(opener, url, stream, limit, deadline)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def read_download(opener, url, stream, limit, deadline):
    digest, size = hashlib.sha256(), 0
    with opener.open(url, timeout=min(30, max(.01, deadline - time.monotonic()))) as response:
        if response.status != 200:
            raise ValueError('Expected a complete release download (HTTP 200).')
        while chunk := response.read1(65536):
            size += len(chunk)
            if size > limit or time.monotonic() > deadline:
                raise ValueError('Release download exceeded its size or two-minute time limit.')
            stream.write(chunk)
            digest.update(chunk)
        length = response.headers.get('Content-Length')
        if length is not None and size != int(length):
            raise ValueError('Incomplete release download.')
    return digest.hexdigest()


def update(service_origin, executable=None):
    if executable is None:
        if not getattr(sys, 'frozen', False):
            raise Failure('UPDATE_UNSUPPORTED', 'Explicit updates require the standalone executable.',
                          installed_version=VERSION, resulting_version=VERSION,
                          next_command='small-cloud guide updating')
        executable = sys.executable
    destination = Path(executable).resolve()
    details = dict(installed_version=VERSION, resulting_version=VERSION, executable=str(destination),
                   next_command='small-cloud guide updating')
    stage = 'select platform'
    try:
        system = {'Linux': 'linux', 'Darwin': 'macos'}.get(platform.system())
        arch = {'x86_64': 'x86_64', 'amd64': 'x86_64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(platform.machine())
        if not system or not arch:
            raise ValueError('Supported systems are Linux and macOS on x86-64 or ARM64.')
        asset = f'small-cloud-{system}-{arch}'
        base = service_origin + '/cli/releases/latest/' + asset
        context = ssl.create_default_context()
        context.load_verify_locations(certifi.where())
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))
        stage = 'download checksum'
        deadline = time.monotonic() + 120
        checksum_stream = io.BytesIO()
        download(opener, base + '.sha256', checksum_stream, 1024, deadline)
        checksum = checksum_stream.getvalue().decode('ascii')
        match = re.fullmatch(r'([0-9a-f]{64})  ' + re.escape(asset) + r'\n?', checksum)
        if not match:
            raise ValueError('Invalid release checksum.')
        expected = match[1]
        stage = 'read installed executable'
        with destination.open('rb') as stream:
            installed_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        if installed_hash == expected:
            return dict(details, outcome='already_current', next_command='small-cloud --version')
        stage = 'download executable'
        with tempfile.TemporaryDirectory(prefix='.small-cloud-update-', dir=destination.parent,
                                         ignore_cleanup_errors=True) as temporary:
            candidate = Path(temporary) / asset
            with candidate.open('wb') as stream:
                candidate_hash = download(opener, base, stream, 256 * 1024 * 1024, deadline)
                stream.flush()
                os.fsync(stream.fileno())
            if candidate_hash != expected:
                raise ValueError('Checksum mismatch; retry after publication finishes or contact the operator.')
            stage = 'check replacement startup'
            candidate.chmod(0o755)
            probe = subprocess.run([str(candidate), '--version'], stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True, timeout=30,
                                   env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'})
            version = re.fullmatch(r'small-cloud ([0-9]+\.[0-9]+\.[0-9]+)\n?', probe.stdout)
            if probe.returncode or not version:
                raise ValueError('Replacement failed its version/startup check; contact the operator.')
            resulting_version = version[1]
            if tuple(map(int, resulting_version.split('.'))) < tuple(map(int, VERSION.split('.'))):
                raise ValueError('Published release is older than this executable; keep this version or explicitly reinstall a pinned release.')
            stage = 'replace executable'
            with destination.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != installed_hash:
                    raise ValueError('Installation changed during the update; inspect its version before retrying.')
            os.replace(candidate, destination)
        return dict(details, outcome='updated', resulting_version=resulting_version, next_command='small-cloud --version')
    except KeyboardInterrupt:
        raise Failure('INTERRUPTED', 'Update interrupted; inspect the installed version before retrying.', 500,
                      **{**details, 'resulting_version': None, 'next_command': 'small-cloud --version'}) from None
    except (OSError, ValueError, subprocess.SubprocessError, http.client.HTTPException, Failure) as error:
        raise Failure('UPDATE_FAILED', f'Could not {stage}. Existing executable kept. {error}', 500,
                      **details, stage=stage) from None
