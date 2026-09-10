"""Atomic workspace schema upgrades preserving persisted app and identity contracts."""
import re
from .common import Failure

INITIAL_WORKSPACE = 'ws-initial'


def mutation_meaning(inputs, workspace):
    # Preserve unexpired initial-workspace receipts from the deployed single-workspace service.
    return inputs if workspace == INITIAL_WORKSPACE else [*inputs, workspace]


def migrate(db):
    # DDL participates in this transaction; never use executescript inside it.
    db.execute('BEGIN IMMEDIATE')
    legacy = 'member' in {row['name'] for row in db.execute('PRAGMA table_info(users)')}
    initialized = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspaces'").fetchone()
    if legacy and initialized:
        raise Failure('MIGRATION_REQUIRED', 'Partial workspace schema requires operator reconciliation.', 500)
    if not initialized:
        db.execute('CREATE TABLE workspaces (id TEXT PRIMARY KEY, '
                   'name TEXT NOT NULL, owner_id TEXT NOT NULL REFERENCES users(id))')
        db.execute('CREATE TABLE memberships (workspace_id TEXT NOT NULL REFERENCES workspaces(id), '
                   'user_id TEXT NOT NULL REFERENCES users(id), member INTEGER NOT NULL CHECK(member IN (0,1)), '
                   'creator INTEGER NOT NULL CHECK(creator IN (0,1)), '
                   'administrator INTEGER NOT NULL CHECK(administrator IN (0,1)), '
                   'PRIMARY KEY(workspace_id,user_id))')
    if legacy:
        users = db.execute('SELECT * FROM users').fetchall()
        owners = [user for user in users if user['administrator'] == 1]
        if users and (len(owners) != 1 or not owners[0]['member']):
            raise Failure('MIGRATION_REQUIRED', 'Migration requires exactly one admitted operator.', 500)
        if any(user[role] not in (0, 1) for user in users for role in ('member', 'creator', 'administrator')):
            raise Failure('MIGRATION_REQUIRED', 'Legacy membership roles are inconsistent.', 500)
        db.execute('ALTER TABLE users ADD COLUMN platform_administrator INTEGER NOT NULL DEFAULT 0')
        db.execute('ALTER TABLE users ADD COLUMN default_workspace TEXT REFERENCES workspaces(id)')
        if users:
            db.execute('INSERT INTO workspaces VALUES(?,?,?)',
                       (INITIAL_WORKSPACE, 'Initial workspace', owners[0]['id']))
            db.execute('INSERT INTO memberships SELECT ?,id,member,creator,administrator FROM users',
                       (INITIAL_WORKSPACE,))
            db.execute('UPDATE users SET default_workspace=?,platform_administrator=administrator',
                       (INITIAL_WORKSPACE,))
        db.execute('DROP INDEX IF EXISTS sole_administrator')
        for role in ('member', 'creator', 'administrator'):
            db.execute('ALTER TABLE users DROP COLUMN ' + role)
    schema = db.execute("SELECT sql FROM sqlite_master WHERE name='workspaces'").fetchone()[0]
    db.execute('DROP VIEW IF EXISTS workspace_users')
    if 'CHECK' in schema.upper():
        db.execute('CREATE TABLE workspaces_new (id TEXT PRIMARY KEY, name TEXT NOT NULL, '
                   'owner_id TEXT NOT NULL REFERENCES users(id))')
        db.execute('INSERT INTO workspaces_new SELECT * FROM workspaces')
        db.execute('DROP TABLE workspaces')
        db.execute('ALTER TABLE workspaces_new RENAME TO workspaces')
    db.execute('CREATE VIEW workspace_users AS SELECT u.*, m.workspace_id, m.member, m.creator, '
               'm.administrator, w.name AS workspace_name, w.owner_id FROM users u '
               'JOIN memberships m ON m.user_id=u.id '
               'JOIN workspaces w ON w.id=m.workspace_id')
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='apps'").fetchone():
        if 'workspace_id' not in {row['name'] for row in db.execute('PRAGMA table_info(apps)')}:
            db.execute("ALTER TABLE apps ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'ws-initial' "
                       "CHECK(workspace_id='ws-initial')")
        schema = db.execute("SELECT sql FROM sqlite_master WHERE name='apps'").fetchone()[0]
        if re.search(r'name\s+TEXT\s+UNIQUE', schema, re.I):
            updated = re.sub(r'name\s+TEXT\s+UNIQUE', 'name TEXT', schema, flags=re.I)
            updated = re.sub(r"CHECK\s*\(workspace_id\s*=\s*'ws-initial'\)", '', updated, flags=re.I)
            updated = re.sub(r'CREATE TABLE\s+apps', 'CREATE TABLE apps_new', updated, count=1, flags=re.I)
            updated = updated.rstrip().removesuffix(')') + ', UNIQUE(workspace_id,name))'
            db.execute(updated)
            db.execute('INSERT INTO apps_new SELECT * FROM apps')
            db.execute('DROP TABLE apps')
            db.execute('ALTER TABLE apps_new RENAME TO apps')
        if db.execute('SELECT 1 FROM apps a LEFT JOIN memberships m ON m.user_id=a.owner '
                      'AND m.workspace_id=a.workspace_id WHERE m.user_id IS NULL').fetchone():
            raise Failure('MIGRATION_REQUIRED', 'An app has no accountable workspace membership.', 500)
    if db.execute('SELECT 1 FROM workspaces w LEFT JOIN memberships m ON m.user_id=w.owner_id '
                  'AND m.workspace_id=w.id WHERE m.user_id IS NULL OR m.member!=1 OR m.administrator!=1').fetchone():
        raise Failure('MIGRATION_REQUIRED', 'Workspace ownership is inconsistent.', 500)
    if db.execute('SELECT 1 FROM users u LEFT JOIN memberships m ON m.user_id=u.id '
                  'AND m.workspace_id=u.default_workspace WHERE m.user_id IS NULL').fetchone():
        raise Failure('MIGRATION_REQUIRED', 'A saved workspace has no membership.', 500)
    if db.execute('PRAGMA foreign_key_check').fetchone():
        raise Failure('MIGRATION_REQUIRED', 'Workspace references are inconsistent.', 500)
