"""Agent-callable Small Cloud CLI. Never prints credential or provider-token values."""
import getpass
import json
import re
import ssl
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import uuid
import webbrowser
import warnings

import certifi

from .common import Failure, envelope, origin
from .credentials import Credentials
from .google import NoRedirect


from .commands import parser, help_parser, catalog, guide
from .render import human, human_error

SERVICE_ORIGIN = 'https://small-cloud.monkeysees.one'


def global_first(argv):
    flags, rest, index = [], [], 0
    while index < len(argv):
        arg = argv[index]
        if arg in ('--json', '--no-input', '--no-color', '--version'):
            flags.append(arg)
        elif arg in ('--request-id', '--workspace'):
            if index + 1 >= len(argv):
                raise Failure('INVALID_ARGUMENT', 'Missing global flag value.')
            flags.extend(argv[index:index + 2])
            index += 1
        elif arg.startswith(('--request-id=', '--workspace=')):
            flags.append(arg)
        else:
            rest.append(arg)
        index += 1
    return flags + rest


class Client:
    def __init__(self, endpoint, workspace=None):
        self.endpoint = endpoint
        self.workspace = workspace
        context = ssl.create_default_context()
        # Frozen Python's build-time CA paths may not exist on the user's machine.
        context.load_verify_locations(certifi.where())
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))

    def select_workspace(self, token):
        identity = self.request('/api/auth/status', token=token)
        self.workspace = identity['workspace']['id']

    def request(self, path, body=None, token=None, request_id=None, timeout=30):
        headers = {'Content-Type': 'application/x-tar' if isinstance(body, bytes) else 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
            if self.workspace is not None:
                headers['X-Workspace'] = urllib.parse.quote(self.workspace, safe='')
        if request_id:
            headers['X-Request-ID'] = request_id
        request = urllib.request.Request(self.endpoint + path,
                   data=None if body is None else body if isinstance(body, bytes) else json.dumps(body).encode(), headers=headers)
        try:
            try:
                response = self.opener.open(request, timeout=timeout)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                raw = response.read(1048577)
                if len(raw) > 1048576:
                    raise ValueError('Oversized response')
                result = json.loads(raw)
            if result['schema_version'] != 1:
                raise ValueError('Unsupported schema')
            if not result['ok']:
                error = result['error']
                raise Failure(error['code'], error['message'], int(response.code), **error['details'])
            return result['data']
        except (OSError, ValueError, KeyError):
            raise Failure('NETWORK_ERROR', 'Platform request failed; retry with the same request ID.', 503) from None


def execute(args, request_id, service_origin):
    if args.command == 'catalog':
        return catalog(args.query)
    if args.command == 'guide':
        return guide(args.topic)
    if args.command == 'deploy':
        from .upload import package
        if (not re.fullmatch(r'[a-z][a-z0-9-]{0,62}', args.name)
                or args.description is not None and len(args.description) > 500
                or args.timeout <= 0):
            raise Failure('INVALID_ARGUMENT', 'Supply a valid app name, description up to 500 characters and positive timeout.')
        summary, archive = package(args.folder)
        if args.dry_run:
            return summary
        client = Client(service_origin, args.workspace)
        credentials = Credentials(client.endpoint)
        with credentials.locked():
            token = credentials.read()
            client.select_workspace(token)
            metadata = {'name': args.name}
            if args.description is not None:
                metadata['description'] = args.description
            print('Uploading validated source...', file=sys.stderr, flush=True)
            result = client.request('/api/deploy?' + urllib.parse.urlencode(metadata), archive, token, request_id)
            if not args.wait:
                return result
            started = time.monotonic()
            deadline = started + args.timeout
            last_state, last_report = 'accepted', started
            print('Deployment: accepted (0s elapsed).', file=sys.stderr, flush=True)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Failure('WAIT_TIMEOUT', 'Deployment continues; inspect its operation status.', 503,
                                  operation_id=result['operation_id'])
                operation = client.request('/api/operations/' + urllib.parse.quote(result['operation_id'], safe=''),
                                           token=token, timeout=min(30, remaining))
                now = time.monotonic()
                state = operation['state']
                if state != last_state or now - last_report >= 15:
                    label = state if state in ('accepted', 'building', 'starting', 'cleaning', 'succeeded', 'failed') else 'waiting'
                    print(f'Deployment: {label} ({int(now - started)}s elapsed).', file=sys.stderr, flush=True)
                    last_state, last_report = state, now
                if operation['state'] == 'succeeded':
                    return {**result, 'state': 'succeeded', 'active_deployment_id': operation['deployment_id']}
                if operation['state'] == 'failed':
                    error = operation['error']
                    code = error['code']
                    raise Failure(code, error['message'], 409 if code == 'ACTIVE_CAPACITY' else 500,
                                  operation_id=result['operation_id'])
                time.sleep(min(2, max(0, deadline - time.monotonic())))
    client = Client(service_origin, args.workspace)
    credentials = Credentials(client.endpoint)
    with credentials.locked():
        return authenticated_command(args, request_id, client, credentials)


def authority_request(args, client, path, body, token, request_id):
    if getattr(args, 'acknowledge_secret_authority', False):
        body['acknowledge_secret_authority'] = True
    try:
        return client.request(path, body, token, request_id)
    except Failure as error:
        if error.code != 'ACKNOWLEDGEMENT_REQUIRED' or args.no_input or args.json or not sys.stdin.isatty():
            raise
        print(error.message, file=sys.stderr)
        print('Acknowledge this authority? Type yes: ', end='', file=sys.stderr, flush=True)
        if input() != 'yes':
            raise error
        body['acknowledge_secret_authority'] = True
        return client.request(path, body, token, request_id)


def authenticated_command(args, request_id, client, credentials):
    if args.action in ('login', 'login-start', 'login-finish'):
        from .login import start, finish
        if args.action == 'login-finish':
            return setup_status(finish(client, credentials, args.attempt_id, args.timeout), client.endpoint)
        login = start(client, credentials, request_id)
        if args.action == 'login-start':
            return login
        url = login['verification_url']
        print(f'Open {url} and verify code {login["user_code"]}', file=sys.stderr, flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        return setup_status(finish(client, credentials, login['attempt_id']), client.endpoint)
    if args.command == 'auth' and args.action == 'status':
        try:
            return setup_status(client.request('/api/auth/status', token=credentials.read()), client.endpoint)
        except Failure as error:
            error.details.update(service_endpoint=client.endpoint, user=None, workspace=None,
                                 missing_steps=[error.message],
                                 next_steps=['small-cloud auth login start --json'] if error.code in
                                 ('AUTH_REQUIRED', 'CREDENTIAL_REVOKED') else ['Resolve the reported error and retry small-cloud auth status --json.'])
            raise
    token = credentials.read()
    if args.command == 'workspace':
        if args.action == 'list':
            return client.request('/api/workspaces', token=token)
        body = ({'name': args.name, 'owner_email': args.owner} if args.action == 'create'
                else {'workspace': args.target})
        return client.request('/api/workspaces/' + args.action, body, token, request_id)
    if args.command != 'auth':
        client.select_workspace(token)
    if args.command == 'usage':
        return client.request('/api/usage', token=token)
    if args.command == 'directory':
        return client.request('/api/directory', token=token)
    if args.command == 'secret':
        from .app_secrets import validate
        path = '/api/apps/' + urllib.parse.quote(args.app, safe='') + '/secrets'
        if args.action == 'list':
            return client.request(path, token=token)
        validate(args.name)
        if args.timeout <= 0:
            raise Failure('INVALID_ARGUMENT', 'Timeout must be positive.')
        body = {'name': args.name}
        if args.action == 'set':
            if args.stdin:
                raw = sys.stdin.buffer.read(16385)
                try:
                    value = raw.decode('utf-8')
                except UnicodeDecodeError:
                    raise Failure('INVALID_ARGUMENT', 'Secret input must be UTF-8.') from None
            elif args.no_input or args.json or not sys.stdin.isatty():
                raise Failure('INVALID_ARGUMENT', 'Use --stdin or an interactive hidden prompt for the value.')
            else:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter('error', getpass.GetPassWarning)
                        value = getpass.getpass('Secret value: ')
                except getpass.GetPassWarning:
                    raise Failure('INVALID_ARGUMENT', 'Cannot hide terminal input; use --stdin.') from None
            validate(args.name, value)
            body['value'] = value
        result = authority_request(args, client, path + '/' + args.action, body, token, request_id)
        if not args.wait or not result['changed']:
            return result
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            operation = client.request('/api/operations/' + result['operation_id'], token=token,
                                       timeout=min(30, max(.01, deadline - time.monotonic())))
            if operation['state'] == 'succeeded':
                return {**result, 'state': 'succeeded'}
            if operation['state'] == 'failed':
                error = operation['error']
                raise Failure(error['code'], error['message'], 500, **error['details'])
            time.sleep(min(2, max(0, deadline - time.monotonic())))
        raise Failure('WAIT_TIMEOUT', 'Secret change continues; inspect its operation status.', 503,
                      operation_id=result['operation_id'])
    if args.command == 'share':
        return authority_request(args, client, '/api/apps/' + urllib.parse.quote(args.app, safe='') + '/share',
                                 {'scope': args.scope}, token, request_id)
    if args.command == 'status':
        return client.request('/api/apps/' + urllib.parse.quote(args.app, safe=''), token=token)
    if args.command == 'operation':
        if bool(args.id) == bool(request_id):
            raise Failure('INVALID_ARGUMENT', 'Supply an operation ID or --request-id, exclusively.')
        path = ('/api/operations/' + urllib.parse.quote(args.id, safe='') if args.id
                else '/api/operations?request_id=' + request_id)
        return client.request(path, token=token)
    if args.command == 'logs':
        if not 1 <= args.limit <= 1000:
            raise Failure('INVALID_ARGUMENT', 'Log limit must be between 1 and 1000.')
        query = {'source': args.source, 'limit': str(args.limit)}
        if args.deployment:
            query['deployment'] = args.deployment
        if args.since:
            query['since'] = args.since
        if args.cursor:
            query['cursor'] = args.cursor
        if args.source == 'runtime' and args.deployment:
            raise Failure('INVALID_ARGUMENT', 'Deployment applies only to build logs.')
        return client.request('/api/apps/' + urllib.parse.quote(args.app, safe='') + '/logs?'
                              + urllib.parse.urlencode(query), token=token)
    if args.command == 'admin':
        body = {'email': args.email} if args.resource == 'member' else {'user_id': args.user_id}
        return client.request('/api/admin/' + args.resource + '/' + args.action, body, token, request_id)
    try:
        result = client.request('/api/auth/' + args.action, {}, token, request_id)
    except Failure as error:
        if error.code == 'NETWORK_ERROR':
            command = 'small-cloud auth ' + args.action + (' --all' if args.action == 'revoke' else '')
            error.details['next_command'] = command + ' --request-id ' + request_id + ' --json'
        raise
    credentials.remove()
    return result


def setup_status(identity, endpoint):
    missing = []
    if not identity.get('workspace'):
        missing.append('Select an accessible workspace using workspace list and workspace select ID.')
    elif 'creator' not in identity['roles']:
        missing.append('To publish, ask a workspace administrator for creator privileges using your user ID.')
    return {**identity, 'service_endpoint': endpoint, 'missing_steps': missing,
            'next_steps': ['small-cloud app list --json'] if identity.get('workspace') else ['small-cloud workspace list --json']}


def main(argv=None, *, service_origin=SERVICE_ORIGIN):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_mode, request_id = '--json' in argv, None
    try:
        parsers, children = parser()
        root = parsers['']
        if not argv or '-h' in argv or '--help' in argv:
            help_parser(argv, parsers, children).print_help()
            return 0
        args = root.parse_args(global_first(argv))
        if args.command in ('catalog', 'guide') or getattr(args, 'dry_run', False):
            request_id = None
        elif args.request_id:
            request_id = str(uuid.UUID(args.request_id))
        elif args.action not in ('status', 'logs', 'directory', 'usage', 'list') and not getattr(args, 'dry_run', False):
            request_id = str(uuid.uuid4())
        if request_id:
            print('Request ID: ' + request_id, file=sys.stderr, flush=True)
        result = envelope(execute(args, request_id, origin(service_origin)), request_id=request_id)
        print(json.dumps(result) if json_mode else human(result['data'], args.command_path))
        return 0
    except Failure as exc:
        print(json.dumps(envelope(failure=exc, request_id=request_id)) if json_mode else human_error(exc, request_id),
              file=sys.stdout if json_mode else sys.stderr)
        return 130 if exc.code == 'INTERRUPTED' else exc.exit_code
    except KeyboardInterrupt:
        exc = Failure('INTERRUPTED', 'Interrupted.', 500)
        print(json.dumps(envelope(failure=exc, request_id=request_id)) if json_mode else human_error(exc, request_id),
              file=sys.stdout if json_mode else sys.stderr)
        return 130
    except (OSError, ValueError, KeyError):
        exc = Failure('INVALID_ARGUMENT', 'Cannot read configuration or credential storage.')
        print(json.dumps(envelope(failure=exc, request_id=request_id)) if json_mode else human_error(exc, request_id),
              file=sys.stdout if json_mode else sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
