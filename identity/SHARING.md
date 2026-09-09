# Sharing and discovery

Implements [#7](https://github.com/monkeysees/small-cloud/issues/7) against [the pilot sharing boundary](../docs/adr/0002-pilot-sharing-boundary.md). New apps default to creator-only. Sign in with the operator-supplied endpoint, then use:

```bash
small-cloud share check-in --scope workspace-wide
small-cloud directory
small-cloud directory --json
small-cloud share check-in --scope creator-only
```

Only an app's admitted creator can change its sharing scope. Workspace-wide admits every explicitly admitted member, including other creators and the administrator. Members can read and modify all data the app exposes; there are no per-record roles or private records within a shared app. App authors should implement this common data model rather than treating the supplied user ID as a record-access boundary. Administrator diagnostic privileges do not grant access to creator-only content or permission to change another creator's sharing.

`directory` lists accessible apps sorted by immutable app name. Each entry contains `name`, `description`, `creator` (stable `id` and current display `name`) and `url`. It includes authorized apps that are starting or unavailable; a directory entry does not promise runtime readiness. Disabled apps and apps belonging to removed members are excluded. The authenticated API is `GET /api/directory`, returning `data:{apps:[...]}` in the standard envelope. It requires a CLI bearer credential, as do the other management APIs.

Returning an app to creator-only removes it from other members' directory results and denies their subsequent requests, including requests using an existing app session. It preserves the URL and all app data, including other members' contributions. Previously delivered content cannot be recalled. Every app route and method is authorized before app code, including assets and attempted upgrades. The gateway currently rejects upgrades and does not support streaming. Users still permitted by the scope sign in separately at the app URL using Google; workspace membership is explicit, never inferred from an email domain.

Sharing accepts `--request-id UUID`. Matching retries return the original receipt without applying the old scope again; different inputs with that ID return `REQUEST_CONFLICT`. The server rechecks current owner, creator and membership authority and disabled state before returning a receipt. A same-scope request succeeds without restarting the app. The HTTP mutation is `POST /api/apps/<name>/share` with `{"scope":"creator-only"}` or `{"scope":"workspace-wide"}` and `X-Request-ID`. Unknown fields and unsupported scopes are rejected.

Creator-configured app secrets and their required authority acknowledgement are implemented in dependent issue #12. This implementation has no app-secret configuration; `secret_authority_acknowledged` is false. Platform-managed database credentials do not count as creator-configured app secrets.

For installation, update the identity service package and include `/api/directory` from [the Caddy fragment](Caddyfile.fragment) in the management site's proxy routes. Follow the existing [publishing installation procedure](PUBLISHING.md#operator-installation) for validating and restarting Caddy. No schema migration or runtime redeployment is needed for sharing.

Verification uses the real CLI and locally trusted HTTPS identity/gateway service, a signed Google provider fixture, and real disposable PostgreSQL. See [sharing acceptance](../docs/acceptance/app-sharing-2026-09-09.md) for results and limits.
