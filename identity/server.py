"""Trusted identity service operator entry point."""
import argparse
import json

from pathlib import Path
from .common import Failure, envelope, origin, read_private
from .store import Store


def main():
    parser = argparse.ArgumentParser(description='Small Cloud identity service')
    parser.add_argument('--config', required=True, help='Owner-only service JSON file')
    commands = parser.add_subparsers(dest='command', required=True)
    bootstrap = commands.add_parser('bootstrap', help='Set the initial workspace owner and platform administrator once')
    bootstrap.add_argument('email')
    serve = commands.add_parser('serve', help='Serve loopback HTTP behind the management HTTPS proxy')
    serve.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    try:
        config = read_private(Path(args.config))
        origin(config['origin'])
        if args.command == 'serve':
            from .http import create_server
            server = create_server(config, args.port)
            try:
                server.serve_forever()
            finally:
                server.server_close()
        else:
            store = Store(config['state_directory'])
            print(json.dumps(envelope(store.bootstrap(args.email))))
        return 0
    except Failure as exc:
        print(json.dumps(envelope(failure=exc)))
        return exc.exit_code
    except (OSError, ValueError, KeyError):
        print(json.dumps(envelope(failure=Failure('INVALID_ARGUMENT', 'Cannot read service configuration.'))))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
