"""Terminal-safe human results; JSON continues to use the wire envelope."""
import unicodedata


def safe(value):
    text = str(value)
    return ''.join(char if not unicodedata.category(char).startswith('C') else
                   f'\\u{ord(char):04x}' for char in text)


def human(data, command):
    if command == 'app list':
        if not data['apps']:
            return 'No accessible apps. Ask your workspace administrator for access or a creator to share an app.'
        return '\n\n'.join(f"{safe(app['name'])} — {safe(app['description'])}\n"
                           f"  Creator: {safe(app['creator']['name'])} ({safe(app['creator']['id'])})\n"
                           f"  URL: {safe(app['url'])}" for app in data['apps'])
    if command == 'app status':
        operation = data['latest_operation']
        result = [f"App: {safe(data['app'])}", f"Description: {safe(data['description'])}",
                  f"URL: {safe(data['url'])}", f"Sharing: {safe(data['sharing_scope'])}",
                  f"Availability: {safe(data['availability'])}",
                  f"Active deployment: {safe(data['active_deployment_id'] or 'none')}"]
        if operation:
            result += [f"Operation: {safe(operation['id'])} ({safe(operation['state'])})",
                       f"Inspect: small-cloud operation status {safe(operation['id'])} --json"]
        else:
            result.append('Operation: none')
        result.append('Cleanup: ' + safe(data['cleanup'] or 'none reported'))
        if operation and operation.get('cleanup_pending'):
            result.append('Operation cleanup: pending')
        if data.get('runtime_error'):
            result.append('Runtime error: ' + fields(data['runtime_error']))
        return '\n'.join(result)
    if command == 'guide' and 'content' in data:
        return data['content']
    return fields(data)


def fields(value, indent=0):
    if isinstance(value, dict):
        return '\n'.join(' ' * indent + safe(key.replace('_', ' ').capitalize()) + ': ' +
                         ('\n' + fields(item, indent + 2) if isinstance(item, (dict, list)) else scalar(item))
                         for key, item in value.items())
    if isinstance(value, list):
        return '\n'.join(' ' * indent + '- ' + fields(item, indent + 2) for item in value) or ' ' * indent + '(none)'
    return scalar(value)


def scalar(value):
    if value is None:
        return 'none'
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    return safe(value)


def human_error(error, request_id=None):
    hints = {
        'AUTH_REQUIRED': 'Run small-cloud auth login, then small-cloud auth status --json.',
        'CREDENTIAL_REVOKED': 'Run small-cloud auth login to sign in again.',
        'LOGIN_EXPIRED': 'Run small-cloud auth login to start a new approval.',
        'NOT_FOUND': 'Check accessible names with small-cloud app list; status requires the creator or a workspace administrator.',
        'FORBIDDEN': 'Run small-cloud auth status --json to check roles; ask your workspace administrator for the required access.',
        'NETWORK_ERROR': 'Check the connection and endpoint. Inspect accepted work before retrying a mutation.',
    }
    result = safe(error.code) + ': ' + safe(error.message)
    if error.code in hints:
        result += '\n' + hints[error.code]
    if error.details.get('operation_id'):
        result += '\nInspect: small-cloud operation status ' + safe(error.details['operation_id']) + ' --json'
    elif request_id and error.code in ('NETWORK_ERROR', 'WAIT_TIMEOUT'):
        result += '\nInspect: small-cloud operation status --request-id ' + safe(request_id) + ' --json'
    return result
