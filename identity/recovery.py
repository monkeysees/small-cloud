"""Read-only deployment diagnosis using the caller's existing log authority."""
import shlex
import time
import urllib.parse

from .common import Failure
from .completion import inspection, read_before_deadline, uncertain_recovery


def deployment_recovery(client, token, operation):
    details = inspection(operation['request_id'], client.workspace, operation['operation_id'])
    error = operation.get('error') or {}
    reconciliation = error.get('details', {}).get('reconciliation_required', False)
    if operation['state'] != 'failed' and not reconciliation:
        return {**details, **uncertain_recovery()}
    phase = error.get('details', {}).get('failed_phase')
    if phase is None:
        phase = {'BUILD_FAILED': 'building', 'STARTUP_FAILED': 'starting'}.get(error.get('code', ''), 'unknown')
    source = 'runtime' if phase == 'starting' else 'build'
    app = operation['app']
    query = {'source': source, 'limit': '1000', 'tail': 'true'}
    flags = ['--source', source, '--tail']
    if source == 'build':
        query['deployment'] = operation['deployment_id']
        flags += ['--deployment', operation['deployment_id']]
    else:
        query['since'] = operation['created_at']
        flags += ['--since', operation['created_at']]
    suffix = ['--workspace', client.workspace, '--json']
    details.update(failed_phase=phase, next_steps=[
        shlex.join(['small-cloud', 'app', 'status', app, *suffix]),
        shlex.join(['small-cloud', 'app', 'logs', app, *flags, '--limit', '100', *suffix])])
    diagnostics = {'source': source, 'deployment_id': operation['deployment_id'], 'entries': []}
    try:
        snapshot = read_before_deadline(client, token,
            '/api/apps/' + urllib.parse.quote(app, safe='') + '/logs?' + urllib.parse.urlencode(query),
            time.monotonic() + 3)
        entries = [entry for entry in snapshot['entries']
                   if entry['deployment_id'] == operation['deployment_id']]
        excerpt, remaining = [], 4096
        for entry in reversed(entries[-20:]):
            message = entry['message'][-remaining:]
            excerpt.insert(0, {**entry, 'message': message})
            remaining -= len(message)
            if remaining == 0:
                break
        diagnostics.update(status='available' if excerpt else 'empty', entries=excerpt,
            truncated=snapshot['truncated'] or len(excerpt) < len(entries)
                      or sum(len(entry['message']) for entry in entries) > 4096,
            collection_interrupted=snapshot['collection_interrupted'],
            dropped_bytes=snapshot['dropped_bytes'], oldest_available_at=snapshot['oldest_available_at'],
            next_cursor=snapshot['next_cursor'])
        if diagnostics['truncated']:
            diagnostics['status'] = 'partial'
    except (Failure, TimeoutError, KeyboardInterrupt, ValueError, KeyError, TypeError) as error:
        diagnostics.update(status='unavailable', error_code=error.code if isinstance(error, Failure)
                           else 'INTERRUPTED' if isinstance(error, KeyboardInterrupt)
                           else 'WAIT_TIMEOUT' if isinstance(error, TimeoutError) else 'INVALID_RESPONSE')
    details['diagnostics'] = diagnostics
    details['guidance'] = 'Inspect the original operation and diagnostics before deciding on a new deployment. No source or data repair was performed.'
    details['operator_escalation'] = None
    if diagnostics.get('collection_interrupted') or diagnostics['status'] == 'unavailable':
        details['operator_escalation'] = ('If diagnostics remain unavailable or collection is interrupted, contact the platform operator '
                                          'with these request, operation and workspace IDs. Missing logs do not establish success.')
    if diagnostics.get('error_code') in ('NOT_FOUND', 'FORBIDDEN', 'AUTH_REQUIRED', 'CREDENTIAL_REVOKED'):
        details['guidance'] = 'Diagnostic access is unavailable. Sign in if needed and ask a workspace administrator to verify access, then inspect the same operation.'
        details['operator_escalation'] = None
    if reconciliation:
        details.update(uncertain_recovery())
        details['operator_escalation'] = 'Contact the platform operator with these request, operation and workspace IDs. The service requires reconciliation before another deployment.'
    return details
