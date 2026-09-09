# Publishing limits acceptance — 2026-09-09

Local acceptance for [issue #10](https://github.com/monkeysees/small-cloud/issues/10), against the [capacity and accounting contract](../contracts.md). The implementation is verified locally; the hosted service has not been upgraded or exercised with the new accounting receipts in this task. Installation and reconciliation steps are in the [publishing runbook](../../identity/PUBLISHING.md), and creator-facing behavior is in [publishing limits](../../identity/LIMITS.md).

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
