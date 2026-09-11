# Deployment recovery acceptance — 2026-09-11

Acceptance and publication are complete for [#35](https://github.com/monkeysees/small-cloud/issues/35), from specification #29. Implementation `597277b` adds failed phases, bounded authorized diagnostic excerpts, exact human/JSON inspection guidance and log tails. Release **v0.6.0**, tagged at `2a31966`, is deployed on the hosted backend and published for Linux/macOS on ARM64/x86-64. [Redacted evidence](../evidence/deployment-recovery-2026-09-11.json) records verification, the operator intervention described below, cleanup and publication.

## Implementation and local verification

Deployment errors retain their original code, message, state and request/operation/workspace identity. Recovery adds the failed phase, up to 20 entries and 4096 message characters from a bounded authorized tail read, exact status/log commands and conditional operator escalation. Inspection never repairs source, resets data or submits a deployment. Diagnostic denial, interruption, malformed responses and timeouts preserve the original failure. Runtime excerpts filter the original deployment and retain collection-gap metadata; empty or unavailable logs never establish success.

Actual CLI/HTTPS fixtures verify build/startup/capacity failures, human/JSON output, executable recovery commands, 16,020 progress records before a compiler error, redaction and excerpt bounds, interrupted runtime collection, denied diagnostics, publishing-worker unavailability, missing receipts, lost acceptance responses, timeout/SIGINT, service outages and service-side reconciliation errors. Subsequent inspection/execution proves the original identity is retained without duplicate work.

The full implementation suite passed **240 tests**: 147 identity/CLI/HTTP/database tests, 89 infrastructure CLI tests and four hosting-fixture tests. Pyright 1.1.413 reported zero errors or warnings. Independent Standards and Spec reviews have no remaining findings; the review finding concerning oldest-first log pagination was resolved by direct bounded tail retrieval and its long-log regression.

## Hosted acceptance and operator reconciliation

The supported service deployment installed the checksum-verified v0.6.0 wheel and service units, retaining the previous package, units and protected configuration for rollback. All four required services and the runtime-to-collector readiness path passed. The deployment evidence parser initially attempted to parse package-installer output together with the final JSON; a separate installed-version/readiness check confirmed the successful deployment without repeating it.

Using the retained credential and a standalone executable with Python and Docker absent from PATH, acceptance touched only `recovery-acceptance-35`. Four operations were recorded:

1. A successful deployment first returned a one-second observation timeout. Its exact inspection command later observed the same successful operation without resubmission. An authenticated HTTP request saved a PostgreSQL row.
2. A deliberate Dockerfile failure returned `BUILD_FAILED`, the building phase and the compiler marker. Both structured and readable operation inspection, and the returned status/tail commands, passed. The working release and row remained intact.
3. The first attempted startup-failure test encountered real service-side uncertainty before runtime startup: its trusted build-timing receipt existed, but its teardown receipt was missing. The CLI returned `INTERNAL`, retained the building operation and diagnostics, and required operator reconciliation. It did not replay or claim success.
4. After the third operation was conclusively reconciled, a fresh startup test reached the hosted readiness-failure window and returned `STARTUP_FAILED`. The runtime excerpt contained the deliberate startup marker with the app database URL replaced by `[REDACTED]`. Human/JSON inspection passed; the prior release and row still worked.

For operation 3, the operator verified the durable builder-deletion journal and provider 404 responses for the exact builder and every recorded primary IP. No runtime candidate existed. The trusted duration was 8.818658 seconds, so the existing admission-period ledger was charged **9 seconds**. The exact operation became terminal failed with its original error preserved and operator reconciliation recorded; its unused release references were retired. No duration was guessed, reservation discarded, operation replayed, source repaired or data reset. This was an acceptance-environment intervention, not automatic CLI recovery; the initial teardown-receipt loss was not reproduced or repaired in this ticket.

Worker unavailability, lost acceptance responses, denied diagnostics and interrupted runtime collection remain controlled fixture checks. Production services were not deliberately disrupted to manufacture those failures.

## Native release, installation and cleanup

The [native release workflow](https://github.com/monkeysees/small-cloud/actions/runs/34605330941) passed all four targets with file and native OS credential storage. Each mode runs 31 frozen CLI/HTTPS tests and 14 installed checks, including installer integrity and public HTTPS without system CA paths. All eight public binary/checksum URLs matched verified CI artifacts; `latest` moved atomically from v0.5.0 to v0.6.0. The [GitHub release](https://github.com/monkeysees/small-cloud/releases/tag/v0.6.0) is published.

The [public installation workflow](https://github.com/monkeysees/small-cloud/actions/runs/34607180924) passed on all four targets using real HTTPS downloads without source checkout or Python setup. A separate workstation installation verified retained-credential authentication, recovery help/catalog/guide and actual hosted failure inspection with Python and Docker absent from PATH. The downloaded Linux artifact matched its CI checksum. Credential and shell files remained unchanged; the temporary installation was removed.

All four acceptance builders and their primary IPs were deleted. The temporary app, container, database/role, encrypted database credentials, source staging, diagnostic records and request/session records were removed; release/image references were retired for the existing janitors. **38 charged build seconds** remain in the original allowance ledger, including the reconciled 9 seconds; no reserved build time remains. The removed app's authenticated URL returns 404, and provider inventory contains only the two permanent hosts.

Final checks verified both original apps' metadata and PostgreSQL data, users, memberships, credentials, workspace defaults and protected configuration were preserved. The saved workstation credential is unchanged. All required hosted services are ready and maintenance is off. No human acceptance or release step remains for #35; broader integrated journeys remain #45.
