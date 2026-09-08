# Small Software Cloud pilot specification

Status: testing boundaries confirmed; ready-for-agent.

Published specification: [GitHub issue #1](https://github.com/monkeysees/small-cloud/issues/1).

## Problem Statement

People can use coding agents to create purpose-built software, but publishing it for recurring work with colleagues still requires infrastructure help. Creators need a way to publish from their existing coding workflow, control who can use an app, and update it without routinely losing its data. Colleagues need a discoverable, authenticated place to use that software.

The pilot must establish whether this workflow produces repeated use within a two-week development timebox and a $100/month infrastructure spending target excluding labor. Its first workload is a weekly check-in board for priorities and blockers. Stored data is disposable: users must be able to afford losing it, although routine restarts and redeployments must preserve it.

## Solution

Provide one company workspace in the operator's cloud account. Explicitly admitted creators use an agent-callable CLI to upload a local source folder, build a Dockerfile remotely, and publish an app at a stable URL. An app runs as one Linux HTTP container with its own logical database and optional creator-configured runtime secrets.

Apps initially admit only their creator. The creator can share with the whole workspace, whose explicitly admitted members can then read and modify all app data. Google sign-in and platform-enforced authorization protect every app route. A minimal directory helps members find accessible apps.

The platform handles isolated builds and execution, ordinary redeployment, idle stopping and on-demand starting, bounded diagnostics, and explicit data reset and deletion. It communicates disposable data, resource capacity, credential-backed authority, and startup delays clearly. Infrastructure selection remains a prerequisite to infrastructure implementation rather than an architectural decision made by this spec.

## User Stories

1. As a creator, I want to publish from my existing agent-assisted coding workflow, so that I do not need infrastructure help.
2. As a creator, I want to upload a local source folder using an agent-callable CLI, so that publishing fits my existing development tools.
3. As a creator, I want an isolated remote Dockerfile build, so that publishing does not require local Docker.
4. As a creator, I want to use any language or framework that meets the Linux HTTP container contract, so that templates do not constrain my app.
5. As a creator, I want starter templates that demonstrate repeatable database initialization and explain temporary filesystems, so that I understand the runtime contract.
6. As a creator, I want a published URL and deployment status, so that I can determine whether my app is available.
7. As a creator, I want to authenticate interactively with Google once and retain a revocable CLI credential, so that my agent can subsequently publish under my permissions.
8. As a creator, I want platform credentials excluded from source folders and uploads, so that publishing does not expose my platform authority.
9. As a workspace administrator, I want to explicitly admit members, so that an email domain alone does not grant access.
10. As a workspace administrator, I want to grant creator privileges separately, so that membership does not imply publishing authority.
11. As a creator, I want new apps to be creator-only, so that I can use and inspect them before sharing.
12. As a creator, I want to choose creator-only or workspace-wide sharing, so that I control the audience for my apps.
13. As a workspace member, I want sign-in and app access checked before my request reaches app code, so that private apps remain protected.
14. As an app author, I want the platform to supply a stable user ID, name, and email, so that my app can recognize the signed-in person.
15. As a workspace member, I want a directory of accessible apps with a name, description, creator, and link, so that I can find relevant software.
16. As a workspace member, I want to read and modify shared app data, so that colleagues can collaborate without additional per-record permissions.
17. As a creator, I want management permissions limited to my own apps, so that other creators cannot change my deployments or configuration.
18. As a workspace administrator, I want to disable any app, so that I can stop its availability when necessary.
19. As a creator, I want updates to preserve the URL, sharing scope, and database, so that colleagues can keep returning to the same app.
20. As a creator, I want a failed build or startup to leave the current version available, so that an unsuccessful release does not replace it.
21. As a creator, I want data to survive ordinary restarts and redeployments, so that routine publishing supports recurring work.
22. As an app user, I want an explicit explanation that data has no backup or recovery guarantee, so that I use the pilot only for disposable data.
23. As an app author, I want a separate logical database and scoped connection credentials, so that my app cannot access another app's database.
24. As an app author, I want to own schema initialization and migrations, so that my app can evolve its database within the prescribed engine.
25. As a creator, I want failed-update documentation to explain schema compatibility responsibilities, so that I do not mistake container availability for database rollback.
26. As a creator, I want to reset my database after confirming the app name, so that I can start over while retaining code, URL, secrets, and sharing scope.
27. As a creator, I want deletion to disable access immediately and schedule removal of artifacts, database, and secrets after confirmation, so that I can retire an app.
28. As a workspace administrator, I want removing a creator to revoke their platform credentials and disable their apps immediately, so that apps retain an accountable creator.
29. As an app author, I want public internet access, so that my app can call external services.
30. As a workspace administrator, I want apps blocked from private networks, metadata endpoints, and platform management services except for their permitted database connection, so that faulty code cannot cross those boundaries.
31. As a creator, I want to set, replace, delete, and list secret names through the CLI, so that I can manage external credentials independently of source code.
32. As a creator, I want hidden-prompt or stdin secret input without saved-value readback, so that ordinary configuration does not expose secret values.
33. As a creator, I want secrets stored encrypted and supplied only at runtime, so that builds do not receive them.
34. As a creator, I want secret changes to restart the app, so that it uses the saved configuration.
35. As a creator, I want a clear notice when sharing an app with secrets, so that I understand that its users can trigger the credential-backed actions it exposes.
36. As a creator, I want deployment status, build logs, and runtime logs through the CLI, so that I can diagnose my own app.
37. As a workspace administrator, I want access to app diagnostics, so that I can operate the pilot.
38. As a creator, I want bounded logs with seven-day retention and known-secret redaction, so that diagnostics remain useful with reduced exposure and bounded storage.
39. As an app user, I want idle apps to start on demand with a visible loading state, so that I understand a brief startup delay.
40. As an app user, I want an immediate capacity message and retry button when all five active slots are occupied, so that I know why my app cannot start.
41. As an app user, I want actively used apps to remain running when another app requests a slot, so that my work is not interrupted to make room.
42. As a creator, I want clear deployment and runtime limits, so that I understand when capacity prevents publication or execution.
43. As a creator, I want visible workspace build-minute usage, so that I can manage the shared monthly allowance.
44. As a workspace administrator, I want build concurrency, timeout, and allowance enforcement, so that publishing consumes bounded resources.
45. As an app user, I want running apps to remain available after build allowance exhaustion, so that build limits do not interrupt existing work.
46. As a workspace administrator, I want platform content stored and builds and apps executed in EU regions, so that hosting meets the agreed residency boundary.
47. As a workspace administrator, I want spending alerts and a complete infrastructure cost estimate, so that I can manage the monthly spending target.
48. As a colleague, I want to contribute priorities and blockers to a shared weekly check-in board and return the following week, so that the pilot supports real recurring work.

## Implementation Decisions

- **Domain and operating boundary:** Support apps with disposable data. Serve one company workspace in the operator's cloud account, with company approval assumed. The operator is the sole workspace administrator. Membership and creator privileges are separate grants.
- **Publishing interface:** Provide an agent-callable CLI for browser-based Google authentication, source upload, remote Dockerfile builds, publishing, deployment status, diagnostics, sharing, secret management, reset, and deletion. Retain a revocable credential outside source folders and uploaded build contexts. Command syntax, output schemas, and credential protocol are defined in [CLI and platform contracts](contracts.md).
- **Runtime contract:** Run one unprivileged Linux HTTP container per app on a platform-provided port. Supply a connection URL for one prescribed database engine. Container filesystems are temporary; only the database provides persistence. Templates are conveniences and must explain these constraints.
- **Identity and access boundary:** Enforce Google identity, explicit membership, and sharing scope before requests reach apps. Supply stable user ID, name, and email. No publicly accessible container route may bypass enforcement. Trusted identity transport and spoofing prevention are defined in [CLI and platform contracts](contracts.md).
- **Authorization:** Creators manage only their own apps. Ordinary app users cannot perform platform management operations. The administrator can admit members, grant creator privileges, disable any app, and inspect diagnostics. Administrative access to creator-only app content is not specified by the source documents and must not be inferred from diagnostic authority.
- **Sharing and discovery:** Default to creator-only access, with an explicit choice of workspace-wide access. All workspace members can read and modify all data within a workspace-wide app. The directory lists accessible apps with name, description, creator, and link.
- **Execution and network isolation:** Treat generated code as potentially faulty despite creator admission. Isolate build execution and app runtimes. Allow public internet traffic while denying private networks, cloud metadata endpoints, and platform management services, with the specific database exception. Metadata must be unreachable; a low-permission metadata identity is insufficient.
- **Database isolation:** Provision a separate logical database and restricted database user per app. A shared database server is permitted, but one app's credentials must not authenticate to or access another app's database. Separate database network endpoints are unnecessary.
- **Secrets:** Encrypt stored values; deliver them only as runtime environment variables. Provide set, replace, delete, and name-list operations with hidden prompts or stdin for values and no saved-value readback. Builds must not receive runtime secrets. Secret changes restart the app. App code is trusted with its own secrets and can disclose them; authorized users can trigger any exposed credential-backed action. Sharing an app with secrets must explain this authority.
- **Updates and schemas:** Preserve URL, sharing scope, and database on redeployment. Failed builds or startup leave the current container version available. Apps own initialization and migrations; templates demonstrate safe, repeatable startup initialization. Previous-container availability neither reverses schema changes nor guarantees compatibility with a changed database. Recovery may require creator-led schema repair or explicit reset.
- **Lifecycle:** Stop apps after 30 minutes without an HTTP request and start them on demand with a visible loading state. Stopping loses in-memory state. At five active apps, another start request immediately receives a capacity message and retry button; do not evict actively used apps to admit it.
- **Capacity and build accounting:** Support five creators, 30 deployed apps, and five simultaneously active apps. Permit one concurrent build per creator, enforce a ten-minute build timeout, and provide 1,000 shared build minutes per workspace per month. Display usage and refuse further builds when exhausted while keeping running apps available. Enforce runtime-resource limits and refuse new deployments at exhausted capacity. Accounting and UTC month boundaries are defined in [CLI and platform contracts](contracts.md); per-app resources remain behind the hosting gate.
- **Diagnostics:** Make deployment status, build logs, and runtime logs available through the CLI to the creator and administrator. Logs have seven-day retention, bounded volume, truncation at limits, and known-secret-value redaction. Volume, truncation and redaction-retention limits are defined in [CLI and platform contracts](contracts.md). Redaction does not guarantee confidentiality from app code.
- **Reset and deletion:** Require explicit confirmation naming the app for both operations and communicate that recovery is unavailable. Reset erases the database and retains URL, code, secrets, and sharing. Deletion immediately disables access and schedules removal of container artifacts, database, and secrets. Cleanup deadlines, retries and failure visibility are defined in [CLI and platform contracts](contracts.md).
- **Creator removal:** Immediately revoke the removed creator's platform credentials and disable their apps. Do not implicitly transfer ownership.
- **Residency:** Store source, images, databases, secrets, and logs in EU regions and execute builds and apps there. Provider account metadata and support access need not remain entirely in the EU. Creators are responsible for destinations of their configured external API calls.
- **Infrastructure decision and admission gate:** The operator selected Hetzner VM infrastructure in [#17](https://github.com/monkeysees/small-cloud/issues/17), superseding the earlier provider-selection hold. Provisioning is authorized; creator admission requires separate build/runtime isolation checks, EU-residency evidence, measured capacity, a complete cost estimate and verified alerts. The implementation uses PostgreSQL and gVisor with fresh disposable build VMs, without Kubernetes. Retain failed or inconclusive checks in the acceptance report rather than treating provider selection as deployment acceptance.
- **Budget interpretation:** Use the MVP's $100/month infrastructure spending target excluding labor, supported by alerts rather than a guaranteed hard cap. Issue #2 resolves the original pilot ADR's “ceiling” wording to this target; ADR 0001 now agrees. Alerts are not evidence of a technically enforceable cap.

## Testing Decisions

The confirmed primary seam is the externally observable platform workflow: exercise the CLI as a creator or administrator and make authenticated HTTP requests to the directory and published app URLs as different users. Prefer a reusable, minimal HTTP app fixture with database and optional external-service behavior over tests tied to internal modules. At specification review time there was no implementation or test suite to reuse; #17 subsequently added separate operator-infrastructure and isolation checks. The user confirmed this boundary together with the separate infrastructure isolation and EU-residency checks.

Good tests assert outcomes, access boundaries, and preserved or removed data. They must not depend on internal class structure, orchestration objects, or a particular hosting vendor. Deterministic timing and accounting controls may be necessary for lifecycle and quota tests; their concrete design is not yet decided.

- **Publishing and runtime:** Publish a local Dockerfile source folder without local Docker; observe build logs, status, and a working URL. Verify the port and database contract using the published fixture.
- **Identity, sharing, and directory:** Verify unauthenticated, unadmitted, member, creator, other-creator, and administrator behavior. Check creator-only defaults, workspace-wide access, both sharing choices, accessible directory entries, trusted supplied identity, and rejection of management operations by unauthorized actors. Probe for a direct route bypassing platform access checks.
- **Redeployment and persistence:** Write data, restart, idle-stop/start, and redeploy; verify database data and stable URL and sharing. Fail a build and fail startup; verify the current version remains available. Separately demonstrate the documented schema-change caveat without asserting automatic rollback. Do not rely on in-memory or filesystem persistence.
- **Isolation:** Run a bounded deployment-environment probe before hosting selection, then retain repeatable checks for database cross-access denial, metadata denial, private-network and management-service denial, permitted database access, and permitted public internet access. Validate build isolation separately from runtime isolation because successful app requests do not prove build isolation.
- **Secrets:** Verify name-only listing, unavailable saved-value readback, exclusion from builds and source uploads, runtime availability only to the owning app, replacement and deletion taking effect after restart, sharing notice, and known-value log redaction. Do not assert that malicious app code cannot disclose entrusted values.
- **Diagnostics:** Verify creator and administrator access and rejection for other users, bounded/truncated logs, and seven-day retention behavior once concrete limits and timing controls are selected.
- **Lifecycle and quotas:** Verify the 30-minute HTTP-idle threshold, visible startup state, at most five simultaneous active apps under competing requests, immediate capacity feedback with retry, and no eviction of actively used apps. Verify deployed-app capacity, runtime limits, per-creator build concurrency, ten-minute timeout, displayed build usage, and refusal after monthly exhaustion without interrupting running apps.
- **Destructive operations and revocation:** Verify reset and deletion require confirmation naming the app; reset removes database contents while preserving the specified configuration; deletion disables access immediately and ultimately removes the scheduled resources. Verify creator removal immediately invalidates platform credentials and disables owned apps.
- **Residency and cost evidence:** Review deployed service and storage-region configuration, execution regions, capacity estimates, and the complete cost model. These are infrastructure acceptance checks; browser or CLI behavior alone cannot establish them. Verify spending alerts without treating them as a hard cap.
- **Pilot outcome:** Separately from automated checks, observe the first colleague use an agent and CLI to publish the check-in board without operator intervention in deployment. At least two other colleagues must contribute and return for a second weekly check-in. Passing technical tests alone does not satisfy this adoption criterion.

## Out of Scope

- Apps requiring durable data, backup or recovery guarantees, automatic database rollback, and a separate migration runner.
- Platform-managed company integrations and per-user third-party authorization.
- Individual app invitations, group sharing, per-record ownership or roles, and ownership transfer.
- Multiple company workspaces, company-owned deployments, and company-specific environment customization.
- Background workers, scheduled jobs, multi-container deployments, and privileged containers.
- Private package dependencies requiring build credentials.
- Persistent container filesystems, managed uploads, and persistent file storage.
- A graphical debugging console.
- A guaranteed hard spending cap or a blanket guarantee that all provider metadata, support access, and creator-selected external API traffic remain in the EU.
- Selecting an infrastructure architecture without the required isolation, residency, capacity, and cost evidence.

## Further Notes

This specification synthesizes the domain glossary, MVP document, and eight ADRs present in the workspace. The glossary uses app for creator-published software without implying a durability guarantee. Disposable data must still survive routine platform lifecycle operations.

There is no implementation or test suite in the reviewed folder. The project now uses GitHub Issues, with tracker conventions and default triage labels documented in the agent configuration. The publication label is `ready-for-agent`; unresolved infrastructure decisions remain subject to the selection gate below.

The product requirements are substantially defined. The [#17 acceptance report](hosting-acceptance-2026-09-08.md) records the deployed Hetzner/PostgreSQL/gVisor foundation, measured resources and the explicitly approved higher CPX cost. [CLI and platform contracts](contracts.md) resolve CLI, identity, build accounting, log-volume and cleanup semantics for implementation #3. Infrastructure acceptance does not enable creator traffic or establish product completion. The two-week timebox remains a constraint rather than proof that all remaining integration and adoption work fits; the acceptance report identifies that remaining work without weakening isolation or residency requirements.
