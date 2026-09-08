#!/usr/bin/env python3
"""Safe network/resource probe, shared by uploaded Dockerfiles and app runtimes."""

import argparse
import errno
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import resource
import re
import secrets
import socket
import ssl
import subprocess
import sys
import time
from urllib.parse import parse_qs, quote, unquote, urlsplit, urlunsplit


def resolve(target):
    family = {'ipv4': socket.AF_INET, 'ipv6': socket.AF_INET6}.get(
        target.get('family'), socket.AF_UNSPEC)
    return socket.getaddrinfo(target['host'], int(target['port']),
                              family=family, type=socket.SOCK_STREAM)


def attempt(target, record=None):
    started = time.monotonic()
    connection = None
    phase = 'dns'
    result = {}
    try:
        if record is None:
            record = resolve(target)[0]
        family, kind, protocol, _, address = record
        result['family'] = 'ipv6' if family == socket.AF_INET6 else 'ipv4'
        phase = 'connect'
        connection = socket.socket(family, kind, protocol)
        connection.settimeout(3)
        connection.connect(address)
        result['connected'] = True
        if target.get('kind', 'tcp') == 'https':
            phase = 'tls'
            connection = ssl.create_default_context().wrap_socket(
                connection, server_hostname=target['host'])
            phase = 'http'
            path = target.get('path', '/')
            if not path.startswith('/') or any(char in path for char in '\r\n'):
                raise ValueError('Invalid probe path')
            request = (f"GET {path} HTTP/1.1\r\nHost: {target['host']}\r\n"
                       'Connection: close\r\n\r\n').encode('ascii')
            connection.sendall(request)
            with connection.makefile('rb') as incoming:
                line = incoming.readline(4096).split(b' ', 2)
            result['http_status'] = int(line[1]) if len(line) > 1 else 0
        result['observed'] = 'connected'
    except socket.gaierror:
        result['observed'] = 'dns_failed'
    except (TimeoutError, socket.timeout):
        result['observed'] = 'timeout'
    except OSError as error:
        result['observed'] = {
            errno.ECONNREFUSED: 'refused', errno.ENETUNREACH: 'unreachable',
            errno.EHOSTUNREACH: 'unreachable', errno.EAFNOSUPPORT: 'family_disabled',
        }.get(error.errno or 0, 'transport_error')
    except (ValueError, UnicodeError):
        result['observed'] = 'invalid_request_or_response'
    finally:
        if connection is not None:
            connection.close()
    result['phase'] = phase
    result['elapsed_ms'] = round((time.monotonic() - started) * 1000)
    return result


def matrix(config, phase):
    results = []
    for target in config['targets']:
        try:
            records = resolve(target)
        except socket.gaierror:
            records = [None]
        for record in records:
            results.append(check(target, phase, record))
    ipv6 = Path('/proc/net/if_inet6')
    try:
        # No addresses or response bodies are retained in the result.
        ipv6_interfaces = len(ipv6.read_text().splitlines())
    except OSError:
        ipv6_interfaces = None
    return {
        'phase': phase, 'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'checks': results, 'ipv6_interface_count': ipv6_interfaces,
        'proxy_environment_present': any(os.environ.get(name) for name in
            ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')),
        'limitation': 'Healthy forbidden endpoints must be verified independently before and after; no proxy, redirect, or rebinding claim.',
    }


def check(target, phase, record):
    expected = target[phase]
    result = {'name': target['name'], 'expected': expected, 'proxy': 'bypassed'}
    result.update(attempt(target, record))
    if expected == 'allow':
        success = result['observed'] == 'connected'
        if target.get('kind') == 'https':
            success = success and 200 <= result.get('http_status', 0) < 400
        result['result'] = 'pass' if success else 'fail'
    elif result.get('connected'):
        result['result'] = 'fail'
    elif (target.get('control_verified') is True
          and result['phase'] == 'connect'
          and result['observed'] in ('timeout', 'unreachable', 'family_disabled')):
        result['result'] = 'pass'
    else:
        result['result'] = 'inconclusive'
    return result


def database():
    connection_url = os.environ.get('DATABASE_URL', '')
    other = os.environ.get('PROBE_OTHER_DATABASE', '')
    if not connection_url or not re.fullmatch(r'[a-z0-9_]{1,63}', other):
        return {'configured': False, 'error': 'DATABASE_URL and PROBE_OTHER_DATABASE required'}
    try:
        parsed = urlsplit(connection_url)
        parameters = parse_qs(parsed.query, strict_parsing=True)
        if (parsed.scheme not in ('postgres', 'postgresql') or not parsed.hostname
                or not parsed.path.strip('/') or set(parameters) - {'sslmode', 'sslrootcert'}
                or any(len(values) != 1 for values in parameters.values())
                or unquote(parsed.path) == '/' + other):
            return {'configured': False, 'error': 'Invalid probe database configuration'}
        port = str(parsed.port or 5432)
    except ValueError:
        return {'configured': False, 'error': 'Invalid probe database configuration'}

    def query(url, statement):
        parts = urlsplit(url)
        environment = {
            'PATH': '/usr/bin:/bin', 'LC_ALL': 'C',
            'PGHOST': parts.hostname, 'PGPORT': port,
            'PGDATABASE': unquote(parts.path.lstrip('/')),
            'PGUSER': unquote(parts.username or ''),
            'PGPASSWORD': unquote(parts.password or ''),
            'PGCONNECT_TIMEOUT': '5',
            'PGOPTIONS': '-c client_min_messages=warning -c statement_timeout=5000',
        }
        for parameter in ('sslmode', 'sslrootcert'):
            if parameter in parameters:
                environment['PG' + parameter.upper()] = parameters[parameter][0]
        try:
            completed = subprocess.run([
                'psql', '-X', '-qAt', '--set=ON_ERROR_STOP=1',
            ], input=statement, text=True, env=environment,
                capture_output=True, timeout=10)
            return completed.returncode, completed.stdout, completed.stderr
        except (OSError, subprocess.TimeoutExpired):
            return -1, '', ''

    nonce = secrets.token_hex(16)
    statement = f'''
CREATE TABLE IF NOT EXISTS public.sc_hosting_probe (id integer PRIMARY KEY, value text NOT NULL);
INSERT INTO public.sc_hosting_probe (id, value) VALUES (1, '{nonce}')
ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value;
SELECT value FROM public.sc_hosting_probe WHERE id = 1;
'''
    code, output, _ = query(connection_url, statement)
    checks = [{'name': 'own-database-create-write-read', 'pass': code == 0 and output.strip() == nonce}]
    for name in (other, 'postgres', 'template1'):
        changed_url = urlunsplit(parsed._replace(path='/' + quote(name, safe='')))
        code, _, error = query(changed_url, 'SELECT 1;')
        checks.append({
            'name': 'deny-' + name,
            'pass': code > 0 and 'permission denied for database' in error.lower(),
        })
    return {'configured': True, 'checks': checks}


def serve(config):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/_small-cloud/ready':
                data = {'ready': True}
            elif self.path == '/probes':
                data = matrix(config, 'runtime')
            elif self.path == '/database':
                data = database()
            elif self.path == '/':
                data = {'fixture': 'small-cloud-hosting', 'pid': os.getpid()}
            else:
                self.send_error(404)
                return
            body = (json.dumps(data) + '\n').encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8080'))), Handler).serve_forever()


def exhaust(kind):
    # The probe's own outer deadline bounds even a missing platform limit.
    import signal
    def deadline(*_):
        raise TimeoutError()
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(15)
    children = []
    value = 0
    observed = 'probe_ceiling'
    disk_created = False
    try:
        if kind == 'cpu':
            begin = time.process_time()
            until = time.monotonic() + 10
            while time.monotonic() < until:
                value += 1
            value = round(time.process_time() - begin, 3)
            observed = 'cpu_seconds_over_ten_wall_seconds'
        elif kind == 'memory':
            blocks = []
            for _ in range(768):
                blocks.append(bytearray(1024 * 1024))
                value += 1024 * 1024
        elif kind == 'pids':
            for _ in range(192):
                pid = os.fork()
                if pid == 0:
                    time.sleep(12)
                    os._exit(0)
                children.append(pid)
                value += 1
        elif kind == 'disk':
            with open('/tmp/sc-exhaustion', 'xb') as output:
                disk_created = True
                block = b'x' * (1024 * 1024)
                for _ in range(1152):
                    output.write(block)
                    value += len(block)
    except (OSError, MemoryError, TimeoutError) as error:
        observed = type(error).__name__
    finally:
        signal.alarm(0)
        for pid in children:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
        if disk_created:
            Path('/tmp/sc-exhaustion').unlink(missing_ok=True)
    print(json.dumps({'resource': kind, 'observed': observed, 'value': value,
                      'rlimit_nproc': resource.getrlimit(resource.RLIMIT_NPROC)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('check', 'serve', 'database', 'cpu', 'memory', 'pids', 'disk'))
    parser.add_argument('--config', type=Path, default=Path('/probe/targets.json'))
    parser.add_argument('--phase', choices=('build', 'runtime'), default='build')
    parser.add_argument('--strict', action='store_true')
    args = parser.parse_args()
    if args.mode == 'database':
        result = database()
        print(json.dumps(result))
        return int(not result['configured'] or not all(item['pass'] for item in result['checks']))
    if args.mode not in ('check', 'serve'):
        exhaust(args.mode)
        return 0
    config = json.loads(args.config.read_text())
    if args.mode == 'serve':
        serve(config)
        return 0
    result = matrix(config, args.phase)
    print(json.dumps(result))
    return int(args.strict and any(item['result'] != 'pass' for item in result['checks']))


if __name__ == '__main__':
    sys.exit(main())
