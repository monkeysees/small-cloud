"""Origin-bound OS keyring storage with an owner-only file fallback."""
import json
import os
from pathlib import Path
import tempfile
import fcntl
from contextlib import contextmanager

import keyring

from .common import Failure, digest, protected_directory, read_private, validate_private_file


class Credentials:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        base = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state')))
        if not base.is_absolute():
            raise Failure('INVALID_ARGUMENT', 'XDG_STATE_HOME must be an absolute path.')
        directory = base / 'small-cloud'
        resolved = directory.resolve()
        if any((parent / '.git').exists() or (parent / 'Dockerfile').is_file()
               for parent in (resolved, *resolved.parents)):
            raise Failure('INVALID_ARGUMENT', 'Credential storage must be outside the source folder.')
        self.directory = protected_directory(directory)
        self.path = self.directory / (digest(endpoint) + '.json')
        self.backend = None
        candidate = keyring.get_keyring()
        # Only OS stores qualify; third-party plaintext/chainer backends never do.
        if type(candidate).__module__ in ('keyring.backends.SecretService', 'keyring.backends.macOS', 'keyring.backends.Windows'):
            self.backend = candidate

    @contextmanager
    def locked(self):
        path = self.path.with_suffix('.lock')
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            validate_private_file(fd)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Failure('OPERATION_CONFLICT', 'Another CLI command is using this credential.', 409) from None
            yield
        finally:
            os.close(fd)

    def read(self):
        try:
            data = read_private(self.path)
        except FileNotFoundError:
            raise Failure('AUTH_REQUIRED', 'Sign in with small-cloud auth login.', 401) from None
        if data.get('endpoint') != self.endpoint:
            raise Failure('AUTH_REQUIRED', 'Credential belongs to a different endpoint.', 401)
        if data.get('storage') == 'keyring':
            if self.backend is None:
                raise Failure('AUTH_REQUIRED', 'Unlock the OS credential store and retry.', 401)
            try:
                token = self.backend.get_password('small-cloud', self.endpoint)
            except Exception:
                raise Failure('AUTH_REQUIRED', 'Unlock the OS credential store and retry.', 401) from None
        else:
            token = data.get('credential')
        if not isinstance(token, str) or not token:
            raise Failure('AUTH_REQUIRED', 'No saved credential is available.', 401)
        return token

    def write(self, token):
        if self.path.exists() or self.path.is_symlink():
            read_private(self.path)
        data = {'endpoint': self.endpoint, 'storage': 'file', 'credential': token}
        if self.backend is not None:
            try:
                self.backend.set_password('small-cloud', self.endpoint, token)
                data = {'endpoint': self.endpoint, 'storage': 'keyring'}
            except Exception:
                raise Failure('INTERNAL', 'Cannot save to the OS credential store; unlock it and retry.', 500) from None
        fd, temporary = tempfile.mkstemp(prefix='.credential-', dir=self.directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def remove(self):
        data = read_private(self.path)
        if data.get('storage') == 'keyring':
            if self.backend is None:
                raise Failure('INTERNAL', 'Cannot remove credential from locked OS store.', 500)
            try:
                self.backend.delete_password('small-cloud', self.endpoint)
            except Exception:
                raise Failure('INTERNAL', 'Cannot remove credential from OS store.', 500) from None
        self.path.unlink()
