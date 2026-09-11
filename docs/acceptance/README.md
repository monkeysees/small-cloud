# Acceptance reports

Reports use `<topic>-YYYY-MM-DD.md`, dated by the acceptance or validation milestone. Each report preserves its dated observations and limitations; later confirmations and cleanup are recorded explicitly. Supporting machine-readable evidence stays in [docs/evidence](../evidence/).

| Report | Scope |
| --- | --- |
| [Deployment completion — 2026-09-11](deployment-completion-2026-09-11.md) | #34 readiness waits and recovery, frozen Linux verification, five hosted deployments, retained data/sharing and scoped cleanup. |
| [App preparation — 2026-09-11](app-preparation-2026-09-11.md) | #33 offline runtime guidance and local source checks; v0.4.0 native release and actual public installation on all four targets. |
| [Required service recovery — 2026-09-11](service-recovery-2026-09-11.md) | #47 automatic worker restoration, acknowledged readiness, graceful in-flight restart, fault recovery, maintenance and scoped hosted cleanup. |
| [Workspace CLI release — 2026-09-11](cli-workspaces-2026-09-11.md) | v0.3.1 native downloads, public installation, glibc compatibility and hosted owner-role defaults. |
| [Hosted workspaces — 2026-09-11](workspaces-hosted-2026-09-11.md) | #20 live upgrade, two cloud builds, workspace/app/database isolation, restart, scoped cleanup and final user acceptance. |
| [Multiple workspaces — 2026-09-10](workspaces-2026-09-10.md) | #20 local workspace creation/selection, scoped roles and retries, browser/gateway boundaries and duplicate-name PostgreSQL isolation. |
| [CLI distribution — 2026-09-09](cli-distribution-2026-09-09.md) | #31 standalone releases, fixed-service credentials, native OS storage and public installation on Linux/macOS ARM64/x86-64. |
| [CLI discovery — 2026-09-09](cli-discovery-2026-09-09.md) | #30 installed offline discovery, hosted read-only human/JSON app inspection and local CLI/HTTPS authorization acceptance. |
| [Hosting validation — 2026-09-08](hosting-validation-2026-09-08.md) | Historical #2/#17 validation, including incomplete checks; superseded by hosting foundation acceptance. |
| [Hosting foundation — 2026-09-08](hosting-foundation-2026-09-08.md) | #17 infrastructure acceptance. |
| [Workspace identity — 2026-09-09](workspace-identity-2026-09-09.md) | #4 identity and CLI authentication acceptance. |
| [App publishing — 2026-09-09](app-publishing-2026-09-09.md) | #5 publication and protected app ingress acceptance. |
| [Diagnostics — 2026-09-09](diagnostics-2026-09-09.md) | #11 authorized bounded logs, redaction, real EU volume/restart checks and acceptance cleanup. |
| [Publishing limits — 2026-09-09](publishing-limits-2026-09-09.md) | #10 local quota/month boundaries and live CLI usage, successful/timeout accounting, preserved app availability and acceptance cleanup. |
| [App sharing — 2026-09-09](app-sharing-2026-09-09.md) | #7 local CLI/HTTP sharing, directory and shared PostgreSQL acceptance. |
| [App redeployment — 2026-09-09](app-redeployment-2026-09-09.md) | #8 local and hosted builds, retained URL/sharing/data, failed updates, committed-schema repair and acceptance cleanup. |
| [App database — 2026-09-09](app-database-2026-09-09.md) | #6 database persistence, isolation and acceptance-resource cleanup. |
| [Initial workspace migration — 2026-09-09](workspace-migration-2026-09-09.md) | #19 local acceptance and hosted migration/restart, saved defaults, workspace authorization and retained PostgreSQL data. |

Setup and repeatable procedures remain in the [identity runbook](../../identity/README.md), [publishing runbook](../../identity/PUBLISHING.md), [database starter guide](../../identity/fixture/README.md), and [infrastructure runbook](../../infra/README.md).
