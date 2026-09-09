-- Frozen pre-workspace schema from commit 27c98a8.

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, admission_email TEXT UNIQUE NOT NULL,
                    subject TEXT UNIQUE, name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL,
                    member INTEGER NOT NULL DEFAULT 1, creator INTEGER NOT NULL DEFAULT 0,
                    administrator INTEGER NOT NULL DEFAULT 0);
                CREATE UNIQUE INDEX IF NOT EXISTS sole_administrator ON users(administrator)
                    WHERE administrator = 1;
                CREATE TABLE IF NOT EXISTS credentials (
                    id TEXT PRIMARY KEY, verifier TEXT UNIQUE NOT NULL, user_id TEXT NOT NULL,
                    expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS browser_sessions (
                    verifier TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS logins (
                    code TEXT PRIMARY KEY, poll_verifier TEXT UNIQUE NOT NULL, expires REAL NOT NULL,
                    user_id TEXT, consumed INTEGER NOT NULL DEFAULT 0, last_poll REAL NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS oauth (
                    state TEXT PRIMARY KEY, browser_verifier TEXT NOT NULL,
                    nonce TEXT NOT NULL, pkce TEXT NOT NULL, code TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (
                    actor TEXT NOT NULL, id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    result TEXT NOT NULL, expires REAL NOT NULL, PRIMARY KEY(actor,id));


                CREATE TABLE IF NOT EXISTS apps (
                    id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, owner TEXT NOT NULL,
                    description TEXT NOT NULL, sharing_scope TEXT NOT NULL DEFAULT 'creator-only',
                    disabled INTEGER NOT NULL DEFAULT 0, active_deployment_id TEXT,
                    target_host TEXT, target_port INTEGER, container TEXT,
                    created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS deployments (
                    id TEXT PRIMARY KEY, app_id TEXT NOT NULL, actor TEXT NOT NULL,
                    request_id TEXT NOT NULL, state TEXT NOT NULL, source BLOB,
                    created REAL NOT NULL, finished REAL, error TEXT,
                    build_log TEXT NOT NULL DEFAULT '', dropped_bytes INTEGER NOT NULL DEFAULT 0,
                    candidate_host TEXT, candidate_port INTEGER, candidate_container TEXT,
                    previous_container TEXT, cleanup_pending INTEGER NOT NULL DEFAULT 0);

                CREATE TABLE IF NOT EXISTS app_sessions (
                    verifier TEXT PRIMARY KEY, app TEXT NOT NULL, user_id TEXT NOT NULL,
                    expires REAL NOT NULL);
