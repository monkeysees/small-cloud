"""Agent-callable Small Cloud CLI. Never prints credential or provider-token values."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import time
import urllib.request
import urllib.error
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

    def request(self, path, body=None, token=None, request_id=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if request_id:
            headers['X-Request-ID'] = request_id
        request = urllib.request.Request(self.endpoint + path,
                   data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            try:
                response = self.opener.open(request, timeout=30)
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
        if args.request_id:
            request_id = str(uuid.UUID(args.request_id))
        elif args.action != 'status':
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
