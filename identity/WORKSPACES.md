# Create and use workspaces

Issue [#20](https://github.com/monkeysees/small-cloud/issues/20) implements workspace creation and selection under [ADR 0009](../docs/adr/0009-multiple-workspaces.md). Onboarding remains operator-assisted. A platform administrator creates each workspace with exactly one designated owner:

```bash
small-cloud workspace create "Design team" --owner owner@example.com --request-id UUID --json
```

Substitute a fresh UUID, retain it, and reuse the same command and UUID after an uncertain result. Matching retries return the original workspace, including after service restart; changed inputs fail with `REQUEST_CONFLICT`. Workspace IDs are immutable. Display names need not be unique. Creation admits the designated owner, consumes one creator grant, and fails with `CREATOR_CAPACITY` if all five grants are occupied. It does not admit the platform administrator unless they are the owner, or reserve runtime capacity. It does not accept `--workspace`.

The owner signs in with their explicitly designated Google email using `small-cloud auth login` or visits `/directory` in a browser. Verified Google sign-in binds a pending admission to one immutable identity. Email-domain matching grants nothing. One identity can belong to multiple workspaces with separate roles. Owners automatically receive administrator and creator privileges. After Google sign-in they can publish using their first workspace as the default, without a creator grant or `--workspace`. Other members require a separate creator grant:

```bash
small-cloud workspace list --json
small-cloud workspace select ws_FROM_LIST
small-cloud workspace member add colleague@example.com --workspace ws_FROM_LIST
# After the colleague signs in and supplies the user ID from auth status:
small-cloud workspace creator grant usr_FROM_AUTH_STATUS --workspace ws_FROM_LIST
```

The first admission automatically becomes the saved default, without prompting. The default lives on the service identity and applies across that user's CLI credentials. Adding another membership does not change it. `workspace select` saves an accessible workspace ID or exact unambiguous name; `--workspace` overrides the default for one command without saving it. Workspace listing and selection remain available when the old default is inaccessible. Fresh sign-in then returns no selected workspace and directs explicit selection; app commands fail until an accessible target is supplied. There is no silent fallback. Use IDs when names are ambiguous. Existing IDs take precedence over display names; an inaccessible ID cannot fall back to a similarly named workspace.

Automation should always specify the immutable workspace ID:

```bash
small-cloud app deploy . --name dashboard --description "Team dashboard" --workspace ws_FROM_LIST --json
small-cloud app status dashboard --workspace ws_FROM_LIST --json
small-cloud operation status d_FROM_DEPLOY --workspace ws_FROM_LIST --json
small-cloud app share dashboard --scope workspace-wide --workspace ws_FROM_LIST --json
```

The CLI resolves and pins the workspace for the command, including any `--wait` polling. Retry the original request ID with the original workspace. A changed workspace is a changed mutation even when the app name, actor and source bytes match. Foreign operation IDs, unsupported app-ID inputs, inaccessible workspaces and ambiguous names fail; commands never choose a similarly named app elsewhere. App names are unique only within their fixed workspace; duplicate names have distinct immutable app IDs, URLs, databases and secrets. There are no app moves or cross-workspace sharing operations.

Creator-only content requires the creator's current membership in the app's workspace. Workspace-wide content requires current membership in that workspace. Workspace and platform administration grant no private-content or saved secret-value access. App URL routing uses the app's workspace independently of the user's default. `app list` and the browser `/directory` show only accessible apps in the selected workspace. Browser workspace links select a view without changing the saved CLI default; an explicit browser target survives Google sign-in.

## API

Management APIs require a bearer credential. Mutations require `X-Request-ID: UUID`. Workspace-scoped routes accept `X-Workspace` with an immutable ID or percent-encoded exact display name; omission selects the saved default. Duplicate, empty, inaccessible or ambiguous targets are rejected.

| Route | Body/result |
| --- | --- |
| `GET /api/workspaces` | Accessible `workspaces` with IDs, names, owner IDs and the caller's roles; `default_workspace`. |
| `POST /api/workspaces/create` | `{ "name": "Design team", "owner_email": "owner@example.com" }`; returns `workspace:{id,name,owner_id}`. Platform administrator only; no workspace override. |
| `POST /api/workspaces/select` | `{ "workspace": "ws_FROM_LIST" }`; returns `workspace` and `default_workspace`. |
| `POST /api/admin/member/add` | `{ "email": "colleague@example.com" }`; workspace administrator only. |
| `POST /api/admin/creator/grant` | `{ "user_id": "usr_FROM_AUTH_STATUS" }`; workspace administrator only; member must already have verified identity. |

Existing app, operation, usage, directory and auth-status routes honor `X-Workspace`. The gateway accepts bearer credentials or its existing host-bound browser sessions; an explicit bearer `X-Workspace` must also match the app URL. Authentication revocation remains identity-wide. Browser `/directory` uses its management session cookie, while `/api/directory` continues to require a bearer credential.

## Installation and limits

Stop the publishing and identity services before upgrading as described in [migration](WORKSPACE-MIGRATION.md). Install the updated package and merge `/directory`, `/api/workspaces` and `/api/workspaces/*` from [the Caddy fragment](Caddyfile.fragment) into the management site. Validate Caddy configuration, run the original operator bootstrap as preflight, and restart the services. Install [CLI v0.3.1 or later](../distribution/README.md) for the workspace commands; the hosted service includes the automatic owner creator grant.

Startup upgrades the single-workspace constraints and global app-name uniqueness transactionally while preserving existing identity/app IDs, URLs, data references, roles, credentials and operations. Do not downgrade to the single-workspace package. The persisted-receipt contract is explicit: existing unexpired initial-workspace fingerprints keep their format; additional-workspace fingerprints include the resolved ID. An old receipt can only replay in its original initial workspace. No legacy role-writing or alternate authorization path is retained.

Until configurable workspace allowances land, the installation shares five creator grants, 30 deployed app slots, five active app slots and 60,000 build seconds per UTC month. A grant of the same identity in two workspaces consumes two creator grants. Builds reserve 600 seconds and retain the existing creator/build serialization and replacement-headroom rules. Usage counts and charged/reserved build time are workspace-scoped; limits and remaining `available_seconds` are installation-wide, so other workspaces can consume capacity. Exhaustion does not stop already serving apps. Creating a workspace never multiplies these limits.

Start the diagnostics collector before publishing apps: Docker's syslog driver requires `/run/small-cloud-diagnostics.sock` for runtime startup.

Ownership transfer/delegation, removal/readmission, suspension, deletion, and configurable workspace allowances remain subsequent tickets. [Local acceptance](../docs/acceptance/workspaces-2026-09-10.md) uses real CLI/HTTPS, signed Google fixtures and real PostgreSQL. [Hosted acceptance](../docs/acceptance/workspaces-hosted-2026-09-11.md) verified the upgrade, two real builds, isolation and restart; the user accepted testing as complete on 2026-09-11. Complete-service acceptance remains #28 after its predecessor workflows land.
