# Changelog

## Unreleased

## 0.4.0 — 2026-09-11

- Add #33 offline `app check` with safe source manifests, limits, actionable errors and explicit local/remote verification boundaries, plus bundled runtime guidance without a local Docker prerequisite.

- Add #47 coordinated server deployment, automatic worker restoration, acknowledged diagnostics readiness, bounded recovery and persistent maintenance stop/resume while preserving operation locks and accounting.

- Verify #47 hosted deployment, in-flight restart, publication, idle wake, runtime logs and fault recovery; preserve both original apps and remove acceptance resources while retaining 10 build seconds.

- Finalize #20 with user acceptance and remove only the empty test-one workspace and its exclusive admission, preserving the other workspaces.

- Restore the hosted publishing, lifecycle and diagnostics workers to active service and document restarting them after identity-service upgrades.

## 0.3.1 — 2026-09-11

- Publish and verify all four native CLI downloads and public installers; deploy automatic owner creator grants and preserve the operator credential and workspace default.

- Build and verify Linux x86-64 downloads on Ubuntu 22.04 so the CLI runs on glibc 2.35 workstations.

## 0.3.0 — 2026-09-11

- Grant new workspace owners administrator and creator privileges automatically, count them toward creator capacity, and verify publishing without an override uses the first associated workspace.

- Verify #20 hosted upgrade, two cloud builds, workspace/database isolation, retries and restart; clean up acceptance resources and document remaining Google/browser checks.

- Add #20 platform-admin workspace creation, exact-email onboarding, saved and explicit CLI targets, isolated duplicate app names/data, browser directory, workspace-bound retries and shared installation safety limits.

- Add #46 public Small Cloud landing page with testing-stage and manual-admission notices, persistent app databases, backup/recovery limits, and CLI installation guidance.

- Fix simultaneous open CLI approval forms by retaining valid same-account browser sessions without extending expiry or weakening origin/CSRF checks.
- Complete #32 live combined/split Google approval, credential retention, and targeted revocation acceptance.

## 0.2.0 — 2026-09-09

- Add #32 headless `auth login start/finish` with protected pending state, resumable browser approval, actionable setup status, and readable authentication outcomes.
- Publish v0.2.0 on all four native targets with split-login, file/OS credential storage, public installation, and retained hosted-identity verification.

## 0.1.0 — 2026-09-09

- Publish #31 standalone downloads and one-command installation; verify all four native platforms, file/OS credentials, bundled TLS trust, public installation without Python, and retained hosted credentials.

- Add #31 native standalone CLI packaging and checksum-verified installation for Linux/macOS ARM64/x86-64, bind the CLI to the hosted service, and preserve exact-origin credentials with an undistributed HTTPS test launcher.

- Verify #30 through 68 installed-executable discovery/hosted-read checks and the final CLI/HTTPS suite; record acceptance without modifying hosted apps or services.

- Add #30 grouped CLI commands, shared offline help and scoped versioned catalog, bundled task guides, readable app inspection and actionable human errors; remove superseded command paths and verify CLI/HTTPS authorization contracts.

- Deploy #12 and verify exact multiline runtime secrets, hidden input, sharing/authorization boundaries, encrypted storage, retained-value redaction and failed/interrupted restart recovery; remove acceptance resources and retain 41 build seconds.

- Add #12 creator-owned encrypted runtime secrets with hidden/stdin input, saved-configuration restarts, sharing acknowledgement, seven-day retired-value redaction and local CLI/HTTP/external-service regression coverage.

- Deploy #9 and verify a real 30-minute idle stop, competing wake-ups, retained data, capacity/loading responses and failed/interrupted startup recovery; remove four acceptance apps/builders, retain 43 build seconds, and close acceptance with the operator accepting the unverified browser checks.

- Add #9 authenticated HTTP idle stop/start with retained database data, visible loading and explicit retry, atomic five-app reservations shared with publishing, in-flight request protection, and restart-safe cleanup with local CLI/HTTP/PostgreSQL regression coverage.

- Complete #8 hosted redeployment acceptance across seven EU builds, verify preserved releases/data and creator-led schema repair, remove temporary resources, and preserve both existing apps and the 92-second build charge.

- Verify #8 redeployment with uploaded Docker/HTTP/PostgreSQL fixture variants, preserved URL/sharing/data, separate build/startup failures and schema-repair regression checks; document compatible migrations and the limits of previous-container recovery.

- Deploy #11 and verify live build/runtime eviction, database-value redaction and collector restart; preserve both existing apps and remove acceptance resources while retaining real build charges.

- Add #11 authorized build/runtime diagnostics with bounded snapshots, stable cursors, seven-day retention, encrypted known-value redaction, streamed EU collection and visible collection gaps without raw Docker log caching.

- Deploy #10 and verify live usage, replay/concurrency refusal, a 15-second successful build charge and 600-second timeout charge with the previous app still serving; remove the temporary acceptance app and preserve existing apps.

- Include #10 accounting receipts in the existing seven-day diagnostic cleanup, preserving recent reconciliation evidence without leaving expired staging directories behind.

- Add #10 authenticated publishing usage, durable monthly build reservations and termination-based settlement, conservative exhaustion feedback, and deterministic capacity/concurrency/month-boundary regression checks.

- Deploy #19, migrate all three hosted identities and both apps into the initial workspace, restart identity/publishing services, and verify retained credentials, unchanged database data and private-content denial.

- Add #19 initial-workspace migration with separate membership and platform roles, saved defaults, preserved app URLs/data/credentials, workspace-authorized publishing and sharing, and restart/CLI/PostgreSQL regression checks; additional workspaces remain unavailable.

- Record the confirmed multi-workspace design, owner and administrator boundaries, migration and capacity rules; publish specification #18 and implementation tickets #19–#28.

- Complete #7 live acceptance with separate Google accounts: filtered discovery, owner-only sharing, administrator private-content denial, shared member writes and existing-session revocation with data preserved.

- Deploy #7 sharing and the directory route to the hosted pilot; verify owner CLI/HTTP smoke checks and restore the disposable probe to creator-only.

- Add #7 creator-owned sharing in both directions, an authenticated accessible-app directory, and shared CLI/HTTP/PostgreSQL access checks.

- Consolidate acceptance reports under `docs/acceptance/<topic>-YYYY-MM-DD.md`, extract identity/publishing outcomes from runbooks, and update report links.

- Ship and close #6 with verified persistence/isolation evidence, unblock #9, and remove the two acceptance apps and their resources while preserving the existing publishing probe.

- Add #6 database-backed starter with repeatable initialization, parameterized entry writes, visible disposable-data notice and CLI/authenticated HTTP persistence and cross-app PostgreSQL isolation checks.

- Show deployment upload/stage progress and periodic elapsed-time updates on stderr during CLI waits; record operator-confirmed browser sign-in, network checks, readiness denial and other-account denial.

- Add #5 local source validation, durable remote publishing, creator-only authenticated app ingress, bounded build-log/status commands and a reusable HTTP acceptance fixture on the EU hosting foundation.

- Complete #4 acceptance with operator-confirmed macOS creator sign-in, administrator-command denials and unadmitted Google-account rejection.

- Allow CLI authentication from the home directory while rejecting credential storage within Git checkouts, worktrees and Dockerfile source roots independently of the current directory.
- Verify live Google administrator sign-in, separate creator privileges, retained CLI authentication and immediate credential revocation; leave the workstation signed in with a tested replacement credential.
- Fix browser CLI approval by preserving the form's Origin header with a strict-origin referrer policy, while retaining exact-origin and CSRF checks.
- Deploy Google identity routes on the control host, bootstrap the confirmed administrator, install the local CLI and redact OAuth callback details from proxy-error logs; keep app publishing routes closed.
- Add #4 Google browser approval, retained revocable CLI credentials, explicit administrator admission and separate five-creator grants, with CLI/HTTPS acceptance checks and an identity-service runbook; live Google verification is recorded in the identity evidence.
- Use “app” for creator-published software across the glossary, specifications, operator guidance and GitHub tracker; retain disposable-data limits and deployed infrastructure identifiers.
- Complete #17 infrastructure acceptance with live concurrency/isolation/renewal evidence, release-aware retention, crash-export hardening and independent host-loss alerts; retain the closed creator gateway and document approved costs.
- Enable Hetzner API-based estimated spending alerts with retained builder costs, monthly caps, traffic, quoted VAT, ECB conversion and explicit coverage/staleness warnings.

- Remove the CX watcher and support explicitly approved permanent CPX32/CPX42 provisioning in Germany; defer cost optimization.

- Add a persistent German CX availability watcher with automatic bounded procurement, durable create reconciliation and operator notifications for #17.
- Add verified-host SMTP installation and alert activation; record confirmed delivery while billing evidence and deployed acceptance remain pending.
- Record verified Resend sending domain, protected SMTP configuration and operator-confirmed test delivery for #17; deployed alert automation remains pending.
- Add reproducible Hetzner provisioning, gVisor runtime, disposable EU builders, database isolation, retention and health monitoring for #17; record temporary live validation and keep creator admission closed pending acceptance.
- Document agent access to Hetzner and Cloudflare, operator settings, local credential paths and outstanding provisioning checks.
- Record approved Hetzner setup and per-build CX23 → CPX22 fallback across Germany without an initial prewarmed pool; retain the live deployment acceptance gate.
- Define CLI and platform contracts for #3, including authentication, trusted identity, build accounting, bounded logs, lifecycle failures and acceptance examples.
- Migrate all pilot issues into GitHub Project with execution order, phases and readiness, and replace the superseded hosting dependency with infrastructure #17.
- Evaluate pilot hosting for #2, retain database and deployment isolation probes, record the unresolved selection gate, and clarify the $100/month spending target.
