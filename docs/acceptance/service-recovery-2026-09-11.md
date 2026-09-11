# Required service recovery — 2026-09-11

Acceptance for [#47](https://github.com/monkeysees/small-cloud/issues/47), against starting commit `2a79287`. Implementation and review fixes are committed as `ca44c18` and `7b84993`. The [operator procedure](../../identity/SERVICES.md) and [redacted evidence](../evidence/service-recovery-2026-09-11.json) record deployment, readiness, recovery and cleanup separately from local tests. No standalone CLI release is needed.

## Local verification

The first real user-systemd regression reproduced diagnostics remaining inactive after identity stop followed by start. An explicit `systemctl restart` already recovered the original units on this system; the failing separate-stop/start path was preserved in the regression before adding identity's worker dependencies.

The full suite passed **209 tests**: 116 identity, 89 infrastructure and four hosting-fixture tests. Review added five operator-command regressions; all **14 service tests** then passed, along with seven existing diagnostics tests after the framing refinement. This covers 214 distinct tests across the full and focused runs. Pyright 1.1.413 reported zero errors. Standards and Spec review findings were resolved and both reviewers reported zero remaining findings.

Service tests use actual user-systemd transactions with isolated unit names, real process locks and readiness notifications. They cover initial activation using the boot dependency graph, identity stop/start and repeated restart, delayed/unavailable diagnostics, recovery exhaustion, worker/collector failure and maintenance. Operator-command tests execute deployment, check, maintenance-stop and resume, including failed package installation and concurrent-command refusal. Root identity, installation paths, package installation and SSH transport are substituted external boundaries; HTTP readiness, collector challenges and systemd remain real. Unsupported platforms explicitly skip systemd tests; this run did not skip them.

These local checks establish the available-runtime boot ordering. No hosted control-host reboot or runtime-host reboot was performed; runtime-host reboot reconciliation and disaster recovery remain outside #47.

## Hosted acceptance

The existing German control/runtime pair was retained. There were no pending operations and two existing apps before deployment. The source/wheel/unit bundle was checksum-verified; protected rollback package files and units remain under `/root/small-cloud-47/rollback`. The supported deployment command installed the package and four units and reported success only after full readiness. A subsequent identity restart replaced all four service processes and restored them automatically.

The designated `service-recovery-47` app built on one fresh Nuremberg CX23 builder and reached a usable authenticated URL. While its operation was `building`, another identity restart waited **54.3 seconds** for the publication to finish successfully before replacing services. The operation remained succeeded with no error; no replay or uncertain-reservation repair was needed.

An authenticated request wrote a disposable database marker. Only this acceptance app's idle timestamp was advanced by 1,801 seconds; the normal lifecycle worker stopped it. Its next authenticated request returned seven HTTP 503 loading responses followed by HTTP 200, and the database marker survived. This is an accelerated idle-clock check, not another wall-clock 30-minute idle trial. Runtime logs exposed the expected startup marker and the existing interruption indication.

Killing the collector's SSH tunnel recovered forwarding without restarting the collector. Killing each worker/collector main process recovered automatically. Attempts to start duplicate publishing, lifecycle and collector daemons were refused by their kernel locks. Main PIDs and restart counters then remained stable for 12 seconds. Explicit maintenance-stop prevented all four units from starting even when directly requested; the full readiness command failed during maintenance, and explicit resume restored readiness.

The final reviewed package was deployed through the same procedure. Its wheel SHA-256 is `c3327465669111860d375d0bb05dea33a4684e09aa9bd18d94dae2c3a21fc668`. Installed worker, collector and service-orchestration modules and all four unit files matched the reviewed checkout byte-for-byte.

## Cleanup and handback

Only the designated acceptance app, its PostgreSQL database/role, encrypted app credentials, diagnostics, runtime allocation and source staging were removed. Its artifact references were retired for the existing retention mechanism. Builder `165493132` was confirmed deleted; its **10 charged build seconds** remain in the allowance ledger. Final provider inventory contains only the two original permanent hosts, with no orphan builders.

Before/after fingerprints matched for original app metadata, users, workspaces, memberships, credential records, both original app databases and identity/publishing configurations. The retained CLI credential still identified the same operator with the same `ws-initial` default. Final state contains the two original apps, zero pending operations, no maintenance marker, and all four required services ready/enabled with stable PIDs and restart counters.
