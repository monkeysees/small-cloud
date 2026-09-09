# Acceptance reports

Reports use `<topic>-YYYY-MM-DD.md`, dated by the acceptance or validation milestone. Each report preserves its dated observations and limitations; later confirmations and cleanup are recorded explicitly. Supporting machine-readable evidence stays in [docs/evidence](../evidence/).

| Report | Scope |
| --- | --- |
| [Hosting validation — 2026-09-08](hosting-validation-2026-09-08.md) | Historical #2/#17 validation, including incomplete checks; superseded by hosting foundation acceptance. |
| [Hosting foundation — 2026-09-08](hosting-foundation-2026-09-08.md) | #17 infrastructure acceptance. |
| [Workspace identity — 2026-09-09](workspace-identity-2026-09-09.md) | #4 identity and CLI authentication acceptance. |
| [App publishing — 2026-09-09](app-publishing-2026-09-09.md) | #5 publication and protected app ingress acceptance. |
| [Publishing limits — 2026-09-09](publishing-limits-2026-09-09.md) | #10 local CLI/HTTP capacity, monthly accounting, concurrency and termination-evidence acceptance. |
| [App sharing — 2026-09-09](app-sharing-2026-09-09.md) | #7 local CLI/HTTP sharing, directory and shared PostgreSQL acceptance. |
| [App database — 2026-09-09](app-database-2026-09-09.md) | #6 database persistence, isolation and acceptance-resource cleanup. |
| [Initial workspace migration — 2026-09-09](workspace-migration-2026-09-09.md) | #19 local acceptance and hosted migration/restart, saved defaults, workspace authorization and retained PostgreSQL data. |

Setup and repeatable procedures remain in the [identity runbook](../../identity/README.md), [publishing runbook](../../identity/PUBLISHING.md), [database starter guide](../../identity/fixture/README.md), and [infrastructure runbook](../../infra/README.md).
