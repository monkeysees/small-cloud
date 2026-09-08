"""Shared wire errors and protected local files."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import urllib.parse


class Failure(Exception):
    def __init__(self, code: str, message: str, status: int = 400, **details):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details

    @property
    def exit_code(self):
        if self.code in ('AUTH_REQUIRED', 'CREDENTIAL_REVOKED', 'LOGIN_EXPIRED'):
            return 3
        if self.status == 403 or self.status == 404:
            return 4
        if self.status == 409 or self.status == 429:
            return 5
        if self.code in ('NETWORK_ERROR', 'WAIT_TIMEOUT'):
            return 6
        return 2 if self.status == 400 else 1


def envelope(data=None, failure=None, request_id=None):
    return {'schema_version': 1, 'ok': failure is None, 'request_id': request_id,
            'data': data if failure is None else None,
            'error': None if failure is None else {
                'code': failure.code, 'message': failure.message,
                'retryable': failure.code == 'NETWORK_ERROR', 'details': failure.details}}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')


def origin(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')
            or parsed.netloc != parsed.netloc.lower()):
        raise Failure('INVALID_ARGUMENT', 'Endpoint must be one HTTPS origin.')
    return value.rstrip('/')


def protected_directory(path: Path):
    path = path.absolute()
    for parent in reversed((path, *path.parents)):
        if parent.is_symlink():
            raise Failure('INVALID_ARGUMENT', 'Symlinked credential storage is not permitted.')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise Failure('INVALID_ARGUMENT', 'Credential directory must be owned by you with mode 0700.')
    return path


def validate_private_file(fd: int):
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
        raise Failure('INVALID_ARGUMENT', 'Protected file must be owned by you with mode 0600 and one link.')


def read_private(path: Path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise Failure('INVALID_ARGUMENT', 'Symlinked credential storage is not permitted.')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        validate_private_file(stream.fileno())
        return json.load(stream)
