"""Bounded diagnostic records and a privileged, encrypted redaction-only registry."""
import argparse
import codecs
from datetime import datetime
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time

from cryptography.fernet import Fernet
from .common import Failure, timestamp

RETENTION = 7 * 86400
RECORD_LIMIT = 16 * 1024
SNAPSHOT_LIMIT = 1024 * 1024 - 4096
VOLUME = {'build': 10 * 1024 * 1024, 'runtime': 50 * 1024 * 1024}


def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS diagnostic_streams (
            id TEXT PRIMARY KEY, app_id TEXT NOT NULL, source TEXT NOT NULL,
            retained INTEGER NOT NULL DEFAULT 0, dropped INTEGER NOT NULL DEFAULT 0,
            interrupted INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS diagnostic_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, stream TEXT NOT NULL,
            ingested REAL NOT NULL, entry TEXT NOT NULL, size INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS diagnostic_records_stream ON diagnostic_records(stream,id);
        CREATE INDEX IF NOT EXISTS diagnostic_records_age ON diagnostic_records(ingested);
        CREATE TABLE IF NOT EXISTS diagnostic_values (
            app_id TEXT NOT NULL, deployment TEXT NOT NULL, value BLOB NOT NULL,
            expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS diagnostic_cursors (
            id TEXT PRIMARY KEY, actor TEXT NOT NULL, stream TEXT NOT NULL,
            after_id INTEGER NOT NULL, through_id INTEGER NOT NULL, expires REAL NOT NULL);
    ''')


def prune(db, now):
    for row in db.execute('SELECT stream,SUM(size) AS size FROM diagnostic_records WHERE ingested<=? GROUP BY stream',
                          (now - RETENTION,)).fetchall():
        db.execute('UPDATE diagnostic_streams SET retained=retained-?,dropped=dropped+? WHERE id=?',
                   (row['size'], row['size'], row['stream']))
    db.execute('DELETE FROM diagnostic_records WHERE ingested<=?', (now - RETENTION,))
    db.execute('DELETE FROM diagnostic_cursors WHERE expires<=?', (now,))
    db.execute('DELETE FROM diagnostic_values WHERE expires<=? AND deployment NOT IN '
               '(SELECT active_deployment_id FROM apps WHERE active_deployment_id IS NOT NULL '
               "UNION SELECT id FROM deployments WHERE state IN ('starting','cleaning'))", (now,))


class Registry:
    def __init__(self, state, key, clock=time.time):
        self.state, self.clock = state, clock
        path = Path(key)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(Fernet.generate_key())
                stream.flush()
                os.fsync(stream.fileno())
        from .common import validate_private_file
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
            validate_private_file(stream.fileno())
            self.cipher = Fernet(stream.read(1024))

    def register(self, deployment, values):
        with self.state.connect() as db:
            row = db.execute('SELECT app_id FROM deployments WHERE id=?', (deployment,)).fetchone()
            if row is None:
                raise ValueError('Unknown diagnostic deployment')
        self.save(row['app_id'], deployment, values)

    def save(self, app, deployment, values):
        if (not isinstance(values, list) or len(values) > 128
                or any(not isinstance(v, str) or not 0 < len(v.encode()) <= 65536 for v in values)
                or sum(len(v.encode()) for v in values) > 262144):
            raise ValueError('Invalid redaction values')
        with self.state.connect() as db:
            existing = {self.cipher.decrypt(row['value']).decode(): row['rowid'] for row in db.execute(
                'SELECT rowid,value FROM diagnostic_values WHERE app_id=? AND deployment=?', (app, deployment))}
            for value in set(values):
                if value in existing:
                    db.execute('UPDATE diagnostic_values SET expires=? WHERE rowid=?',
                               (self.clock() + RETENTION + 60, existing[value]))
                else:
                    db.execute('INSERT INTO diagnostic_values VALUES(?,?,?,?)',
                               (app, deployment, self.cipher.encrypt(value.encode()), self.clock() + RETENTION + 60))

    def values(self, app_id):
        self.maintain()
        with self.state.connect() as db:
            rows = db.execute("SELECT value FROM diagnostic_values WHERE app_id IN (?, '*') AND expires>?",
                              (app_id, self.clock())).fetchall()
        return [self.cipher.decrypt(row['value']) for row in rows]

    def maintain(self):
        with self.state.connect() as db:
            # Interrupted candidates remain possible users until operator reconciliation.
            db.execute('UPDATE diagnostic_values SET expires=? WHERE deployment IN '
                       '(SELECT active_deployment_id FROM apps UNION SELECT id FROM deployments '
                       "WHERE state IN ('starting','cleaning'))", (self.clock() + RETENTION + 60,))
            prune(db, self.clock())

    def migrate(self):
        with self.state.connect() as db:
            columns = {row['name'] for row in db.execute('PRAGMA table_info(deployments)')}
            if 'build_log' not in columns:
                return
            rows = db.execute("SELECT id,build_log,dropped_bytes,finished,created FROM deployments WHERE build_log!=''").fetchall()
        for row in rows:
            recorded = row['finished'] or row['created']
            if recorded > self.clock() - RETENTION:
                writer = Writer(self.state, self, row['id'], 'build', clock=lambda: recorded)
                writer.feed(row['build_log'].encode(), final=True)
                if row['dropped_bytes']:
                    writer.append('[previous collector truncated this build]', row['dropped_bytes'])
            with self.state.connect() as db:
                db.execute("UPDATE deployments SET build_log='' WHERE id=?", (row['id'],))
        with self.state.connect() as db:
            db.execute('ALTER TABLE deployments DROP COLUMN build_log')
            db.execute('ALTER TABLE deployments DROP COLUMN dropped_bytes')


class Redactor:
    def __init__(self, values):
        self.values = sorted(set(values), key=len, reverse=True)
        self.pending = b''
        self.starts = re.compile(b'[' + re.escape(bytes(set(v[0] for v in self.values))) + b']') if values else None

    def feed(self, chunk, final=False):
        data = self.pending + chunk
        self.pending = b''
        if self.starts is None:
            return data
        output, position = [], 0
        while match := self.starts.search(data, position):
            start = match.start()
            output.append(data[position:start])
            suffix = data[start:]
            full = next((value for value in self.values if suffix.startswith(value)), None)
            # A longer value can span the next chunk, including a shorter full match.
            if any(value.startswith(suffix) and len(value) > len(suffix) for value in self.values):
                if final:
                    output.append(b'[REDACTED]')
                else:
                    self.pending = suffix
                return b''.join(output)
            if full is not None:
                output.append(b'[REDACTED]')
                position = start + len(full)
            else:
                output.append(data[start:start + 1])
                position = start + 1
        output.append(data[position:])
        return b''.join(output)


class Writer:
    def __init__(self, state, registry, deployment, source, clock=time.time):
        if source not in VOLUME:
            raise ValueError('Invalid diagnostic source')
        self.state, self.clock = state, clock
        self.deployment, self.source = deployment, source
        with state.connect() as db:
            row = db.execute('SELECT app_id FROM deployments WHERE id=?', (deployment,)).fetchone()
            if row is None:
                raise ValueError('Unknown diagnostic deployment')
            self.app = row['app_id']
            self.stream = source + ':' + (deployment if source == 'build' else self.app)
            db.execute('INSERT OR IGNORE INTO diagnostic_streams(id,app_id,source) VALUES(?,?,?)',
                       (self.stream, self.app, source))
        values = registry.values(self.app)
        if source == 'runtime':
            # Docker removes line delimiters before syslog framing. Match that wire
            # representation as well as literal values, including multiline secrets.
            values += [value.replace(b'\n', b'') for value in values if value.replace(b'\n', b'')]
        self.redactor = Redactor(values)
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.line = ''
        self.lost = 0

    def feed(self, chunk, final=False, record=False):
        text = self.decoder.decode(self.redactor.feed(chunk, final), final=final)
        parts = text.split('\n')
        for index, part in enumerate(parts):
            encoded = (self.line + part).encode()
            # Keep only bounded redacted text while consuming an arbitrarily long line.
            self.line = encoded[:RECORD_LIMIT].decode('utf-8', errors='ignore')
            self.lost += len(encoded) - len(self.line.encode())
            if index < len(parts) - 1 or ((final or record) and (self.line or self.lost)):
                self.append(self.line, self.lost)
                self.line, self.lost = '', 0

    def append(self, message, dropped=0, interrupted=False):
        now = self.clock()
        entry = {'timestamp': timestamp(now), 'source': self.source,
                 'deployment_id': self.deployment, 'message': message}
        # JSON escaping and metadata count toward the stored-record bound.
        original = len(message.encode())
        while True:
            entry['message'] = message + (' [truncated]' if dropped else '')
            encoded = json.dumps(entry, ensure_ascii=True)
            if len(encoded.encode()) <= RECORD_LIMIT:
                break
            message = message[:max(0, len(message) - max(1, (len(encoded) - RECORD_LIMIT + 5) // 6))]
            dropped += original - len(message.encode())
            original = len(message.encode())
        size = len(encoded.encode())
        with self.state.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prune(db, now)
            db.execute('INSERT INTO diagnostic_records(stream,ingested,entry,size) VALUES(?,?,?,?)',
                       (self.stream, now, encoded, size))
            db.execute('UPDATE diagnostic_streams SET retained=retained+?,dropped=dropped+?,interrupted=interrupted+? WHERE id=?',
                       (size, dropped, int(interrupted), self.stream))
            retained = db.execute('SELECT retained FROM diagnostic_streams WHERE id=?', (self.stream,)).fetchone()[0]
            if retained > VOLUME[self.source]:
                removed, last = 0, None
                for row in db.execute('SELECT id,size FROM diagnostic_records WHERE stream=? ORDER BY id', (self.stream,)):
                    removed += row['size']
                    last = row['id']
                    if retained - removed <= VOLUME[self.source]:
                        break
                db.execute('DELETE FROM diagnostic_records WHERE stream=? AND id<=?', (self.stream, last))
                db.execute('UPDATE diagnostic_streams SET retained=retained-?,dropped=dropped+? WHERE id=?',
                           (removed, removed, self.stream))


def snapshot(db, actor, app, source, deployment, since, limit, cursor, now):
    if source not in VOLUME or type(limit) is not int or not 1 <= limit <= 1000:
        raise Failure('INVALID_ARGUMENT', 'Select build or runtime logs and a limit between 1 and 1000.')
    if (source == 'runtime' and deployment) or (cursor and since):
        raise Failure('INVALID_ARGUMENT', 'Deployment applies only to build logs; cursor and since are exclusive.')
    prune(db, now)
    saved = None
    if cursor:
        saved = db.execute('SELECT c.* FROM diagnostic_cursors c JOIN diagnostic_streams s ON s.id=c.stream '
                           'WHERE c.id=? AND c.actor=? AND c.expires>? AND s.app_id=? AND s.source=?',
                           (cursor, actor, now, app['id'], source)).fetchone()
        if saved is None:
            raise Failure('INVALID_ARGUMENT', 'Invalid or expired log cursor.')
        if source == 'build' and deployment is None:
            deployment = saved['stream'].removeprefix('build:')
    if source == 'build':
        row = db.execute('SELECT id FROM deployments WHERE app_id=? AND (? IS NULL OR id=?) '
                         'ORDER BY created DESC,rowid DESC LIMIT 1', (app['id'], deployment, deployment)).fetchone()
        if row is None:
            raise Failure('NOT_FOUND', 'Deployment not found.', 404)
        deployment = row['id']
    stream = source + ':' + (deployment if source == 'build' else app['id'])
    after, through = 0, db.execute('SELECT COALESCE(MAX(id),0) FROM diagnostic_records WHERE stream=?', (stream,)).fetchone()[0]
    minimum = 0.0
    if since:
        try:
            if not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)', since):
                raise ValueError()
            minimum = datetime.fromisoformat(since.replace('Z', '+00:00')).timestamp()
        except (ValueError, TypeError):
            raise Failure('INVALID_ARGUMENT', 'Since must be an RFC3339 timestamp.') from None
    expires = now + 600
    if cursor:
        if saved is None or saved['stream'] != stream:
            raise Failure('INVALID_ARGUMENT', 'Invalid or expired log cursor.')
        after, through, expires = saved['after_id'], saved['through_id'], saved['expires']
    rows = db.execute('SELECT * FROM diagnostic_records WHERE stream=? AND id>? AND id<=? AND ingested>=? '
                      'ORDER BY id LIMIT ?', (stream, after, through, minimum, limit + 1)).fetchall()
    entries, size, more = [], 0, False
    for row in rows:
        if len(entries) == limit or size + row['size'] + 2 > SNAPSHOT_LIMIT:
            more = True
            break
        entries.append(json.loads(row['entry']))
        size += row['size'] + 2
        after = row['id']
    next_cursor = None
    if more:
        next_cursor = secrets.token_urlsafe(32)
        db.execute('DELETE FROM diagnostic_cursors WHERE id IN '
                   '(SELECT id FROM diagnostic_cursors ORDER BY expires DESC LIMIT -1 OFFSET 999)')
        db.execute('INSERT INTO diagnostic_cursors VALUES(?,?,?,?,?,?)',
                   (next_cursor, actor, stream, after, through, expires))
    stats = db.execute('SELECT dropped,interrupted FROM diagnostic_streams WHERE id=?', (stream,)).fetchone()
    oldest = db.execute('SELECT ingested FROM diagnostic_records WHERE stream=? ORDER BY id LIMIT 1', (stream,)).fetchone()
    dropped = stats['dropped'] if stats else 0
    interrupted = bool(stats and stats['interrupted'])
    return {'entries': entries, 'truncated': bool(dropped or more or interrupted), 'dropped_bytes': dropped,
            'collection_interrupted': interrupted,
            'oldest_available_at': timestamp(oldest[0]) if oldest else None, 'next_cursor': next_cursor}


def main(clock=time.time):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--key', type=Path, required=True)
    commands = parser.add_subparsers(dest='action', required=True)
    register = commands.add_parser('register', help='Read confidential redaction values from stdin; no readback')
    register.add_argument('--deployment', required=True)
    ingest = commands.add_parser('ingest', help='Read a diagnostic stream from stdin')
    ingest.add_argument('--deployment', required=True)
    ingest.add_argument('--source', required=True, choices=VOLUME)
    args = parser.parse_args()
    from .worker import State
    state = State(args.database)
    registry = Registry(state, args.key, clock)
    if args.action == 'register':
        registry.register(args.deployment, json.loads(sys.stdin.buffer.read(262145))['values'])
    else:
        writer = Writer(state, registry, args.deployment, args.source, clock)
        while chunk := sys.stdin.buffer.read(65536):
            writer.feed(chunk)
        writer.feed(b'', final=True)


if __name__ == '__main__':
    main()
