# Workspace identity and CLI

For source upload, remote builds and protected app URLs, see [publishing](PUBLISHING.md).

For app-scoped PostgreSQL persistence, author-owned initialization and the disposable-data starter, see [database acceptance](DATABASE.md) and the [starter guide](fixture/README.md).

Implements [#4](https://github.com/monkeysees/small-cloud/issues/4) against the [CLI and identity contracts](../docs/contracts.md). One operator bootstraps the sole administrator, explicitly admits Google emails, and grants creator privileges separately. A member can sign in to establish their immutable user ID; membership and administrator authority alone do not grant publishing privileges. There are at most five creators, including the administrator if separately granted that role.

## Install the CLI

Use Python 3.11+ on Linux or macOS. From this checkout, install into a virtual environment outside source folders:

```bash
python3 -m venv "$HOME/.local/share/small-cloud-venv"
"$HOME/.local/share/small-cloud-venv/bin/python" -m pip install .
"$HOME/.local/share/small-cloud-venv/bin/small-cloud" --help
```

Add that environment's `bin` directory to your PATH. The operator supplies the HTTPS endpoint. Set `SMALL_CLOUD_ENDPOINT` or put `{"endpoint":"https://small-cloud.monkeysees.one"}` in `~/.config/small-cloud/config.json` (or `$XDG_CONFIG_HOME/small-cloud/config.json`). `--endpoint` overrides both; no repository configuration or `.env` is loaded.

```bash
small-cloud auth login
small-cloud auth login --no-browser
small-cloud --json auth status
small-cloud auth logout
small-cloud auth revoke --all
```

Start login from your working directory and compare the browser approval code with the terminal. Only approve a login you initiated. `--no-browser` prints a link and code for manual opening. `--no-input` refuses login; `--json` still allows explicit browser approval and emits one result object. CLI polling starts at five seconds and honors backoff. A login expires after ten minutes; credential delivery is single-use. A lost delivery requires a new login, not replay of the poll. No Google tokens are delivered to the CLI.

Credentials last 30 days and are bound to the exact HTTPS origin. The CLI uses the native macOS Keychain or Linux Secret Service when available, otherwise an owner-only file in `$XDG_STATE_HOME/small-cloud` (default `~/.local/state/small-cloud`). A locked available keyring fails rather than silently saving plaintext. Directories use 0700 and files 0600; symlinks, hardlinked files and unsafe permissions are refused. Authentication works from your home directory. Credential storage inside a Git checkout, Git worktree or Dockerfile source root is refused regardless of the current directory. Keep the state directory outside all source folders; validation of explicitly selected upload roots and mandatory credential exclusions belong to publishing #5. No token flags, token environment variables, saved-value readback or redirect forwarding are supported. Commands sharing a local credential are serialized by a nonblocking lock.

`auth status` reports current user, roles, credential ID and expiry without its value. Logout first revokes on the server and then removes local storage; offline failure retains the credential for retry. Already revoked logout succeeds. `auth revoke --all` revokes every CLI credential for the caller, including this one, and removes this machine's copy. Other machines see `CREDENTIAL_REVOKED` immediately. Browser sessions are separate and expire after twelve hours; member removal and its session/app invalidation are #14.

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
small-cloud admin member add colleague@example.com
# The colleague signs in and gives the administrator the user ID from auth status.
small-cloud admin creator grant usr_RETURNED_USER_ID
```

An admitted email is pending until its first verified Google sign-in atomically binds it to Google's subject and an immutable random user ID. A subsequent email change updates profile information without transferring ownership; a replacement Google subject cannot take over the old email's bound admission. A pending member must sign in before a creator grant. Existing admission/grant is a no-op. The sixth creator receives `CREATOR_CAPACITY` (exit 5), even under competing grants. Creator privileges do not grant administrator commands.

Admission and grant mutations accept `--request-id UUID`; IDs are printed before transmission and returned in JSON. The server retains actor-scoped results for seven days, rechecks current authority on retries, returns the original result for matching inputs and refuses changed inputs with `REQUEST_CONFLICT`. Credential revocation retries are scoped to the originating credential. Retry an uncertain command with its original ID.

## HTTP boundary and operation

Management requests use `Authorization: Bearer …` and mutation header `X-Request-ID`; do not place either credential or OAuth code in command arguments or access logs. Browser cookies are Secure, HttpOnly, SameSite=Lax, host-only `__Host-` cookies. The management approval form requires both CSRF token and matching Origin. CLI management routes never accept browser cookies as bearer credentials. [App ingress](PUBLISHING.md) uses separate origins and host-bound sessions, checks authorization before forwarding, and strips platform authentication material.

| Route | Input/result |
| --- | --- |
| `POST /api/auth/login` | Random 32-byte base64url `poll_secret` held in CLI memory; returns verification URL, user code, expiry and interval. Retrying the same secret returns its existing pending login. |
| `POST /api/auth/poll` | `poll_secret`; pending/backoff or one-time credential delivery after approval. |
| `GET /api/auth/status` | Bearer credential; current identity, roles, credential ID and expiry. |
| `POST /api/auth/logout` | Bearer credential, request ID and `{}`; revoke this credential. |
| `POST /api/auth/revoke` | Bearer credential, request ID and `{}`; revoke all caller CLI credentials. |
| `POST /api/admin/member/add` | Administrator bearer, request ID and `{"email":"…"}`. |
| `POST /api/admin/creator/grant` | Administrator bearer, request ID and `{"user_id":"…"}`. |
| `GET /health` | Loopback readiness check with the configured management Host header. |

The one-time login delivery is confidential protocol traffic; the CLI removes the credential before rendering the standard output envelope. Server state stores credential and browser-session verifiers, not their reusable values. SQLite transactions serialize admission, binding, grants, delivery and revocation on the trusted EU control disk. The protected database also contains short-lived OAuth nonce/PKCE material, pending logins and seven-day request receipts. Expired transient rows are pruned on new logins, with at most 100 login sessions and 200 OAuth attempts outstanding. Credential history stays available for idempotent logout; monitor disk use. This is disposable control-host state without backup guarantees; loss requires rebootstrap and user sign-in.

## Validation and live acceptance

The identity service is installed on control host `165120313` in Nuremberg, using the operator-provided Google web client and administrator `monkeyseesone@gmail.com`. It runs as the dedicated `small-cloud-identity` user. On this workstation, `~/.local/bin/small-cloud` points to the installation in `~/.local/share/small-cloud-venv`, and `~/.config/small-cloud/config.json` selects the live HTTPS endpoint. [Deployment evidence](../docs/evidence/identity-2026-09-08.json) records live route denials, protected configuration, service/listener state and a forced proxy-error log-redaction check. Responses use `Referrer-Policy: strict-origin`: unlike `no-referrer`, it preserves the Origin header required for HTML form approval while excluding URL paths and queries from referrers.

On 2026-09-08 the operator completed real Google sign-in and browser approval. Fresh CLI invocations verified retained credentials and the separately granted creator role. A second browser approval produced a replacement credential; revoking the original immediately caused authenticated HTTP status to return `CREDENTIAL_REVOKED`, repeated revocation succeeded, and the replacement remained authorized. The workstation is left signed in as member, creator and administrator. The full alternate-identity/role matrix and five-creator boundary pass in the local signed-provider suite; the operator subsequently verified a separate creator on macOS with retained member/creator roles, denial of both administrator commands, and rejection of an unadmitted Google account. These alternate-identity results are operator-reported, not direct agent observations.

Install the package and starter dependencies in your test environment, then run from the repository root. The HTTP/database suite also requires Docker for its disposable PostgreSQL 16 server:

```bash
python3 -m pip install . -r identity/fixture/requirements.txt
npx --yes pyright@1.1.413 --pythonpath "$(command -v python3)"
python3 -m unittest discover -s identity/tests -p 'test_*.py'
python3 -m unittest discover -s infra/tests -p 'test_*_cli.py'
python3 -m unittest discover -s probes/hosting/fixture -p 'test_*.py'
```

Identity acceptance launches the real CLI in subprocesses and the real HTTP service over locally trusted TLS. Only Google is replaced by a signed-token HTTP fixture; production configuration cannot select a fixture issuer or bypass verification. Assertions cover administrator bootstrap, browser approval, retained credentials, explicit roles, capacity, Google subject binding, invalid identity claims, CSRF, revocation, request replay, and protected storage.

Local verification on 2026-09-08 passed: 14 identity acceptance tests, 80 infrastructure tests, four hosting-fixture tests, the production Pyright check, wheel installation/CLI entry-point smoke check, and the PostgreSQL 16 own-database/cross-database isolation probe. Independent Standards review has no remaining findings; the live acceptance gap was subsequently resolved by the operator-reported checks below.

Local checks do not establish deployed acceptance. The Google web client, administrator/creator sign-in, retained credential and revocation checks above were verified against the live HTTPS endpoint while app routes remained closed for #4. The operator confirmed the remaining deployed creator/admin-denial and unadmitted-account checks passed on a separate macOS machine. Member-only behavior and the five-creator boundary are covered by the local suite; no separate live member-only or quota probe is claimed. Together these checks complete #4 acceptance. See [publishing](PUBLISHING.md) for subsequent #5 implementation and evidence; workspace sharing/directory, creator removal and integrated infrastructure verification remain #7, #14 and #15.

Dependency review (2026-09-08): [PyJWT](https://pypi.org/project/PyJWT/2.12.1/) provides maintained JWT validation with the [PyCA cryptography](https://github.com/pyca/cryptography) RSA backend; [keyring](https://pypi.org/project/keyring/25.7.0/) provides native OS storage. These established projects have active upstream releases and commits. Direct runtime dependencies are pinned in `pyproject.toml`. Google behavior follows the [official OpenID Connect documentation](https://developers.google.com/identity/openid-connect/openid-connect); no custom signature implementation is used.
