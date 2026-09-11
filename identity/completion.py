"""Bounded observation of accepted operations, independent of mutation submission."""
import queue
import shlex
import sys
import threading
import time
import urllib.parse

from .common import Failure


def inspection(request_id, workspace_id, operation_id=None):
    target = [operation_id] if operation_id else ['--request-id', request_id]
    return {'request_id': request_id, 'workspace_id': workspace_id,
            **({'operation_id': operation_id} if operation_id else {}),
            'next_command': shlex.join(['small-cloud', 'operation', 'status', *target,
                                        '--workspace', workspace_id, '--json'])}


def uncertain_recovery():
    return {'reconciliation_required': True,
            'guidance': 'Inspect the original request or operation. Do not submit another deployment while its outcome is unresolved.',
            'operator_escalation': 'If work remains pending or inspection stays unavailable, contact the platform operator with the request, operation and workspace IDs. A publishing worker may be unavailable even when sign-in works.'}


def read_before_deadline(client, token, path, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    responses = queue.Queue()

    def read():
        try:
            response = client.request(path, token=token, timeout=min(30, remaining))
        except Exception as error:
            response = error
        responses.put(response)

    # Socket timeouts only limit inactivity. A daemon read cannot hold the CLI
    # past its deadline when a response trickles in; this thread never mutates.
    threading.Thread(target=read, daemon=True).start()
    try:
        response = responses.get(timeout=max(0, deadline - time.monotonic()))
    except queue.Empty:
        raise TimeoutError from None
    if time.monotonic() >= deadline:
        raise TimeoutError
    if isinstance(response, Exception):
        raise response
    return response


def wait_for_completion(client, token, result, request_id, timeout, label):
    details = inspection(request_id, client.workspace, result['operation_id'])
    started = time.monotonic()
    deadline = started + timeout
    state, last_report = 'accepted', started
    last_error = None
    try:
        print(f'{label}: accepted (0s elapsed).', file=sys.stderr, flush=True)
        while True:
            try:
                operation = read_before_deadline(client, token,
                    '/api/operations/' + urllib.parse.quote(result['operation_id'], safe=''), deadline)
            except Failure as error:
                if error.code != 'NETWORK_ERROR':
                    raise
                now = time.monotonic()
                if last_error is None or now - last_report >= 15:
                    print(f'{label}: connection unavailable ({int(now - started)}s elapsed); observing the same operation until timeout.',
                          file=sys.stderr, flush=True)
                    last_report = now
                last_error = {'code': error.code, 'message': 'Operation status is temporarily unavailable.'}
                time.sleep(min(2, max(0, deadline - time.monotonic())))
                continue
            last_error = None
            now = time.monotonic()
            previous, state = state, operation['state']
            if state != previous or now - last_report >= 15:
                phase = state if state in ('accepted', 'building', 'starting', 'cleaning', 'succeeded', 'failed') else 'waiting'
                print(f'{label}: {phase} ({int(now - started)}s elapsed).', file=sys.stderr, flush=True)
                last_report = now
            if state == 'succeeded':
                return operation
            if state == 'failed' or (operation.get('error') or {}).get('details', {}).get('reconciliation_required'):
                from .recovery import deployment_recovery
                error = operation['error']
                raise Failure(error['code'], error['message'],
                              409 if error['code'] == 'ACTIVE_CAPACITY' else 500,
                              **{**error['details'], **deployment_recovery(client, token, operation)})
            time.sleep(min(2, max(0, deadline - time.monotonic())))
    except TimeoutError:
        raise Failure('WAIT_TIMEOUT', 'Observation timed out; accepted work continues. Inspect before retrying.', 503,
                      **details, **uncertain_recovery(), state=state, work_continues=True,
                      **({'last_observation_error': last_error} if last_error else {})) from None
    except KeyboardInterrupt:
        continuing = state not in ('succeeded', 'failed')
        message = ('Observation interrupted; accepted work continues. Inspect before retrying.' if continuing
                   else 'Observation interrupted after completion. Inspect the operation result.')
        raise Failure('INTERRUPTED', message, 500,
                      **details, **(uncertain_recovery() if continuing else {}), state=state, work_continues=continuing,
                      **({'last_observation_error': last_error} if last_error else {})) from None
    except Failure as error:
        error.details.update(details, state=state, work_continues=state not in ('succeeded', 'failed'))
        if state not in ('succeeded', 'failed'):
            for key, value in uncertain_recovery().items():
                error.details.setdefault(key, value)
        if last_error:
            error.details['last_observation_error'] = last_error
        raise
