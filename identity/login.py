"""Browser approval with protected, origin-bound cross-process pending state."""
import json
import os
import re
import secrets
import time
import uuid

from .common import Failure, digest, read_private, timestamp


def attempt_path(credentials, attempt_id):
    if not re.fullmatch(r'[0-9a-f]{32}', attempt_id):
        raise Failure('INVALID_ARGUMENT', 'Use the attempt_id returned by small-cloud auth login start.')
    return credentials.directory / (digest(credentials.endpoint) + '.login-' + attempt_id)


def start(client, credentials, request_id):
    poll_secret = secrets.token_urlsafe(32)
    created = time.time()
    try:
        login = client.request('/api/auth/login', {'poll_secret': poll_secret}, request_id=request_id)
    except Failure as error:
        error.details['next_command'] = 'small-cloud auth login start --json'
        raise
    if not login['verification_url'].startswith(client.endpoint + '/auth/verify?'):
        raise Failure('NETWORK_ERROR', 'Invalid verification origin.', 503)
    expires_in = max(0, min(login['expires_in'], 600))
    attempt_id = uuid.uuid4().hex
    pending = {'endpoint': client.endpoint, 'poll_secret': poll_secret,
               'expires_at': created + expires_in, 'interval': max(5, min(login['interval'], 60))}
    path = attempt_path(credentials, attempt_id)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(pending, stream)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink()
        raise
    return {'verification_url': login['verification_url'], 'user_code': login['user_code'],
            'attempt_id': attempt_id, 'expires_in': expires_in, 'expires_at': timestamp(pending['expires_at'])}


def finish(client, credentials, attempt_id, timeout=600):
    if timeout <= 0:
        raise Failure('INVALID_ARGUMENT', 'Timeout must be positive.')
    path = attempt_path(credentials, attempt_id)
    try:
        pending = read_private(path)
    except FileNotFoundError:
        raise Failure('LOGIN_EXPIRED', 'Login attempt is absent or already used; run small-cloud auth login start.', 401,
                      next_command='small-cloud auth login start --json') from None
    if pending['endpoint'] != client.endpoint:
        raise Failure('INVALID_ARGUMENT', 'Login attempt belongs to a different endpoint.')
    remaining = pending['expires_at'] - time.time()
    expires = time.monotonic() + remaining
    deadline = min(expires, time.monotonic() + timeout)
    interval = max(5, min(pending['interval'], 60))
    recovery = {'attempt_id': attempt_id,
                'next_command': 'small-cloud auth login finish ' + attempt_id + ' --json'}
    try:
        while time.monotonic() < deadline:
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
            if time.monotonic() >= deadline:
                break
            result = client.request('/api/auth/poll', {'poll_secret': pending['poll_secret']},
                                    timeout=min(30, max(.01, deadline - time.monotonic())))
            if result.get('state') == 'complete':
                token = result.pop('credential')
                result.pop('state')
                try:
                    credentials.write(token)
                except (Exception, KeyboardInterrupt) as error:
                    revocation = 'revoked'
                    try:
                        client.request('/api/auth/logout', {}, token, str(uuid.uuid4()))
                    except (Exception, KeyboardInterrupt):
                        revocation = 'unconfirmed'
                    if not isinstance(error, Failure):
                        error = (Failure('INTERRUPTED', 'Interrupted while saving the delivered credential.', 500)
                                 if isinstance(error, KeyboardInterrupt) else
                                 Failure('INTERNAL', 'Cannot save the delivered credential.', 500))
                    error.details.update(next_command='small-cloud auth login start --json',
                                         credential_revocation=revocation)
                    if revocation == 'unconfirmed':
                        error.details['next_steps'] = ['After signing in again, run small-cloud auth revoke --all to revoke any undelivered credential.']
                    raise error
                finally:
                    path.unlink()
                return result
            interval = max(5, min(result.get('interval', 5), 60))
        if time.monotonic() >= expires:
            raise Failure('LOGIN_EXPIRED', 'Login expired; run small-cloud auth login start.', 401)
        raise Failure('WAIT_TIMEOUT', 'Browser approval is still pending; finish this attempt again.', 503, **recovery)
    except KeyboardInterrupt:
        raise Failure('INTERRUPTED', 'Stopped waiting; the login attempt remains available until expiry.', 500, **recovery) from None
    except Failure as error:
        if error.code == 'LOGIN_EXPIRED':
            path.unlink(missing_ok=True)
            error.details['next_command'] = 'small-cloud auth login start --json'
        elif error.code == 'NETWORK_ERROR' and path.exists():
            error.details.update(recovery)
        raise
