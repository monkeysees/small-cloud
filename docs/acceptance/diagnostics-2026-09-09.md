# Diagnostics acceptance — 2026-09-09

Local and hosted acceptance for [issue #11](https://github.com/monkeysees/small-cloud/issues/11), against the [diagnostics contract](../contracts.md). The implementation is deployed on the existing Nuremberg control/runtime hosts, with [machine-readable evidence](../evidence/diagnostics-2026-09-09.json). Limits, literal-redaction limitations, collection gaps and installation procedures are documented in the [diagnostics guide](../../identity/DIAGNOSTICS.md).

## Local acceptance

The CLI and authenticated HTTPS tests verify creator/administrator access and denial for other creators and members. Existing gateway tests preserve the separate rule that administrator diagnostics authority does not grant private app content. Tests cover split database-value redaction before persistence and record shortening, escaped control characters, 16 KiB encoded records, at most 1 MiB and 1,000 entries per response, chronological pagination, actor-bound cursors that retain the original build after redeployment, and runtime volume shared across deployments. The deterministic clock verifies expiry at exactly seven days after ingestion, independently of source timestamps.

Real Docker syslog tests verify split frames, multiline known values, disabled local log caching, and new redaction registrations on an already-open stream with a secret prefix pending. Independent review found two problems that were corrected: existing writers needed refreshed patterns, and transport reconnection failures could bypass scheduled pruning. Maintenance now runs through transport outages and refreshes active writers. Legacy build output is migrated through redaction before the old columns are removed.

The final full identity suite passed **63 tests**. The infrastructure suite passed **86 tests**, and the hosting probe fixture suite passed **four tests**. Pyright 1.1.413 reports zero errors; shell syntax and whitespace checks pass. The quota concurrency fixtures now distinguish the earlier single-upload gate from downstream quota admission while still requiring exactly one accepted contender and the precise quota refusal. Independent Standards and Spec reviews have zero unresolved findings.

Reproduce with the repository dependencies, Docker and the starter PostgreSQL driver installed:

```bash
python3 -m unittest discover -s identity/tests -p 'test_*.py'
python3 -m unittest discover -s infra/tests -p 'test_*_cli.py'
python3 -m unittest discover -s probes/hosting/fixture -p 'test_*.py'
npx --yes pyright@1.1.413 --pythonpath "$(command -v python3)"
bash -n infra/builder/run.sh
```

## Hosted acceptance

Installed the package from `a95e068` and the builder script from `d655296` using a locally built wheel and uploaded files; these commits have not been pushed. Identity, publishing and diagnostics services are active. Runtime collection uses root-only mode-0600 Unix sockets over pinned SSH between the German hosts. Docker uses the syslog driver with its local cache disabled; product builds stream into the redactor without raw `build.log` or `daemon.log` staging files.

Two real CLI publications of `diagnostics-acceptance-11` used fresh Nuremberg builders. The first exposed BuildKit's own clipping before the platform could observe 10 MiB. Disabling its upstream size/rate limits and repeating the build verified platform eviction: **857,823 dropped bytes**, 770 retained entries over 11 pages, and a largest page of 1,033,162 bytes. The oldest marker was evicted and the final redacted marker remained. Runtime output exceeded the shared 50 MiB bound: **3,776,062 dropped bytes**, 3,737 entries over 51 pages, with the same oldest/final-marker result.

The runtime deliberately printed its actual database URL and password, including split writes, plus a registered synthetic canary. All were absent from the persistent SQLite file and redacted in the retrieved output. Restarting the collector exposed `collection_interrupted`, resumed collection, and retained redaction for newly emitted values. The private runtime remained ready. Unauthenticated diagnostics and private app API requests returned HTTP 401; a browser-style private app request redirected to sign-in. Live authentication used the retained creator/administrator credential; the separate-role denial matrix and seven-day clock boundary are local acceptance evidence, without modifying production identities or time.

Both pre-existing apps were moved to the new logging configuration using their retained images and a readiness-checked candidate promotion. Their URLs, selected deployment IDs, creator-only sharing and database credentials were preserved. Before/after comparisons of all public database table contents matched; no private data or credentials were included in the evidence. Both apps were running after final cleanup.

## Cleanup and remaining scope

Deleted only the temporary acceptance app, runtime, PostgreSQL database/role, encrypted credential, source staging, diagnostics and synthetic registration. Removed the temporary rollback copy and ten migrated legacy raw log files. Both fresh builders and their addresses were deleted; only the permanent control/runtime hosts remain. Retired acceptance images follow the existing registry/runtime janitor grace periods, without forcing shared-layer deletion. The two real builds charged 14 and 13 seconds; those **27 seconds** remain in the ledger. Final usage is two deployed/active apps, 642 charged seconds and zero reserved seconds. Provider billing remains an estimate until an invoice is reconciled.

Creator-supplied secret management and product app deletion remain separate #12/#13 work. This acceptance does not claim arbitrary encoded or transformed secret detection, exact byte counts for transport loss, or a durable replay buffer during collector outages; those limits are explicit in the diagnostics guide.
