# Publishing limits acceptance — 2026-09-09

Local and hosted acceptance for [issue #10](https://github.com/monkeysees/small-cloud/issues/10), against the [capacity and accounting contract](../contracts.md). The implementation is deployed and verified on the existing German hosts, with [recorded live evidence](../evidence/publishing-limits-2026-09-09.json). Installation and reconciliation steps are in the [publishing runbook](../../identity/PUBLISHING.md), and creator-facing behavior is in [publishing limits](../../identity/LIMITS.md).

Authenticated CLI/HTTPS checks verify usage visibility for creators and administrators, denial for ordinary members and unauthenticated callers, persisted reservations after service restart, request replay without double reservation, competing creator/build/deployed-slot admission, and the 30-app boundary while retaining update eligibility. Existing creator-grant tests cover the fifth grant under competition. The existing runtime adapter and resource limits remain in place; their hosted isolation and timeout evidence remains in the [foundation report](hosting-foundation-2026-09-08.md).

Deterministic worker execution checks cover fractional-second rounding, actual failed-build charges, zero-charge unstarted builds, the 600-second cap, unknown termination retaining its reservation and creator lock, exact allowance exhaustion, and an unusable 599-second remainder. A full month's consumption is driven through HTTP admission and worker execution, without directly editing ledger rows. Competing requests cannot reserve the last block twice. December admissions that finish in January settle wholly in December; January starts at zero, while the unfinished creator lock survives the boundary. Exhaustion preserves the existing selected runtime and reports actionable accounting counts.

Trusted builder tests verify that termination evidence is issued only after the execution group is empty, includes elapsed execution, remains unchanged on repeated termination, and is absent when termination cannot be confirmed. The production publishing adapter refuses an artifact with unconfirmed deletion. A review exposed preflight failures that could unnecessarily retain allowance; regressions now cover the real remote CLI's proven-unstarted response and the publishing worker's zero-charge settlement of that response.

Verification used the existing Python 3.11 test environment with the repository's pinned JWT/keyring and starter PostgreSQL dependencies. The full identity suite passed 55 tests, including Docker/PostgreSQL acceptance; the full infrastructure suite passed 84 tests, and the hosting probe fixture suite passed four. After the preflight fix and additional regressions, focused identity suites passed 17 tests and trusted-worker/remote suites passed 21. Pyright 1.1.413 reports zero errors; builder shell syntax and `git diff --check` pass. Independent Standards and Spec reviews have no unresolved findings.

To reproduce with the documented dependencies installed:

```bash
python3 -m unittest discover -s identity/tests -p 'test_*.py'
python3 -m unittest discover -s infra/tests -p 'test_*_cli.py'
python3 -m unittest discover -s probes/hosting/fixture -p 'test_*.py'
npx --yes pyright@1.1.413 --pythonpath "$(command -v python3)"
bash -n infra/builder/run.sh
```

The accounting upgrade does not estimate charges for deployments completed before it was enabled. Unfinished older operations conservatively retain a reservation in their original admission period. Missing termination/timing evidence requires operator reconciliation; this increment does not add an automatic repair command. Configurable quotas and additional workspaces remain #26/#20 work.

## Hosted deployment and acceptance

Pushed `26ae52f` and installed its package, remote coordinator, builder scripts and Caddy usage route on the existing German control host. The installed workstation CLI was updated. Caddy configuration validation and all three service health checks passed; both existing app routes and selected deployments were unchanged. The retained creator/administrator credential successfully read usage, while an unauthenticated usage request returned HTTP 401.

A real CLI publication reserved 600 seconds. Replaying its request ID returned the same operation without another reservation, and a competing publication returned `BUILD_BUSY`. Its fresh CX23 builder in Nuremberg was deleted after confirmed termination. The build executed for 14.889615702 seconds, charged 15 seconds, released its unused reservation and produced a creator-protected app returning HTTP 200. Runtime inspection confirmed gVisor, 0.5 CPU, 512 MiB memory and 128 tasks.

A subsequent Dockerfile requested a 900-second sleep. The independent builder timer terminated execution after 600.013726374 seconds; accounting capped the charge at 600, released the reservation and reported `BUILD_FAILED`. The fresh Nuremberg builder was deleted. The previously selected release returned HTTP 200 during the attempt and after its failure, with its deployment ID unchanged. Final shared usage was 615 charged seconds, zero reserved seconds and 59,385 available seconds.

Deployment verification also found that the new accounting receipt was absent from the diagnostic janitor's recognized files. Fix `8931e58` was reviewed, pushed and installed; its retention regression failed before the fix and passed afterward, along with all ten artifact-CLI tests and typechecking. Receipts now follow the existing seven-day diagnostic retention.

Removed only the temporary `limits-acceptance-10` app, runtime, database, encrypted credentials and source staging; retired its registry/runtime artifacts under the existing janitors. Preserved the genuine 615-second build charge and both pre-existing apps. Deployed and active app counts returned to two. No further manual or browser check is required for #10 acceptance. Full allowance exhaustion, UTC-month rollover and competing final-slot boundaries remain deterministic local evidence rather than artificial changes to the production quota or clock.
