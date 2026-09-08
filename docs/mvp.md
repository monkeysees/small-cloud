# Small Software Cloud MVP

## Objective

A creator publishes agent-built software without infrastructure help, shares it with colleagues, and those colleagues return to use it for real work. The first workload is a weekly check-in board for priorities and blockers.

## Scope

- Two-week development timebox; $100/month infrastructure spending target excluding labor, with alerts rather than a guaranteed hard cap.
- One company workspace, hosted in the operator's cloud account with company approval assumed.
- A small, explicitly admitted group of creators; other workspace members can use shared apps.
- An agent-callable CLI uploads a local source folder for an isolated remote Dockerfile build, returns logs, and publishes a URL.
- One Linux HTTP container per app, using a platform-provided port and a separate database. Languages and frameworks are unrestricted within this contract; templates are conveniences.
- Data survives ordinary restarts and redeployments but has no backup or recovery guarantee. Reset and deletion are explicit operations.
- User-entered data is the pilot workload's starting point. Apps may access the public internet and use creator-configured secrets. Platform-managed company integrations, apps requiring durable data, background workers, scheduled jobs, multi-container deployments, and privileged containers are deferred.

## Identity and sharing

Use Google sign-in with an explicit account allowlist for workspace membership and separately assigned creator privileges. The platform enforces access before requests reach an app and supplies a stable user ID, name, and email. No publicly accessible container route may bypass this enforcement.

The operator is the sole workspace administrator and admits members and creators. Creators manage only their own apps, including sharing, redeployment, data reset, and deletion. Reset and deletion require explicit confirmation. The administrator can disable any app; ordinary app users cannot perform these platform operations.

The CLI opens a browser for interactive Google sign-in and retains a revocable credential for subsequent agent-driven publishing under that person's creator permissions. Credentials stay outside source folders and uploaded build contexts.

Apps start creator-only. The creator can explicitly share an app with the whole workspace. All workspace members can read and modify all data within a workspace-wide app; per-record roles, individual invitations, and group sharing are deferred.

A minimal workspace directory lists accessible apps with their name, description, creator, and link.

## Network, secrets, and diagnostics

Apps may access the public internet. Private networks, cloud metadata endpoints, and platform management services are blocked, with a specific exception for the database connection. Metadata endpoints must be unreachable; exposing metadata with a low-permission identity is not an accepted substitute. Each app has a separate logical database and restricted database user on a potentially shared server: it must not be able to authenticate to or access other apps' databases. Separate database network endpoints are not required.

Creators can set, replace, delete, and list secret names through the CLI, but cannot read saved values back. Input uses hidden prompts or stdin rather than command-line argument values. Secrets are stored encrypted and delivered only as runtime environment variables; builds cannot access them. Secret changes restart the app to apply the saved configuration. Private package dependencies requiring build credentials are unsupported initially.

App code is trusted with its own secrets and can disclose them through responses, logs, or outbound requests. Everyone allowed to use an app can trigger whatever credential-backed actions its code exposes. Sharing an app with secrets includes a clear notice of this authority; creators are responsible for appropriately scoped credentials. Per-user third-party authorization and platform-managed company integrations remain deferred.

Deployment status, build logs, and runtime logs are available through the CLI to the app's creator and workspace administrator, with seven-day retention, bounded volume, truncation at volume limits, and redaction of known secret values. Redaction does not guarantee that app code cannot disclose secrets. A graphical debugging console is deferred.

## Infrastructure direction

Source, images, databases, secrets, and logs must be stored in EU regions; builds and apps must execute there. This does not require all provider account metadata or support access to remain in the EU. Creator-configured external API calls may send data elsewhere, with destinations the creator's responsibility.

The hosting provider and orchestration choice are deliberately deferred. Both managed Kubernetes and VM-based sandboxed containers remain candidates; none of the discussed architectures is accepted. Select an approach before infrastructure implementation using a bounded isolation test, EU-residency check, capacity check, and complete cost estimate. Kubernetes concepts, if used, must not be exposed in the creator workflow.

Prefer managed container execution with an explicit isolation boundary and an isolated build service. Provide one prescribed database engine, a separate database per app, and scoped credentials through a connection URL. Concrete services, engine, and costs remain to be evaluated against the runtime contract and budget.

## Updates and capacity

Updates retain the app URL, sharing scope, and database. Failed builds or startup leave the current version available. The app author is responsible for database schema compatibility during the pilot.

Keeping the previous container available does not undo schema changes made by a failed update or guarantee that the previous version works against the changed database. Recovery may require the creator's agent to repair the schema or explicitly reset disposable data; automatic database rollback is outside scope.

Idle apps stop after 30 minutes without an HTTP request and start on demand. In-memory state is lost on stopping. A brief startup delay is acceptable, with a visible loading state. When all five active slots are occupied, another app immediately shows a capacity message with a retry button; actively used apps are not evicted to make room.

The pilot supports five creators and 30 deployed apps, with at most five simultaneously active apps. Show a clear capacity message when another app cannot start. Allow one concurrent build per creator with a ten-minute build timeout and a workspace-wide allowance of 1,000 build minutes per month. Show build-minute usage and refuse further builds when the allowance is exhausted; running apps remain available. Enforce runtime-resource limits and refuse new deployments when capacity is exhausted. Per-app resource limits remain to be selected and costed. Spending alerts support the monthly target but do not guarantee a hard cap.

Only database persistence is provided. Container filesystems are temporary and files may disappear on restart; managed uploads and persistent file storage are outside scope. Templates must make this explicit.

Apps own schema initialization and migrations, with templates demonstrating safe, repeatable startup initialization. The platform does not provide a separate migration runner.

## Reset, deletion, and membership removal

Reset erases the app database while retaining its URL, code, secrets, and sharing scope. Deletion immediately disables access and schedules removal of the app's container artifacts, database, and secrets. Both operations require confirmation naming the app and offer no recovery in this pilot.

Removing a creator from the workspace immediately revokes their platform credentials and disables their apps. Ownership transfer is deferred so active apps are not left without an accountable creator.

## Acceptance

The first colleague uses an agent and the CLI to publish the check-in board without operator intervention in deployment. At least two other colleagues contribute and return for a second weekly check-in.

Verify creator-only access, cross-app isolation, failed-update behavior, and data surviving redeployment separately from the usage experiment.

## Outstanding design decisions

Deferred: hosting provider, orchestration, build execution, and database technology. These choices must satisfy the accepted runtime, isolation, EU-residency, capacity, and budget requirements before infrastructure implementation. Per-app resource limits remain unresolved. [CLI and platform contracts](contracts.md) define the CLI, identity, accounting, diagnostics and lifecycle interfaces for implementation. Product and CLI design can proceed without selecting a provider.
