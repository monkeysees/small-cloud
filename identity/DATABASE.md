# App database persistence — issue #6

Each app receives its own PostgreSQL database and scoped `DATABASE_URL` through the existing publishing worker. Repeated provisioning reuses the encrypted credentials and database. Runtime traffic reaches the shared server through the permitted private PostgreSQL exception and verifies the server certificate against the installed CA. The app role can initialize its own schema but cannot connect to another app's database or maintenance databases.

The [HTTP/database starter](fixture/README.md) demonstrates parameterized writes, repeatable startup initialization, authenticated HTTP reads, and a visible disposable-data notice. Authors own schema initialization and compatible migrations; the platform adds no migration runner. Rows survive ordinary restarts and redeployments. Filesystems and memory are temporary, and there is no backup or recovery guarantee.

## Verification

Local acceptance runs the production provisioning helper against PostgreSQL 16 and uses the real CLI and authenticated gateway with local starter processes at the infrastructure boundary. It verifies writes and reads across process restart and repeated publication, both directions of cross-database and cross-role denial, the user notice, input validation, and unauthenticated route denial. Local database transport is loopback TCP; it does not establish deployed TLS or network isolation.

On 2026-09-09, [recorded deployed evidence](../docs/evidence/app-database-2026-09-09.json) verified two creator-only apps on the existing German hosts:

- CLI publication built each app remotely and returned a running, protected HTTPS URL. All three acceptance builds, including the update, succeeded and their builder VMs and addresses were removed.
- Authenticated HTTP inserted and read a row through the supplied TLS-verified URL. The identical row survived an operator `docker restart` of the first app and a fresh CLI deployment to the same app name and URL.
- Both apps could connect to their own database while cross-database access, authentication as the other app's role, and maintenance-database access were denied. Runtime configuration confirmed `sslmode=verify-full`, the installed CA path, the shared private database host and gVisor execution.
- Authenticated HTML contained the disposable-data and no-backup/recovery notices. Unauthenticated data requests returned 401 and public authenticated readiness returned 404. This verifies HTML delivery, not browser rendering or a new Google sign-in flow.
- Public HTTPS was reachable; fixture probes to metadata and private control/runtime SSH were blocked. Earlier hosting/publishing acceptance separately established the reachable listener controls and broader isolation boundary.

The full suite passed 121 tests (36 identity/publishing/database, 81 infrastructure and four hosting fixture). Pyright reported zero errors or warnings. Independent Standards and Spec reviews found no issues.

After #6 shipped and closed, the operator requested cleanup. Both acceptance apps (`database-starter-6` and `database-peer-6`) were removed, releasing two active slots. Their authenticated URLs now return 404. Their databases, roles, encrypted credentials, containers, six runtime images, registry manifests/unused blobs, staged source/images/build logs, and app/session/request metadata were removed. The local acceptance image and temporary test environments were also removed. The earlier `publishing-probe` app remains running and returns authenticated HTTP 200.

Cleanup used scoped operator operations because the product deletion workflow belongs to #13. Shared infrastructure and billing/teardown audit records were retained. This increment required no platform service/configuration deployment: it uses the existing database provisioning and runtime handoff. Idle lifecycle, reset/deletion and broader deployment-failure/schema-repair acceptance remain their separate tickets.
