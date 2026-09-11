"""Bundled, separately authored task guidance; no repository access required."""
GUIDES = {
    'getting-started': ('Discover commands, sign in and inspect apps', '''Small Cloud getting started

Use --json for one versioned result object, including errors. JSON and non-TTY
commands never prompt for terminal input. Progress is on stderr.

small-cloud --help
small-cloud catalog app --json
small-cloud guide runtime
small-cloud guide publishing
small-cloud auth login --no-browser --json
small-cloud auth status --json
small-cloud app list --json
small-cloud app status example --json

Replace example with a name returned by app list. Listing is available to members;
status requires the app creator or workspace administrator. Administrators do not
receive private app content or saved secret values.

Standalone releases bundle Python for Linux and macOS on ARM64 and x86-64.
Installation does not sign in or modify your shell startup files; add the install
directory to PATH if necessary. The service is always
https://small-cloud.monkeysees.one; no endpoint setup is needed or supported.
Credentials stay in protected per-user storage outside source folders, bound
to that exact origin. Old endpoint environment variables and configuration are
ignored. No repository config or .env is loaded.

Login requires human Google browser approval. --no-browser prints a verification
URL and code on stderr; compare the code before approving. The same process waits
and saves the credential. --no-input prohibits terminal prompts but permits this
explicitly requested browser approval. Never paste credentials into commands.

For a headless agent session:
small-cloud auth login start --json --no-input
small-cloud auth login finish ATTEMPT_ID --json --no-input

Start returns verification_url, user_code and attempt_id. Give the URL and code
to the human, who compares the code and approves in their browser. Replace
ATTEMPT_ID with the returned local identifier, then finish on the same machine
and OS account. Finish waits and saves the credential without terminal input.
Use --timeout SECONDS to bound the wait. Timeout, interruption and network errors
provide a next_command to resume; expired or consumed attempts require a new start.
Pending secrets stay in owner-only per-user storage, never in the attempt ID.

auth status reports the fixed service, current identity, workspace and missing
setup steps. Without a credential it returns AUTH_REQUIRED (exit 3) with setup
details and a login command. A member can list apps; publishing additionally
requires a creator grant in the selected workspace. Use workspace list and
workspace select ID; automation should always pass --workspace ID.
Use auth logout to revoke this credential, or auth revoke --all for all your CLI
credentials. Network failures retain local credentials so revocation can be retried.

The delivered CLI has app, workspace, auth and operation groups. Project
linking, default deployment waiting, live
logs and additional workspace controls are still pending. Use catalog for only
implemented commands. Bare invocation, help, catalog and guides work offline.
'''),
    'runtime': ('Author a compatible app and check source before upload', '''Runtime requirements and local preparation

Choose your own language and framework. Small Cloud builds a root Dockerfile
remotely from the selected folder; no local Docker is required. The CLI does not
generate starter files. Supply one Linux x86-64 HTTP container with a foreground
server command. Dependencies must be available without private build credentials;
there are no extra build contexts, multi-container apps, scheduled jobs or
background worker services. Runtime secrets and database credentials are never
available during the build. Do not bake confidential values into source or images.

Listen on 0.0.0.0 using the platform-owned PORT environment variable (currently
8080), not loopback. Implement GET /_small-cloud/ready and return HTTP 200 only
after repeatable initialization. Readiness must succeed within 120 seconds of
startup. The platform reserves that route; it is not available through the public
app URL. A Dockerfile EXPOSE instruction alone does not start a listening server.
The runtime uses gVisor, UID/GID 65532, a read-only root, 0.5 CPU, 512 MiB memory
and 128 tasks. /tmp is temporary and shares the memory budget. Make application
files readable by that user and avoid startup writes outside /tmp.

DATABASE_URL is supplied at runtime for the app's isolated PostgreSQL 16 database.
Use a compatible driver and retain TLS certificate verification: the supplied URL
uses sslmode=verify-full and sslrootcert=/etc/small-cloud/database-ca.crt. Never
print the URL. Initialize and migrate your schema repeatably before reporting
readiness; coordinate overlapping startups. Keep migrations compatible with the
old serving release. A failed update leaves the old release selected but cannot
undo committed schema changes.

Use runtime secrets for external credentials, configured with app secrets set;
read them from environment variables at runtime, never as build arguments.
PORT, DATABASE_URL and SMALL_CLOUD_* names are reserved. Do not log confidential
values. Changing secrets restarts the app; workspace-wide users can trigger
credential-backed actions exposed by its code. See small-cloud guide secrets-sharing.

Data is disposable: use only data users can afford to lose and tell users there
is no backup or recovery guarantee. The database survives ordinary restarts and
redeployments; container filesystems, /tmp and memory are temporary.

Run these commands from your source folder, or replace . with its path:
small-cloud app check .
small-cloud app check . --json
small-cloud catalog app check --json

Checking works offline without login, workspace selection or Docker. It reads and
packages source in memory without writing files, uploading or consuming build
allowance. Human and JSON results report included/excluded relative paths, total
uncompressed file bytes, limits, verified_locally and requires_remote. Excluded
directory entries cover their descendants. File contents are never displayed.

The local checks verify a root Dockerfile, safe source reads and archive paths,
types, mandatory exclusions, and limits of 100 MiB (104857600 bytes) and 10,000
included files. Root .dockerignore patterns apply, including negation; Dockerfile
and .dockerignore themselves remain included. Every .git, .small-cloud, .env and
.env.* path is excluded even if negated. These are not a general secret scanner:
inspect included paths and keep other embedded credentials out yourself.

Source roots inside or containing platform config/credential storage are rejected,
as are embedded platform storage paths. Keep source separate from the per-user
XDG_CONFIG_HOME/small-cloud and XDG_STATE_HOME/small-cloud locations (defaulting
to ~/.config/small-cloud and ~/.local/state/small-cloud). Do not select your whole
home directory as source. Symlinks, hardlinked files and special files are refused,
even when ignored; use ordinary files and keep source stable during checking.

On UPLOAD_REJECTED (exit 2), fix the reported cause and rerun: add the root
Dockerfile, repair invalid .dockerignore syntax, remove links/special files, move
source outside credential storage, stop concurrent edits, or exclude unnecessary
files to fit the size/count limits. No partial file manifest is returned on failure.

Success establishes neither remote build feasibility nor runtime readiness.
Dockerfile syntax, COPY inputs, dependency resolution, image compatibility,
listening/readiness behavior, database initialization, runtime secrets and resource
use require a remote build/runtime. Permissions, available capacity and build
allowance require server admission. Checking does not reserve capacity; deploy
revalidates the source. Read small-cloud guide publishing for deployment and
diagnostics. No local check promises that deployment will succeed.
'''),
    'publishing': ('Prepare, publish, redeploy and inspect bounded diagnostics', '''Publishing and inspection

Read small-cloud guide runtime for the full runtime contract and source remedies.
Publish a folder containing Dockerfile; no local Docker is required. The app must
listen on 0.0.0.0 using PORT (8080), serve HTTP, and initialize its own schema.
Implement GET /_small-cloud/ready: return 200 after repeatable initialization,
within 120 seconds. The runtime uses UID 65532 and a read-only root filesystem;
/tmp is temporary and shares the 512 MiB memory limit.
DATABASE_URL supplies its private PostgreSQL database at runtime; never bake it
or app secrets into an image. Data is disposable, even when ordinary redeployments
and idle restarts preserve it. Keep schema changes compatible with the serving
release: a failed candidate leaves the previous release serving.

small-cloud app check . --json
small-cloud app deploy . --name example --description demo --dry-run --json
small-cloud app deploy . --name example --description demo --wait --json
small-cloud app status example --json
small-cloud app deploy . --name example --wait --json
small-cloud app logs example --source build --json
small-cloud app logs example --source runtime --limit 100 --json
small-cloud operation status op_FROM_DEPLOY --json
small-cloud operation status --request-id 12345678-1234-4234-8234-123456789abc --json

Replace operation/request placeholders with the returned IDs. New apps require a
description (empty allowed); omitted descriptions on updates are preserved.
Dry run reports included/excluded files and bytes; it does not establish remote
build feasibility or readiness. .dockerignore applies, but credentials, .env,
Git metadata and mandatory sensitive paths remain excluded; inspect its result.

Deployment returns acceptance by default. --wait observes completion with a
positive --timeout in seconds (default 900). Timeout, disconnection or Ctrl-C do
not cancel work. Preserve the request ID printed on stderr and inspect that
request or operation before retrying a mutation; retries reuse the same UUID.
Use status for availability and cleanup, and logs for the failed phase. Logs are
bounded snapshots, subject to seven-day retention and volume loss; use the
returned cursor via --cursor for continuation. No --follow is delivered yet.
'''),
    'secrets-sharing': ('Configure runtime secrets and sharing authority', '''Secrets and sharing

small-cloud app secrets list example --json
small-cloud app secrets set example SERVICE_TOKEN --stdin --wait --json
small-cloud app secrets delete example SERVICE_TOKEN --wait --json
small-cloud app share example --scope workspace-wide --acknowledge-secret-authority --json
small-cloud app share example --scope creator-only --json

Replace example with your app. Supply the secret value on stdin for --stdin;
without it, only an interactive terminal may use the hidden prompt. Never put
values in arguments. Input preserves trailing newlines. Saved values cannot be
read back. Names are uppercase identifiers; PORT, DATABASE_URL and SMALL_CLOUD_*
are reserved. Values are 1–16384 UTF-8 bytes without NUL; at most 50 names per app.

Only the creator may change sharing or secrets. Workspace-wide users can trigger
actions backed by app secrets: acknowledge that authority explicitly. Changed
secrets save encrypted configuration and restart the app; --wait observes the
operation. Failure may leave the new configuration saved and the app unavailable.
Deleting an absent name is a no-op. Creator-only apps remain private to the creator.
'''),
    'workspace': ('Create, select and administer workspaces', '''Workspace onboarding and selection

small-cloud workspace create "Design team" --owner owner@example.com --json
small-cloud workspace list --json
small-cloud workspace select ws_FROM_LIST --json

small-cloud auth status --json
small-cloud workspace member add colleague@example.com --json
small-cloud workspace creator grant usr_FROM_AUTH_STATUS --json
small-cloud workspace usage --json

An administrator admits a Google email. The member signs in and obtains their
user ID using auth status; substitute that ID to grant publishing separately.
New owners receive administrator and creator privileges automatically. Other
administrators need a separate creator grant. Usage is
available to creators and administrators. Each build reserves 600 seconds against
the monthly 60000-second allowance; fewer than ten remaining minutes cannot admit
a build. Exhaustion does not stop existing serving apps. Capacity is limited to
five creators, 30 deployed apps and five active apps in this pilot.

Only platform administrators create workspaces. The designated owner signs in
with their exact admitted Google email. Each identity has independent roles in
each workspace; matching email domains grant nothing. The first admission becomes
the saved default automatically. Later membership does not change it. Selection
saves a default across your CLI credentials; --workspace ID overrides it for one
command. Always pass --workspace ID in automation, including operation polling
and retries. Inaccessible or ambiguous targets fail without fallback; workspace
list and workspace select remain available if your old default loses access.

App names are workspace-unique; URLs, app IDs, data and secrets remain separate.
Creator-only content stays private; workspace-wide sharing reaches that workspace
only. Visit /directory on the service for browser sign-in and accessible apps.
Retry with the same request ID AND workspace; changed targets cannot reuse a
receipt. The CLI pins the resolved workspace through any wait.

The five creator grants, 30 deployed apps, five active apps and 60000 monthly
build seconds are installation-wide safety limits shared across workspaces;
creating another workspace does not multiply capacity. Usage counts and build
charges are scoped to your workspace, so other workspaces can consume capacity.
Ownership transfer, suspension, removal and allowance configuration remain
pending. Platform authority grants no private content or saved secret values.
'''),
}
