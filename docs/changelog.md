# Changelog

## Unreleased

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
