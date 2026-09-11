# Workspace identity and CLI

The public homepage is served by Caddy from the [static landing page](../landing/README.md), with testing-stage and manual-admission notices. It requires no sign-in; app content and management APIs retain their existing authentication requirements.

For creator-only/workspace-wide access and the accessible app directory, see [sharing and discovery](SHARING.md).

For source upload, remote builds and protected app URLs, see [publishing](PUBLISHING.md).

For preserved releases during failed updates and schema compatibility responsibilities, see [redeployment](REDEPLOYMENT.md).

For `small-cloud workspace usage`, deployment capacity and the shared monthly build allowance, see [publishing limits](LIMITS.md).

For HTTP idle stopping, on-demand loading, active capacity and retry behavior, see [app lifecycle](LIFECYCLE.md).

For confidential app configuration and restart behavior, see [runtime secrets](SECRETS.md).

For authorized status, build/runtime log snapshots, redaction and retention, see [diagnostics](DIAGNOSTICS.md).

For app-scoped PostgreSQL persistence, author-owned initialization and the disposable-data starter, see [database acceptance](../docs/acceptance/app-database-2026-09-09.md) and the [starter guide](fixture/README.md).

Implements [#4](https://github.com/monkeysees/small-cloud/issues/4) and [#19](https://github.com/monkeysees/small-cloud/issues/19) against the [CLI and identity contracts](../docs/contracts.md). One operator bootstraps the initial workspace owner and platform administrator, explicitly admits Google emails, and grants creator privileges separately. A member can sign in to establish their immutable user ID; owners automatically receive creator privileges; other members and administrators need a separate grant. There are at most five creator grants, including owners. See [initial workspace migration](WORKSPACE-MIGRATION.md) before upgrading an existing installation. See [workspace creation and selection](WORKSPACES.md) for #20 onboarding, independent roles, explicit automation targets and shared installation safety limits.

## Discover the CLI

Start with `small-cloud`, `small-cloud app --help`, or `small-cloud catalog app --json`. Read bundled guidance using `small-cloud guide` and `small-cloud guide getting-started`; these work offline without credentials or this checkout. Groups are `app`, `workspace`, `auth` and `operation`; superseded top-level command paths have been removed. App list/status have readable default results, and every command supports `--json` for the unchanged versioned envelope. Use `small-cloud app list` to discover accessible apps; detailed `app status NAME` requires the creator or a workspace administrator.

Catalog version 1 describes only delivered commands, including permissions, inputs, output contracts and effects. Setup status and split login are implemented in #32. Later #29 slices deliver project linking, default completion waits, live logs and additional workspace commands.

## Install the CLI

Use a standalone Linux or macOS executable for ARM64 or x86-64; Python and a source checkout are not required. See [installation and downloads](../distribution/README.md). Installation does not sign in or modify shell startup files. Add the install directory (default `~/.local/bin`) to PATH when needed.

The CLI always connects to `https://small-cloud.monkeysees.one`. No endpoint setup is needed: `--endpoint` is removed, and old endpoint environment variables and config files are ignored. Existing credentials for the hosted origin keep working; credentials belonging to other origins are not used. No repository configuration or `.env` is loaded.

```bash
small-cloud auth login
small-cloud auth login --no-browser
small-cloud --json auth status
small-cloud auth logout
small-cloud auth revoke --all
```

Start login from your working directory and compare the browser approval code with the terminal. Only approve a login you initiated. `--no-browser` prints a link and code for manual opening. `--no-input` and `--json` prohibit terminal prompts while permitting explicitly requested browser approval. CLI polling starts at five seconds and honors backoff. A login expires after ten minutes; credential delivery is single-use. A lost delivery requires a new login, not replay of the poll. No Google tokens are delivered to the CLI.

For a headless session, run `small-cloud auth login start --json --no-input`. Give the returned `verification_url` and `user_code` to the human for browser approval. Run `small-cloud auth login finish ATTEMPT_ID --json --no-input`, substituting the returned `attempt_id`, on the same machine and OS account. Start never opens a browser; finish waits up to the remaining ten-minute lifetime, optionally bounded by `--timeout SECONDS`, and saves the credential. Pending timeout/interruption returns the attempt ID and an exact resume command. Expired or consumed attempts require a new start. No credential or poll secret needs to pass through the agent session.

Pending state uses independent random attempt IDs and owner-only files beside the origin-bound credential, protected by the same directory and command lock. The attempt ID contains no poll secret. Finish refuses unsafe permissions, symlinks, hardlinks, or a mismatched origin; successful delivery and observed expiry remove pending state. Abandoned attempts expire server-side after ten minutes; their protected local files may be deleted. Pending state is never stored in a project folder.

Multiple open approval forms for the same Google account remain usable: repeated verified sign-in retains a valid management session and its original expiry. Changing accounts creates a new session, and an old form must be reloaded to display and approve the new identity. Origin and CSRF checks remain required.

Credentials last 30 days and are bound to the exact HTTPS origin. The CLI uses the native macOS Keychain or Linux Secret Service when available, otherwise an owner-only file in `$XDG_STATE_HOME/small-cloud` (default `~/.local/state/small-cloud`). A locked available keyring fails rather than silently saving plaintext. Directories use 0700 and files 0600; symlinks, hardlinked files and unsafe permissions are refused. Authentication works from your home directory. Credential storage inside a Git checkout, Git worktree or Dockerfile source root is refused regardless of the current directory. Keep the state directory outside all source folders; validation of explicitly selected upload roots and mandatory credential exclusions belong to publishing #5. No token flags, token environment variables, saved-value readback or redirect forwarding are supported. Commands sharing a local credential are serialized by a nonblocking lock.

`auth status` reports the service endpoint, current user, workspace, roles, credential ID and expiry without its value, plus `missing_steps` and `next_steps`. Missing/revoked credentials retain their authentication error and exit 3, with endpoint, empty identity/workspace and sign-in guidance in error details. Network or access failures retain their distinct error and advise repair before retry. Publishing requires creator privileges independently of administrator/owner status. Use `workspace list`, `workspace select ID` and per-command `--workspace ID`; inaccessible defaults require explicit reselection. Logout first revokes on the server and then removes local storage; offline failure retains the credential for retry. Already revoked logout succeeds. `auth revoke --all` revokes every CLI credential for the caller, including this one, and removes this machine's copy. Other machines see `CREDENTIAL_REVOKED` immediately. Browser sessions are separate and expire after twelve hours; member removal and its session/app invalidation are #14.

## Bootstrap and admission

Create a Google OAuth **web application** client with authorized redirect URI `https://small-cloud.monkeysees.one/auth/callback`. External audience with Testing status is sufficient for the pilot: the requested basic `openid email profile` scopes are exempt from Google's test-user allowlist and seven-day authorization expiry. See [Google's audience rules](https://support.google.com/cloud/answer/15549945?hl=en). No Google client secret belongs in Git, CLI arguments, browser JavaScript or an app. The service validates signature, issuer, audience, expiry, nonce, verified email and authorized party, with state and PKCE protecting the authorization-code exchange.

On the control host, create a dedicated `small-cloud-identity` system user, a 0700 `/srv/small-cloud/identity` owned by that user, and `/etc/small-cloud/identity/server.json` owned by that user with mode 0600. Its parent directory should be 0700 owned by the service user. Write these fields through a protected editor or credential handoff, never an echoed command:

```json
{
  "origin": "https://small-cloud.monkeysees.one",
  "google_client_id": "YOUR_WEB_CLIENT_ID",
  "google_client_secret": "YOUR_WEB_CLIENT_SECRET",
  "state_directory": "/srv/small-cloud/identity"
}
```

Install this package into `/opt/small-cloud-identity` using a Python virtual environment. The operator confirmed `monkeyseesone@gmail.com`, also the alert recipient, as the sole administrator. Bootstrap once as the service user:

```bash
sudo -u small-cloud-identity /opt/small-cloud-identity/bin/small-cloud-identity --config /etc/small-cloud/identity/server.json bootstrap monkeyseesone@gmail.com
```

Repeating the same email returns the original administrator; changing it is refused. Bootstrap does not grant creator privileges. Install [the systemd unit](small-cloud-identity.service), run `systemctl daemon-reload`, then `systemctl enable --now small-cloud-identity`. The service binds only `127.0.0.1:8765`. Merge [the site fragment](Caddyfile.fragment) into the existing management site and [the logging fragment](Caddyfile.global.fragment) into the global options block. Proxy errors can log callback URLs even when access logging is disabled; the global filter removes request URI and headers. Validate the complete Caddy configuration, then restart Caddy after the service is healthy: this installation uses `admin off`, so API-based reload is unavailable. Preserve the site's existing certificate/storage settings. Follow [publishing installation](PUBLISHING.md#operator-installation) for the worker and authenticated app origins. Do not re-run infrastructure `control/bootstrap.sh`, which would replace this configuration with the original closed gateway.

Sign in as administrator, then admit each member:

```bash
small-cloud workspace member add colleague@example.com
# The colleague signs in and gives the administrator the user ID from auth status.
small-cloud workspace creator grant usr_RETURNED_USER_ID
```

An admitted email is pending until its first verified Google sign-in atomically binds it to Google's subject and an immutable random user ID. A subsequent email change updates profile information without transferring ownership; a replacement Google subject cannot take over the old email's bound admission. A pending member must sign in before a creator grant. Existing admission/grant is a no-op. The sixth creator receives `CREATOR_CAPACITY` (exit 5), even under competing grants. Creator privileges do not grant administrator commands.

Admission and grant mutations accept `--request-id UUID`; IDs are printed before transmission and returned in JSON. The server retains actor-scoped results for seven days, rechecks current authority on retries, returns the original result for matching inputs and refuses changed inputs with `REQUEST_CONFLICT`. Credential revocation retries are scoped to the originating credential. Retry an uncertain command with its original ID.

## HTTP boundary and operation

Management requests use `Authorization: Bearer …` and mutation header `X-Request-ID`; do not place either credential or OAuth code in command arguments or access logs. Browser cookies are Secure, HttpOnly, SameSite=Lax, host-only `__Host-` cookies. The management approval form requires both CSRF token and matching Origin. CLI management routes never accept browser cookies as bearer credentials. [App ingress](PUBLISHING.md) uses separate origins and host-bound sessions, checks authorization before forwarding, and strips platform authentication material.

| Route | Input/result |
| --- | --- |
| `POST /api/auth/login` | Random 32-byte base64url `poll_secret` saved in protected local pending state; returns verification URL, user code, expiry and interval. Retrying the same secret returns its existing pending login. |
| `POST /api/auth/poll` | `poll_secret`; pending/backoff or one-time credential delivery after approval. |
| `GET /api/auth/status` | Bearer credential; current identity, roles, credential ID and expiry. |
| `POST /api/auth/logout` | Bearer credential, request ID and `{}`; revoke this credential. |
| `POST /api/auth/revoke` | Bearer credential, request ID and `{}`; revoke all caller CLI credentials. |
| `POST /api/admin/member/add` | Administrator bearer, request ID and `{"email":"…"}`. |
| `POST /api/admin/creator/grant` | Administrator bearer, request ID and `{"user_id":"…"}`. |
| `GET /health` | Loopback readiness check with the configured management Host header. |

The one-time login delivery is confidential protocol traffic; the CLI removes the credential before rendering the standard output envelope. Server state stores credential and browser-session verifiers, not their reusable values. SQLite transactions serialize admission, binding, grants, delivery and revocation on the trusted EU control disk. The protected database also contains short-lived OAuth nonce/PKCE material, pending logins and seven-day request receipts. Expired transient rows are pruned on new logins, with at most 100 login sessions and 200 OAuth attempts outstanding. Credential history stays available for idempotent logout; monitor disk use. This is disposable control-host state without backup guarantees; loss requires rebootstrap and user sign-in.

## Verification

See [workspace identity acceptance — 2026-09-09](../docs/acceptance/workspace-identity-2026-09-09.md) for recorded local and deployed outcomes.

Install the package and starter dependencies in your test environment, then run from the repository root. The HTTP/database suite also requires Docker for its disposable PostgreSQL 16 server:

```bash
python3 -m pip install . -r identity/fixture/requirements.txt
npx --yes pyright@1.1.413 --pythonpath "$(command -v python3)"
python3 -m unittest discover -s identity/tests -p 'test_*.py'
python3 -m unittest discover -s infra/tests -p 'test_*_cli.py'
python3 -m unittest discover -s probes/hosting/fixture -p 'test_*.py'
```

Identity acceptance launches the real CLI in subprocesses and the real HTTP service over locally trusted TLS. Only Google is replaced by a signed-token HTTP fixture; production configuration cannot select a fixture issuer or bypass verification. Assertions cover administrator bootstrap, browser approval, retained credentials, explicit roles, capacity, Google subject binding, invalid identity claims, CSRF, revocation, request replay, and protected storage.

Dependency review (2026-09-08): [PyJWT](https://pypi.org/project/PyJWT/2.12.1/) provides maintained JWT validation with the [PyCA cryptography](https://github.com/pyca/cryptography) RSA backend; [keyring](https://pypi.org/project/keyring/25.7.0/) provides native OS storage. These established projects have active upstream releases and commits. Direct runtime dependencies are pinned in `pyproject.toml`. Google behavior follows the [official OpenID Connect documentation](https://developers.google.com/identity/openid-connect/openid-connect); no custom signature implementation is used.
