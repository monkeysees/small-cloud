# Public landing page

The public homepage at https://small-cloud.monkeysees.one introduces Small Cloud, its testing stage, manual admission, and persistent app databases. It distinguishes persistence across restarts and redeployments from the testing-stage lack of backup and recovery guarantees. Already-admitted users can read the installer and follow CLI sign-in guidance. No signup form or external assets are required.

Caddy serves the two static assets directly, independently of the identity service. Copy `index.html` and `landing.css` to `/srv/small-cloud/landing` on the existing control host (directory mode 0755, file mode 0644). Merge the `@landing` handler and 404 fallback from `identity/Caddyfile.fragment` into `/etc/caddy/small-cloud-management.fragment`, retaining its CLI download handler and all authentication/API routes. Preserve the main Caddyfile and app-origin configuration.

Before applying, save the existing management fragment and validate the complete candidate configuration using `caddy validate --config PATH --adapter caddyfile`. Install the candidate fragment, validate the active configuration, and restart Caddy because this installation has `admin off`. Roll back the fragment and restart if service checks fail. Do not reapply the original infrastructure bootstrap.

Verify public HTTPS GET and HEAD responses, exact HTML/CSS content, HTTP-to-HTTPS redirect, installer availability, unauthenticated API denial and unknown-path 404s. Inspect the page in desktop and mobile browser sizes, exercise the access anchor and installer link, and confirm there is no horizontal overflow. App origins remain behind the existing authenticated gateway.

Run `python3 landing/verify.py` to check the public deployment against the checkout. See [deployment acceptance](../docs/acceptance/landing-page-2026-09-09.md) for browser sizes and recorded results.
