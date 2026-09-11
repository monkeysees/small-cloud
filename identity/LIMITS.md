# Publishing limits and build allowance

All workspaces share installation safety limits of five creator grants, 30 deployed app slots, five active app slots and 1,000 build minutes per UTC calendar month. Owners automatically receive publishing authority and consume a creator grant. Other administrators consume a grant only when separately granted publishing authority. Each workspace grant counts separately, even for the same identity. Creating a workspace does not multiply capacity. Configurable workspace quotas remain #26.

`workspace usage --workspace ID` reports that workspace's counts and build charges/reservations, installation limits (`limit_scope: installation`), and installation-wide remaining build seconds in `available_seconds`. Other workspaces can consume capacity; the displayed workspace counts alone do not promise admission. See [workspace onboarding and selection](WORKSPACES.md).

`small-cloud workspace usage` shows creator, deployed and active counts and limits, together with the current build period, charged seconds, reserved seconds and available seconds. `--json` returns the same accounting fields for automation. Only admitted creators and workspace administrators can inspect usage.

Deployment capacity counts retained apps, including pending first publications and failed publications that have reserved a name. Updating an existing app does not consume another deployed slot. Disabling an app does not free its deployed slot. Active capacity concerns running or starting containers; a deployed app need not be active. An exhausted active slot pool refuses startup without evicting another app. Runtime limits are 0.5 CPU, 512 MiB memory and 128 tasks per app, with temporary files charged to the memory budget.

The [idle lifecycle worker](LIFECYCLE.md) frees slots after 30 HTTP-idle minutes and starts retained releases on demand. Active usage includes queued starts and unconfirmed runtime cleanup. Wake-ups use no build allowance, and publication startup reserves against the same five-slot boundary.

Each accepted build reserves 600 seconds atomically with its creator lock and any new app slot. There is no wait queue for capacity: a competing build from that creator receives `BUILD_BUSY`, and a second operation on the same app receives `OPERATION_CONFLICT`. Retrying the original request ID with identical input observes its original admission without reserving or charging twice.

Admission requires at least 600 available seconds. `ALLOWANCE_RESERVED` means unfinished reservations could return enough time; inspect operations and retry after they settle. `ALLOWANCE_EXHAUSTED` means fewer than 600 seconds would remain even if outstanding builds returned all unused time; wait for the next UTC month. This conservative rule can leave fewer than ten minutes unusable. Neither refusal stops serving apps.

Charge isolated execution through confirmed worker termination, including dependency download and image export, rounded up once to whole seconds and capped at 600 seconds. Upload, VM provisioning, scheduling and runtime startup are excluded. Failed and timed-out builds consume execution time; a build confirmed never started consumes zero. An independent builder-host timer terminates the entire isolated build group after ten minutes even if its controller disconnects.

A build belongs wholly to the UTC month in which it was accepted, including when it executes or finishes in the next month. New-month usage starts at zero; an unfinished creator lock continues across the boundary. Uncertain termination retains its reservation and lock until the operator reconciles the builder. Operation status exposes `reconciliation_required`; a worker restart must never release capacity merely because a process disappeared.
