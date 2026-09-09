# App runtime secrets acceptance — 2026-09-09

Issue [#12](https://github.com/monkeysees/small-cloud/issues/12), against specification [#1](https://github.com/monkeysees/small-cloud/issues/1) and ADR 0006. Implementation `9c4d400` was pushed and installed on the existing German control/runtime hosts. The [recorded evidence](../evidence/app-secrets-2026-09-09.json) includes deployed hashes, observations, cleanup and final inventory.

## Verification

Local verification passed the full 78-test identity, 89-test infrastructure and four-test probe suites. The final seven-test secrets suite additionally covers the two tests added during final verification, for 173 distinct passing tests. Pyright reported zero errors. Standards and Spec reviews had no remaining findings after fixing failed-first-deployment configuration, retired-value expiry after exception cleanup, and plaintext Docker argv exposure. A later regression verifies that secret restarts do not hold another app's creator build lock.

The coordinated hosted upgrade installed the wheel and sandbox, restarted identity to create the schema and service-owned mode-0600 encryption key, then started diagnostics, publishing and lifecycle workers. All services remained healthy. Both existing apps retained their exact release, sharing scope and stopped state throughout acceptance.

Two dedicated `secrets-acceptance-12-*` apps used the PostgreSQL fixture with temporary observation and log-probe routes. Three fresh EU builds used CX23 in Falkenstein and CPX22 in Nuremberg. The Dockerfile asserted absent `SERVICE_TOKEN` and `SERVICE_URL` build variables and an excluded `.env` file, including a redeployment after runtime secrets were configured. That redeployment retained runtime configuration and the app URL.

Creator CLI checks demonstrated stdin values with one and two trailing newlines, name-only listing, replacement, deletion, and absent deletion without restart. A real controlling PTY exercised the hidden prompt and verified that the entered value was not echoed or rendered in output. Runtime digests and byte counts matched the exact supplied values, and process identifiers changed after configuration changes. The second app had no secret configuration.

The owning app sent only disposable random canaries to the public [HTTPBingo echo service](https://httpbingo.org/). Its fixture compared the returned JSON token with its runtime value and exposed only the successful comparison. This establishes live outbound HTTPS behavior with the exact multiline configuration; no real service credential, platform token or user data was sent to that external service.

An existing Google-authenticated owner credential exercised the creator workflow. Three separately named, short-lived operator-created identities exercised member, other-creator and administrator roles through real hosted CLI/API requests. All were denied secret names, saved-value paths, set and delete with `NOT_FOUND`; private content was also denied. Sharing with secrets required explicit acknowledgement, as did setting a secret on an already shared app. Once shared, those members could trigger the app's credential-backed external action. Administrator diagnostic access remained available without secret-management authority.

Live storage inspection verified encrypted value records, the protected encryption key and absence of confidential canaries from plaintext SQLite storage. Runtime inspection confirmed `runsc`, 512 MiB memory, 0.5 CPU, 128 tasks and syslog with the raw disk cache disabled. Installed source hashes matched the pushed implementation on both hosts.

After replacement and deletion, the fixture deliberately logged both retired values and the current hidden-input canary. Creator and administrator diagnostic reads contained `[REDACTED]` and none of the canaries. Retired values remained encrypted with recorded expiry deadlines. Seven-day expiry uses local controlled-clock coverage plus the live stored deadlines; this report does not claim that seven calendar days elapsed during acceptance.

A deliberate startup failure used the production 120-second readiness timeout and reported `STARTUP_FAILED` with `configuration_saved:true`. Correcting the saved setting restored the app. A separate delayed-start test confirmed a physical gVisor container was running, killed the lifecycle worker, observed both active reservations retained, and verified that the restarted service completed the same secret-change operation with the same release. The temporary delay setting was then deleted successfully.

## Cleanup and evidence boundary

Removed both acceptance apps, containers, databases/roles, encrypted database credentials, source staging, current/retired app secrets, diagnostics, receipts and app-session records. Removed all three disposable identities and their credentials; those credentials now fail authentication, and both acceptance URLs return 404. Image references were retired for the existing janitors and their normal grace period, rather than claiming immediate physical removal of every shared layer.

All three builders and their addresses were deleted. Final provider inventory contains only the two permanent German hosts and their two addresses. The 41 seconds of actual build allowance charges remain recorded: final usage is two deployed apps, zero active apps, 818 charged build seconds and zero reserved seconds. The two pre-existing apps remain unchanged. Identity, publishing, lifecycle, diagnostics and Caddy are active.

No fresh Google sign-in or rendered-browser interaction was performed: this session had no accessible existing browser. Foreign-role checks used explicitly identified operator-created fixtures, not impersonation of existing people or a claimed Google authentication result. This is hosted CLI/HTTP acceptance for the secrets capability; predecessor Google/browser evidence remains separate.
