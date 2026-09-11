# Publish a creator-only HTTP app

For updates that retain the app URL, sharing and database, failed-update diagnostics, and creator-owned schema recovery, see [redeployment](REDEPLOYMENT.md).

Publishing implements [issue #5](https://github.com/monkeysees/small-cloud/issues/5) using the existing [identity service](README.md), [product contracts](../docs/contracts.md), and the accepted German control/runtime hosts. Sign in before publishing. Workspace owners receive the creator role automatically; other members need a separate grant. Ordinary membership and administrator status alone do not permit publication.

```bash
small-cloud app deploy identity/fixture --name publishing-probe --description 'Disposable HTTP probe' --dry-run --json
small-cloud app deploy identity/fixture --name publishing-probe --description 'Disposable HTTP probe' --wait --json
small-cloud app status publishing-probe --json
small-cloud app logs publishing-probe --source build --json
small-cloud operation status --request-id UUID_FROM_DEPLOY --json
small-cloud workspace usage --json
```

The CLI needs Python, not local Docker. A root Dockerfile is required. Dry run validates locally and lists included/excluded paths and uncompressed bytes without authentication, upload or capacity admission. Root `.dockerignore` patterns apply before mandatory exclusions: `.git`, `.small-cloud`, `.env`, `.env.*`, and platform configuration/credential locations cannot be included through negation. Keep source outside platform config/state directories and do not select an ancestor containing those directories. Links, special files, changing files, contexts over 100 MiB and contexts over 10,000 files are rejected. The server independently validates the uncompressed archive. Other credentials embedded in source remain the creator's responsibility.

Deploy returns an accepted operation and immutable app URL. Acceptance does not mean the app is ready. `--wait` polls until completion; `--timeout` bounds the local wait and does not cancel remote work. After a lost connection, inspect the original request ID before retrying. Reusing the same request ID with identical source/metadata returns the original accepted result; different input conflicts. New apps require `--description` (empty is allowed), admit only their creator and reserve their name. Other creators cannot manage them, and administrator diagnostics do not grant private content access.

The root worker builds on a fresh EU VM, verifies the exported image, publishes its immutable release and starts a gVisor sandbox on the German runtime host. The builder receives source, never provider tokens, CLI credentials, database credentials or runtime secrets. A readiness check must succeed before routing selects the new container. Build and startup failures are visible through operation status. Build and runtime logs are bounded, redacted and available to the creator and administrator; see [diagnostics](DIAGNOSTICS.md) for pagination, seven-day retention and collector installation. See [publishing limits and build allowance](LIMITS.md) for #10 accounting, capacity and exhaustion behavior.

Apps serve HTTP on `0.0.0.0:$PORT` (`8080` in this deployment) and implement `GET /_small-cloud/ready`. The platform runs them as UID 65532 with a read-only root, gVisor, 0.5 CPU, 512 MiB memory and 128 tasks. Container filesystems and in-memory state are temporary; `/tmp` consumes the same memory budget. Readiness has 120 seconds; it must report 200 only after initialization. The platform supplies a TLS-verified `DATABASE_URL` for the app's persistent, isolated PostgreSQL database. See the [database starter](fixture/README.md) for repeatable author-owned initialization, a visible disposable-data notice, and HTTP read/write checks. No backup or recovery guarantee exists: use only data users can afford to lose. [Database acceptance](../docs/acceptance/app-database-2026-09-09.md) records #6 outcomes.

Open the returned HTTPS URL and sign in with the creator's admitted Google account. Each app has a separate host-only session. The gateway authorizes every route and method, hides the internal readiness route, replaces incoming identity headers, and strips platform authentication material before forwarding. `X-Small-Cloud-User-ID` is the stable ASCII ID; `X-Small-Cloud-User-Name` and `X-Small-Cloud-User-Email` contain unpadded base64url UTF-8. Trust them only on this protected ingress. Browser mutations require the app's exact Origin. This implementation buffers requests and responses up to 16 MiB, uses a 30-second upstream timeout, and rejects protocol upgrades after authorization. It does not provide streaming or WebSocket support.

The CLI reports upload start and, with `--wait`, each observed deployment stage and an elapsed-time update roughly every 15 seconds on stderr. `--json` still emits exactly one final result on stdout. A build can spend several minutes in `building` while its isolated VM is prepared; periodic messages indicate continued polling, not measured build completion.

## Operator installation

For an existing installation, follow the [initial workspace migration](WORKSPACE-MIGRATION.md) before starting the upgraded identity service and publishing worker together. All existing apps retain their IDs, URLs, sharing and databases in `ws-initial`. New publication uses the saved workspace or an explicit override; see [workspace creation and selection](WORKSPACES.md). Start the diagnostics collector before publishing: Docker's syslog driver requires its socket for runtime startup.

Install the updated Python package in `/opt/small-cloud-identity`, preserving the identity configuration and database. Install the updated sandbox runner on the runtime host. Keep the identity service unprivileged; only the separate publishing worker holds infrastructure authority. Install [small-cloud-publishing.service](small-cloud-publishing.service) and the updated [identity unit](small-cloud-identity.service). The identity service admits one bounded upload at a time and has a 1 GiB memory ceiling.

For the #10 accounting upgrade, also install `infra/artifacts.py`, `infra/remote.py`, `infra/builder/run.sh` and `infra/builder/worker.py` under the existing `/opt/small-cloud/infra` tree on the control host, and add `/api/usage` to the Caddy management matcher. Drain deployments before stopping the worker and identity service; start the upgraded identity service first so it creates the allowance ledger. Existing unfinished deployments receive conservative reservations in their original admission months. Completed deployments from before accounting was enabled have no trustworthy settlement ledger and are not retroactively estimated or charged. The new worker requires termination receipts from the new builder scripts; do not mix worker/script versions. See [limits verification](../docs/acceptance/publishing-limits-2026-09-09.md) for local evidence and deployment status.

Create root-owned mode-0600 `/etc/small-cloud/publishing.json`:

```json
{
  "database": "/srv/small-cloud/identity/identity.sqlite3",
  "admin_cidr": "2.28.60.91/32",
  "runtime_address": "10.42.0.3",
  "runtime_host_key_alias": "small-cloud-165120370"
}
```

The worker uses the existing control-host provider configuration and pinned SSH key under `/root/.local/state/small-cloud/infra`. Do not place that authority in the identity service or any uploaded source. Install the existing infrastructure scripts under `/opt/small-cloud`; preserve their independent builder reconciliation and artifact retention timers. Start the identity service before the publishing worker so the publishing tables exist.

Merge [the management routes](Caddyfile.fragment) into the management site and add [the app HTTPS site](Caddyfile.apps.fragment). Preserve the existing global log redaction. Add `on_demand_tls { ask http://127.0.0.1:8765/internal/tls }` to the global options. The loopback authorization endpoint permits certificates only for durable app hostnames and must never be publicly proxied. Caddy obtains and renews individual certificates without a DNS API token; see [Caddy's on-demand TLS documentation](https://caddyserver.com/docs/automatic-https#on-demand-tls).

Create a DNS-only A record for `*.small-cloud.monkeysees.one` pointing to the control host; preserve the existing unrelated wildcard. Validate the complete Caddy configuration before restart. This installation has `admin off`, so API reload is unavailable. Google continues using the existing management `/auth/callback` URI; no new OAuth callback registration is required. App sessions use a browser-bound single-use handoff to their own origin.

The runtime firewall accepts app ingress only from the control private address and blocks app-to-app, private/metadata and platform management traffic. Verify the public runtime IP and private probe ports cannot bypass the gateway. The reusable [HTTP fixture](fixture/README.md) reports identity and fixed network probes. Local acceptance is not a substitute for a real upload/build, public HTTPS denial and permitted/blocked network checks on the deployed hosts.

After worker interruption, affected operations retain their creator/app lock and expose `reconciliation_required`; the worker does not replay them. The operator must first verify builder deletion, inspect the selected/candidate runtime and release references, and finish or remove the exact interrupted allocation before repairing that operation's state. Do not clear a lock merely because the worker restarted. No automatic reconciliation command is provided in this increment. Unstarted uploads and retained metadata remain on the EU control disk; source BLOBs are securely cleared after processing, and the existing artifact janitor bounds staged source/image retention.

Accounting reservations must also be settled before repairing an interrupted deployment to a terminal state. Preserve its admission-period ledger row; use the trusted `accounting.json` execution duration and confirmed `teardown.json` deletion evidence to charge `min(600, ceil(duration_seconds))` exactly once. A controller-proven preflight failure consumes zero. If timing or termination evidence is missing, retain the reservation and inspect the builder/reconciliation records rather than guessing a duration or resetting the month. Source/result logs are not termination evidence. Administrators can inspect the affected app's operation with `small-cloud app status APP --json`; creators see their own operation failures.

## Acceptance report

See [app publishing acceptance — 2026-09-09](../docs/acceptance/app-publishing-2026-09-09.md) for local tests, deployed checks and operator-confirmed browser outcomes.
