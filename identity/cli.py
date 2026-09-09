"""Agent-callable Small Cloud CLI. Never prints credential or provider-token values."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import uuid
import webbrowser

from .common import Failure, envelope, origin
from .credentials import Credentials
from .google import NoRedirect


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Failure('INVALID_ARGUMENT', message)


def parser():
    root = Parser(prog='small-cloud', description='Small Cloud authentication and workspace admission.',
                  epilog='Example: small-cloud --endpoint https://cloud.example auth login')
    root.add_argument('--json', action='store_true')
    root.add_argument('--no-input', action='store_true')
    root.add_argument('--no-color', action='store_true')
    root.add_argument('--endpoint')
    root.add_argument('--request-id')
    root.add_argument('--version', action='version', version='small-cloud 0.1.0')
    commands = root.add_subparsers(dest='command', required=True)
    usage = commands.add_parser('usage', help='Show publishing capacity and monthly build allowance',
        description='Show counts and build seconds. Each build reserves 600 seconds; fewer than ten remaining minutes cannot admit a build.',
        epilog='Example: small-cloud usage --json')
    usage.set_defaults(action='usage')
    share = commands.add_parser('share', help='Change an app’s sharing scope',
                                epilog='Example: small-cloud share example --scope workspace-wide')
    share.set_defaults(action='share')
    share.add_argument('app')
    share.add_argument('--scope', required=True, choices=('creator-only', 'workspace-wide'))
    directory = commands.add_parser('directory', help='List apps you can access',
                                    epilog='Example: small-cloud directory --json')
    directory.set_defaults(action='directory')
    deploy = commands.add_parser('deploy', help='Publish a local Dockerfile source folder',
                                epilog='Example: small-cloud deploy . --name example --description demo --dry-run')
    deploy.set_defaults(action='deploy')
    deploy.add_argument('folder')
    deploy.add_argument('--name', required=True)
    deploy.add_argument('--description')
    deploy.add_argument('--dry-run', action='store_true')
    deploy.add_argument('--wait', action='store_true')
    deploy.add_argument('--timeout', type=int, default=900)
    status = commands.add_parser('status', help='Show app deployment status',
                                 epilog='Example: small-cloud status example --json')
    status.set_defaults(action='status')
    status.add_argument('app')
    operation = commands.add_parser('operation', help='Inspect an accepted operation',
                                    epilog='Example: small-cloud operation status op_ID')
    operation_status = operation.add_subparsers(dest='action', required=True).add_parser('status',
                                    epilog='Example: small-cloud operation status --request-id UUID')
    operation_status.add_argument('id', nargs='?')
    logs = commands.add_parser('logs', help='Read bounded deployment logs',
                               epilog='Example: small-cloud logs example --source build')
    logs.set_defaults(action='logs')
    logs.add_argument('app')
    logs.add_argument('--source', choices=['build', 'runtime'], required=True)
    logs.add_argument('--deployment')
    position = logs.add_mutually_exclusive_group()
    position.add_argument('--since')
    position.add_argument('--cursor')
    logs.add_argument('--limit', type=int, default=100)
    auth = commands.add_parser('auth', help='Sign in and manage CLI credentials', epilog='Example: small-cloud auth status')
    actions = auth.add_subparsers(dest='action', required=True)
    login = actions.add_parser('login', help='Approve Google sign-in in your browser', epilog='Example: small-cloud auth login --no-browser')
    login.add_argument('--no-browser', action='store_true')
    actions.add_parser('status', help='Show current identity without credential values',
                       epilog='Example: small-cloud --json auth status')
    actions.add_parser('logout', help='Revoke this credential and remove local storage',
                       epilog='Example: small-cloud auth logout')
    revoke = actions.add_parser('revoke', help='Revoke all your CLI credentials',
                                epilog='Example: small-cloud auth revoke --all')
    revoke.add_argument('--all', action='store_true', required=True)
    admin = commands.add_parser('admin', help='Administer explicit workspace membership',
                                epilog='Example: small-cloud admin member add colleague@example.com')
    resources = admin.add_subparsers(dest='resource', required=True)
    member = resources.add_parser('member', help='Admit a member by Google email',
                                  epilog='Example: small-cloud admin member add colleague@example.com')
    add = member.add_subparsers(dest='action', required=True).add_parser('add',
                                  epilog='Example: small-cloud admin member add colleague@example.com')
    add.add_argument('email')
    creator = resources.add_parser('creator', help='Grant publishing authority separately',
                                    epilog='Example: small-cloud admin creator grant usr_FROM_AUTH_STATUS')
    grant = creator.add_subparsers(dest='action', required=True).add_parser('grant',
                                    epilog='Example: small-cloud admin creator grant usr_FROM_AUTH_STATUS')
    grant.add_argument('user_id')
    return root


def global_first(argv):
    flags, rest, index = [], [], 0
    while index < len(argv):
        arg = argv[index]
        if arg in ('--json', '--no-input', '--no-color', '--version'):
            flags.append(arg)
        elif arg in ('--endpoint', '--request-id'):
            if index + 1 >= len(argv):
                raise Failure('INVALID_ARGUMENT', 'Missing global flag value.')
            flags.extend(argv[index:index + 2])
            index += 1
        elif arg.startswith(('--endpoint=', '--request-id=')):
            flags.append(arg)
        else:
            rest.append(arg)
        index += 1
    return flags + rest


def endpoint(args):
    value = args.endpoint or os.environ.get('SMALL_CLOUD_ENDPOINT')
    if not value:
        config = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'small-cloud/config.json'
        try:
            value = json.loads(config.read_text())['endpoint']
        except FileNotFoundError:
            raise Failure('INVALID_ARGUMENT', 'Set --endpoint or configure your platform endpoint.') from None
    return origin(value)


class Client:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, path, body=None, token=None, request_id=None, timeout=30):
        headers = {'Content-Type': 'application/x-tar' if isinstance(body, bytes) else 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
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


def execute(args, request_id):
    if args.command == 'deploy':
        from .upload import package
        if (not re.fullmatch(r'[a-z][a-z0-9-]{0,62}', args.name)
                or args.description is not None and len(args.description) > 500
                or args.timeout <= 0):
            raise Failure('INVALID_ARGUMENT', 'Supply a valid app name, description up to 500 characters and positive timeout.')
        summary, archive = package(args.folder)
        if args.dry_run:
            return summary
        client = Client(endpoint(args))
        credentials = Credentials(client.endpoint)
        with credentials.locked():
            token = credentials.read()
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
    client = Client(endpoint(args))
    credentials = Credentials(client.endpoint)
    with credentials.locked():
        return authenticated_command(args, request_id, client, credentials)


def authenticated_command(args, request_id, client, credentials):
    if args.action == 'login':
        if args.no_input:
            raise Failure('INVALID_ARGUMENT', 'Browser sign-in requires interaction; omit --no-input.')
        poll_secret = secrets.token_urlsafe(32)
        login = client.request('/api/auth/login', {'poll_secret': poll_secret}, request_id=request_id)
        url = login['verification_url']
        if not url.startswith(client.endpoint + '/auth/verify?'):
            raise Failure('NETWORK_ERROR', 'Invalid verification origin.', 503)
        print(f'Open {url} and verify code {login["user_code"]}', file=sys.stderr, flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        deadline = time.monotonic() + min(login['expires_in'], 600)
        interval = max(5, login['interval'])
        while time.monotonic() < deadline:
            time.sleep(interval)
            result = client.request('/api/auth/poll', {'poll_secret': poll_secret})
            if result.get('state') == 'complete':
                token = result.pop('credential')
                result.pop('state')
                try:
                    credentials.write(token)
                except BaseException:
                    client.request('/api/auth/logout', {}, token, str(uuid.uuid4()))
                    raise
                return result
            interval = max(5, min(result.get('interval', 5), 60))
        raise Failure('LOGIN_EXPIRED', 'Login expired; start again.', 401)
    token = credentials.read()
    if args.command == 'usage':
        return client.request('/api/usage', token=token)
    if args.command == 'directory':
        return client.request('/api/directory', token=token)
    if args.command == 'share':
        return client.request('/api/apps/' + urllib.parse.quote(args.app, safe='') + '/share',
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
    if args.action == 'status':
        return client.request('/api/auth/status', token=token)
    result = client.request('/api/auth/' + args.action, {}, token, request_id)
    credentials.remove()
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_mode, request_id = '--json' in argv, None
    try:
        root = parser()
        if '-h' in argv or '--help' in argv:
            current = root
            for word in argv:
                for action in current._actions:
                    if isinstance(action, argparse._SubParsersAction) and word in action.choices:
                        current = action.choices[word]
                        break
            current.print_help()
            return 0
        args = root.parse_args(global_first(argv))
        if getattr(args, 'dry_run', False):
            request_id = None
        elif args.request_id:
            request_id = str(uuid.UUID(args.request_id))
        elif args.action not in ('status', 'logs', 'directory', 'usage') and not getattr(args, 'dry_run', False):
            request_id = str(uuid.uuid4())
        if request_id:
            print('Request ID: ' + request_id, file=sys.stderr, flush=True)
        result = envelope(execute(args, request_id), request_id=request_id)
        print(json.dumps(result) if json_mode else json.dumps(result['data'], indent=2))
        return 0
    except Failure as exc:
        print(json.dumps(envelope(failure=exc, request_id=request_id)) if json_mode else exc.message,
              file=sys.stdout if json_mode else sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        exc = Failure('INTERRUPTED', 'Interrupted.', 500)
        print(json.dumps(envelope(failure=exc, request_id=request_id)) if json_mode else exc.message,
              file=sys.stdout if json_mode else sys.stderr)
        return 130
    except (OSError, ValueError, KeyError):
        exc = Failure('INVALID_ARGUMENT', 'Cannot read configuration or credential storage.')
        print(json.dumps(envelope(failure=exc, request_id=request_id)) if json_mode else exc.message,
              file=sys.stdout if json_mode else sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
