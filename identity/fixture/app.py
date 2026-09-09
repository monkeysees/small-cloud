"""Disposable publishing acceptance fixture; no credentials are rendered."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import socket
import ssl
import threading
import time
import urllib.parse

import psycopg
from psycopg.rows import DictRow, dict_row

TARGETS = json.loads(Path(__file__).with_name('targets.json').read_text())['targets']


def connect():
    return psycopg.Connection[DictRow].connect(os.environ['DATABASE_URL'], connect_timeout=3, row_factory=dict_row)


def initialize():
    with connect() as database:
        # Serialize overlapping old/candidate startup, including first-time DDL.
        database.execute('SELECT pg_advisory_xact_lock(600006)')
        database.execute('''CREATE TABLE IF NOT EXISTS entries (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            value text NOT NULL CHECK (octet_length(value) BETWEEN 1 AND 4096))''')


def isolation(other):
    if not re.fullmatch(r'tool_[0-9a-f]{24}', other):
        raise ValueError('Expected an app database identifier.')
    with connect() as database:
        own = database.execute('SELECT current_database() AS name').fetchone()
        if own is None or own['name'] == other:
            raise ValueError('Supply a different app database.')
    result = {'own_database': 'reachable'}
    probes = [('other_database', {'dbname': other}, 'permission denied for database'),
              ('other_role', {'dbname': other, 'user': other}, 'password authentication failed'),
              ('maintenance_database', {'dbname': 'postgres'}, 'permission denied for database')]
    for name, parameters, denial in probes:
        try:
            with psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=3, **parameters) as database:
                database.execute('SELECT 1')
            result[name] = 'reachable'
        except psycopg.Error as error:
            # libpq connection failures have no SQLSTATE. Never treat transport failure as proof.
            result[name] = 'denied' if denial in str(error) else 'inconclusive'
    return result


def network():
    results = {target['name']: {'expected': target['expected'], 'observed': 'timeout'} for target in TARGETS}
    lock = threading.Lock()

    def probe(target):
        observed = 'blocked'
        try:
            with socket.create_connection((target['host'], target['port']), timeout=2) as connection:
                if target.get('tls'):
                    with ssl.create_default_context().wrap_socket(connection, server_hostname=target['host']):
                        observed = 'reachable'
                else:
                    observed = 'reachable'
        except (OSError, ValueError):
            pass
        with lock:
            results[target['name']]['observed'] = observed

    workers = [threading.Thread(target=probe, args=(target,), daemon=True) for target in TARGETS]
    deadline = time.monotonic() + 2.5
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(max(0, deadline - time.monotonic()))
    with lock:
        return {'probes': {name: dict(result) for name, result in results.items()},
                'note': 'Blocked or timed-out targets require an independently verified reachable listener to prove isolation.'}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, status, result):
        payload = json.dumps(result).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if urllib.parse.urlsplit(self.path).path != '/data':
            self.send_error(404)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 32768:
                raise ValueError()
            body = json.loads(self.rfile.read(length))
            value = body.get('value') if isinstance(body, dict) else None
            if not isinstance(value, str) or not 1 <= len(value.encode()) <= 4096 or '\x00' in value:
                raise ValueError()
        except (ValueError, UnicodeError):
            self.respond(400, {'error': 'Supply a value containing 1–4096 UTF-8 bytes.'})
            return
        try:
            with connect() as database:
                entry = database.execute('INSERT INTO entries (value) VALUES (%s) RETURNING id, value',
                                         (value,)).fetchone()
            self.respond(201, entry)
        except psycopg.Error:
            self.respond(503, {'error': 'Database unavailable.'})

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path == '/' and 'text/html' in self.headers.get('Accept', ''):
            payload = Path(__file__).with_name('index.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(payload)
            return
        if path == '/_small-cloud/ready':
            result = {'ready': True}
        elif path == '/data':
            try:
                with connect() as database:
                    result = {'entries': database.execute('SELECT id, value FROM entries ORDER BY id LIMIT 100').fetchall()}
            except psycopg.Error:
                self.respond(503, {'error': 'Database unavailable.'})
                return
        elif path == '/database/isolation':
            try:
                result = isolation(urllib.parse.parse_qs(parsed.query).get('database', [''])[0])
            except ValueError:
                self.respond(400, {'error': 'Supply a different app database identifier.'})
                return
            except psycopg.Error:
                self.respond(503, {'error': 'Database unavailable.'})
                return
        elif path in ('/', '/identity'):
            result = {'fixture': 'small-cloud-publishing', 'identity': {
                name: self.headers.get('X-Small-Cloud-User-' + name.title()) for name in ('id', 'name', 'email')}}
        elif path == '/network':
            result = network()
        else:
            self.send_error(404)
            return
        self.respond(200, result)


if __name__ == '__main__':
    try:
        initialize()
    except (psycopg.Error, KeyError, OSError):
        raise SystemExit('Database initialization failed; check runtime configuration and schema compatibility.') from None
    HTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8080'))), Handler).serve_forever()
