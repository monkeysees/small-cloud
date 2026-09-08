#!/usr/bin/env python3
"""Root-only provisioning; credentials stay encrypted and never reach stdout."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile


ROOT = Path('/srv/small-cloud/secrets')


def command(args, data=None):
    try:
        result = subprocess.run(args, input=data, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=False, timeout=60)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Operator command deadline exceeded') from None
    if result.returncode:
        # Neither SQL nor encryption errors may disclose a credential.
        raise RuntimeError(f'{args[0]} failed; inspect service health without logging credentials')
    return result.stdout


def sql(statement, database='postgres'):
    statement = "SET lock_timeout = '5s'; SET statement_timeout = '30s';\n" + statement
    return command(['runuser', '-u', 'postgres', '--', 'psql', '-X', '-q',
                    '-v', 'ON_ERROR_STOP=1', '--dbname', database], statement.encode())


def provision(tool_id):
    name = 'tool_' + hashlib.sha256(tool_id.encode()).hexdigest()[:24]
    credential_path = ROOT / f'{name}.json.age'
    identity = ROOT / 'identity.age'
    if credential_path.exists():
        saved = json.loads(command(['age', '--decrypt', '-i', str(identity),
                                    str(credential_path)]))
        if saved['tool_id'] != tool_id or saved['database'] != name:
            raise RuntimeError('Credential identity mismatch')
        password = saved['password']
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', password):
            raise RuntimeError('Invalid saved credential')
    else:
        password = secrets.token_urlsafe(32)
        saved = {
            'tool_id': tool_id, 'database': name, 'user': name,
            'password': password,
            'database_url': f'postgresql://{name}:{password}@10.42.0.2:5432/{name}'
                            '?sslmode=verify-full&sslrootcert=/etc/small-cloud/database-ca.crt',
        }
        recipient = command(['age-keygen', '-y', str(identity)]).decode().strip()
        encrypted = command(['age', '--encrypt', '-r', recipient], json.dumps(saved).encode())
        with tempfile.NamedTemporaryFile(dir=ROOT, prefix='.credentials-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, credential_path)
        directory = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    # A fresh role cannot authenticate until all database permissions are in place.
    sql(fr"""
SELECT 'CREATE ROLE {name} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{name}') \gexec
SELECT 'CREATE DATABASE {name} OWNER postgres ALLOW_CONNECTIONS false'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '{name}') \gexec
REVOKE ALL ON DATABASE {name} FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE {name} TO {name};
ALTER DATABASE {name} ALLOW_CONNECTIONS true;
""")
    sql(f"""
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO {name};
""", name)
    sql(f"""
ALTER ROLE {name} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 10 PASSWORD '{password}';
ALTER ROLE {name} SET statement_timeout = '30s';
ALTER ROLE {name} SET idle_in_transaction_session_timeout = '30s';
""")
    return {'tool_id': tool_id, 'database': name, 'user': name,
            'encrypted_credentials': str(credential_path),
            'database_ca': '/etc/small-cloud/database-ca.crt'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tool_id', metavar='app_id', help='Immutable app ID (ASCII letters, numbers, underscore, dash)')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', args.tool_id):
        parser.error('Invalid immutable app ID')
    if os.geteuid() != 0:
        parser.error('Root required')
    os.umask(0o077)
    try:
        with (ROOT / 'provision.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = provision(args.tool_id)
        print(json.dumps(result))
    except (RuntimeError, OSError, ValueError, KeyError):
        print('Database provisioning failed; no credentials returned. Retry after correcting host health.',
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
