# App redeployment acceptance — 2026-09-09

Issue [#8](https://github.com/monkeysees/small-cloud/issues/8), against specification [#1](https://github.com/monkeysees/small-cloud/issues/1). The existing worker already builds and checks a candidate before selecting it; this increment adds executable proof and creator recovery documentation without changing the deployment protocol.

## Verified behavior

The reusable HTTP/database acceptance suite passes eight tests. Three new tests upload source through the real creator CLI, build that uploaded archive with Docker, and launch its resulting image against a real, app-scoped PostgreSQL database. Assertions use CLI status and authenticated HTTP through the platform gateway. Each uploaded variant returns a distinct release marker, so retaining an old version cannot accidentally satisfy a successful-update assertion.

- Successful updates change the serving release while preserving URL, sharing scope and previously written rows in both creator-only and workspace-wide modes. An ordinary member remains denied in creator-only mode and gains access in workspace-wide mode.
- A Dockerfile with `RUN false` fails its build. A separately built image exits before readiness. Both leave the previous deployment ID and HTTP release marker selected, with saved data readable. App status and request-ID operation status identify `BUILD_FAILED` and `STARTUP_FAILED` separately. A corrected update subsequently succeeds with the rows preserved.
- A candidate commits an incompatible column rename and then exits. The old release still answers its identity route, while reads and writes requiring the original column return HTTP 503. A creator-authored repair restores the column and the original rows through a subsequent deployment. This explicitly demonstrates that previous-container availability is not database rollback or old-schema compatibility.

The first release-marker regression failed against the old harness, which ignored uploaded source, and passed after the harness built and ran the actual archive. Successful promotion stops the previous test container; failure cleanup stops only the candidate. Test cleanup removes the containers, per-deployment image tags and disposable PostgreSQL volume.

## Reproduce and interpret

Final verification passed 156 tests: 66 identity tests (including all eight HTTP/database checks), 86 infrastructure CLI tests and four hosting-fixture tests. Pyright 1.1.413 reported zero errors and warnings; `git diff --check` passed. Independent Standards and Spec reviews found no issues.

Use the dependencies and Python environment described in the [identity runbook](../../identity/README.md). Local Docker is required for the acceptance harness, not for creators publishing to the platform.

```bash
python3 -m unittest identity.tests.test_database_http
python3 -m unittest discover -s identity/tests -p 'test_*.py'
python3 -m unittest discover -s infra/tests -p 'test_*_cli.py'
python3 -m unittest discover -s probes/hosting/fixture -p 'test_*.py'
npx --yes pyright@1.1.413 --pythonpath "$(command -v python3)"
```

The local adapter uses the existing signed-token Google fixture, database transport over loopback without TLS and Docker host networking. It does not establish cloud build provisioning, gVisor, production readiness timing, runtime promotion commands or EU hosting. The hosted follow-up below verifies those redeployment paths; broader infrastructure evidence remains in the [foundation report](hosting-foundation-2026-09-08.md).

[Creator guidance](../../identity/REDEPLOYMENT.md) explains compatible migrations, creator-led schema repair and explicit reset as a future recovery option under #13. No automatic schema rollback, backup guarantee, migration runner or reset implementation is claimed.

## Hosted acceptance and finalization

Pushed implementation `b04e2cb` and published seven fixture variants through the real creator CLI to the temporary `redeployment-acceptance-8` app. The existing platform implementation required no package or service upgrade. All seven fresh CX23 builders ran in Nuremberg and were deleted, with termination and accounting receipts captured in the [hosted evidence](../evidence/app-redeployment-2026-09-09.json). Runtime inspection confirmed gVisor and `sslmode=verify-full` database connections.

Successful creator-only and workspace-wide updates preserved the URL and saved PostgreSQL row while changing the serving release marker. Continuous authenticated HTTP probes observed the old release during updates. The `cleaning` stage was also observed with the new release already serving after readiness; it is not a requirement to keep selecting the old release during retirement.

The deliberate Dockerfile failure reported `BUILD_FAILED`; the separate early-exit image reported `STARTUP_FAILED` after the production 120-second readiness window. The same active container ID remained running across both failures, and the saved row remained readable. CLI app status and request-ID operation status identified each failed attempt without replacing the active deployment ID.

The incompatible-schema candidate committed a column rename and then exited. The old release continued answering its identity route, while both database reads and writes returned HTTP 503. A final creator-authored repair deployment restored the expected column and the original row at the same URL. The repair checks for the renamed column under the startup advisory lock before changing it. This experiment touched only the temporary app's disposable database.

Removed the temporary app, container, PostgreSQL database/role, encrypted credentials, source staging, diagnostics and request/session records; its authenticated URL now returns 404. Retired registry/runtime images follow the existing automatic janitor grace periods, with all cleanup timers active. Final provider inventory contains only the two permanent hosts and their two addresses. The seven real builds charged **92 seconds**, retained in the allowance ledger: final usage is two deployed/active apps, 734 charged seconds and zero reserved seconds.

Both pre-existing apps retain their exact status records, deployment IDs and sharing scopes, and both pass operator HTTP readiness. The owner-accessible `publishing-probe` returns authenticated HTTP 200; the other creator's private `sharing-acceptance-7` correctly returns 404 to the administrator, preserving the established content boundary. Identity, publishing, diagnostics and Caddy services are active. Sharing-role coverage remains backed by the local regression matrix and the completed [#7 hosted acceptance](app-sharing-2026-09-09.md); no new human login or browser action is required. All #8 acceptance work is complete.
