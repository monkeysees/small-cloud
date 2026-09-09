# Public landing page acceptance — 2026-09-09

Implemented and deployed [#46](https://github.com/monkeysees/small-cloud/issues/46) at https://small-cloud.monkeysees.one/.

The responsive static page describes purpose-built apps, creator-only/workspace-wide sharing, and CLI publishing. Both the hero and access section identify testing and manual admission. The access section explicitly rules out self-service signup. Following the operator’s copy correction, the page highlights each app’s persistent database and retention across restarts and redeployments, separately from the testing-stage lack of backup/recovery guarantees. Already-admitted users receive installer, PATH, Google sign-in and bundled-guide instructions.

## Verified

- Candidate and active Caddy configurations validated successfully. Only the management site's old text fallback changed: exact homepage/CSS routes now serve static files, with a 404 for unknown paths. CLI, authentication/API, app-origin and TLS settings were retained. Caddy restarted successfully; identity remained active.
- Unauthenticated public HTTPS GET/HEAD returned 200 with correct content types and exact checkout bytes for both assets. No session cookies were set. HTTP redirected to HTTPS.
- Installer returned 200; authentication and directory APIs returned 401; approval without a code retained 400. Unknown, source-document and internal paths returned 404. The existing protected app gateway returned 401 AUTH_REQUIRED; authenticated directory inspection still succeeded.
- User-authorized isolated Chromium passed at 1440×1100, 390×844 and 320×740. Verified rendered headings/notices, stylesheet loading, no horizontal overflow, keyboard skip link, access-section navigation and installer link. Inspected desktop and mobile full-page screenshots. No page/JavaScript errors were observed. This was Chromium coverage, not a cross-browser certification.
- `python3 landing/verify.py`, Python compilation and `git diff --check` passed. No application or identity source changed, so their full suites were not repeated.

Machine-readable public/browser results are in [the evidence file](../evidence/landing-page-2026-09-09.json). Re-run `python3 landing/verify.py` from the checkout for public routing/content checks. Deployment and rollback instructions are in [the landing runbook](../../landing/README.md).

The publishing, lifecycle and diagnostics workers were already inactive before this deployment (publishing stopped at 16:59 UTC; this deployment followed at approximately 17:11 UTC). Their state was preserved. This acceptance establishes the public landing page and access boundaries, not current app publishing or runtime readiness. No apps, memberships, credentials or DNS records were changed.

The persistence wording correction was deployed by atomically replacing the static HTML, without restarting services. Public content/routing checks and the three Chromium viewport checks passed again.
