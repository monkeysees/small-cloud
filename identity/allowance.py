"""Build reservations and settlement on the control database transaction."""
from datetime import datetime, timezone
import math

from .common import Failure, timestamp

BUILD_SECONDS = 600
MONTH_SECONDS = 60000


def period(now):
    start = datetime.fromtimestamp(now, timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start.timestamp(), end.timestamp()


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS build_allowance (
        deployment_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
        period_start REAL NOT NULL, period_end REAL NOT NULL,
        charged_seconds INTEGER CHECK(charged_seconds BETWEEN 0 AND 600))''')
    # Existing unfinished operations retain capacity across the accounting upgrade.
    for row in db.execute("SELECT d.id,d.created,a.workspace_id FROM deployments d JOIN apps a ON a.id=d.app_id "
                          "WHERE d.state NOT IN ('succeeded','failed')"):
        db.execute('INSERT OR IGNORE INTO build_allowance VALUES(?,?,?,?,NULL)',
                   (row['id'], row['workspace_id'], *period(row['created'])))


def usage(db, workspace, now):
    start, end = period(now)
    row = db.execute('SELECT COALESCE(SUM(charged_seconds),0), '
                     'COUNT(*) FILTER (WHERE charged_seconds IS NULL) FROM build_allowance '
                     'WHERE (? IS NULL OR workspace_id=?) AND period_start=?', (workspace, workspace, start)).fetchone()
    charged, reserved = row[0], row[1] * BUILD_SECONDS
    return {'period_start': timestamp(start), 'period_end': timestamp(end), 'limit_seconds': MONTH_SECONDS,
            'charged_seconds': charged, 'reserved_seconds': reserved,
            'available_seconds': MONTH_SECONDS - charged - reserved}


def reserve(db, deployment, workspace, now):
    current = usage(db, None, now)
    if current['available_seconds'] < BUILD_SECONDS:
        code = 'ALLOWANCE_RESERVED' if MONTH_SECONDS - current['charged_seconds'] >= BUILD_SECONDS else 'ALLOWANCE_EXHAUSTED'
        message = ('Build allowance is reserved by unfinished builds; inspect operations and retry after settlement.'
                   if code == 'ALLOWANCE_RESERVED' else
                   'Fewer than ten build minutes remain; wait for the next UTC month.')
        raise Failure(code, message, 409, **current)
    db.execute('INSERT INTO build_allowance VALUES(?,?,?,?,NULL)',
               (deployment, workspace, *period(now)))


def settle(db, deployment, evidence):
    duration = evidence.get('duration_seconds')
    if (evidence.get('terminated') is not True or type(duration) not in (int, float)
            or not math.isfinite(duration) or duration < 0):
        raise Failure('INTERNAL', 'Build termination or execution timing requires operator reconciliation.', 500,
                      reconciliation_required=True)
    db.execute('UPDATE build_allowance SET charged_seconds=? WHERE deployment_id=? AND charged_seconds IS NULL',
               (min(BUILD_SECONDS, math.ceil(duration)), deployment))
