# Initial workspace migration

Issue [#19](https://github.com/monkeysees/small-cloud/issues/19) moves the installation into one explicit workspace, `ws-initial` (display name `Initial workspace`). Creation and selection now land in #20; see [workspace onboarding and upgrade](WORKSPACES.md). Delegated administration, ownership transfer and recovery remain subsequent work under specification #18.

The existing operator becomes the workspace owner and a platform administrator. Ownership includes workspace-administrator authority; it does not grant creator privileges. Existing creator grants are preserved separately. Platform-administrator status alone grants neither workspace admission management nor private app content. App access requires admitted membership in the app's workspace and permission under its current sharing scope. The owner can inspect the existing diagnostics as a workspace administrator, but cannot change another creator's sharing or publish without a creator grant.

Every existing identity, including pending admissions, receives a saved default of `ws-initial`. This preference is persisted on the service identity and used by existing CLI credentials; no local configuration migration or workspace prompt is needed. `small-cloud --json auth status` and completed login return `workspace` (`id`, `name`, `owner_id`), `default_workspace` and a separate `platform_administrator` boolean. The existing `roles` list describes workspace membership, creator and administrator grants. A missing or inactive saved membership denies authenticated workspace workflows; commands never retarget themselves.

## Operator procedure

Let any in-progress deployment finish before stopping the worker, or follow the existing publishing reconciliation procedure. Stop `small-cloud-publishing` and `small-cloud-identity`, install the updated package into the existing service virtual environment, then run bootstrap as the identity service user with the original operator email. Opening the protected identity database applies the migration; repeated bootstrap returns the existing owner. Bootstrap is the migration preflight before starting either service.

```bash
sudo systemctl stop small-cloud-publishing small-cloud-identity
# Install the updated package into /opt/small-cloud-identity here.
sudo -u small-cloud-identity /opt/small-cloud-identity/bin/small-cloud-identity --config /etc/small-cloud/identity/server.json bootstrap monkeyseesone@gmail.com
sudo systemctl start small-cloud-identity small-cloud-publishing
small-cloud --json auth status
small-cloud --json directory
```

Do not run the older package after migration: identity-level membership/creator/administrator columns and the sole-administrator index are removed. The new schema stores membership grants separately, an owner on the workspace, a platform role on the identity, and a fixed workspace on every app. The #20 upgrade removes the initial-workspace constraint and replaces global app-name uniqueness with workspace-scoped uniqueness while retaining app IDs and state.

Migration uses one SQLite write transaction for workspace state, role conversion and existing app assignments. Inconsistent operator ownership, invalid role values, partial workspace schemas, orphan app ownership or inconsistent workspace references fail startup visibly with `MIGRATION_REQUIRED`. The transaction rolls back; repair the reported control-state inconsistency before retrying. Do not reset the database to hide a migration failure. Fresh installations use the same bootstrap command and do not grant creator privileges automatically.

The named persisted-data contracts are immutable identity/app IDs, app names and URLs, sharing scopes, deployment records, runtime targets and app-scoped PostgreSQL/storage identifiers. Migration does not contact PostgreSQL or rebuild app containers. Existing CLI credential verifiers, browser/app sessions and unexpired request receipts retain their identifiers and formats; current workspace authority is rechecked when used. No dual role-writing path or fallback to the removed identity-level grants remains. The disposable-data and EU-hosting boundaries are unchanged.

## Verification

Recorded outcomes and limits are in [initial workspace migration acceptance](../docs/acceptance/workspace-migration-2026-09-09.md).

Run with the repository dependencies installed; the database test requires Docker:

```bash
python3 -m unittest identity.tests.test_workspace_migration -v
python3 -m unittest identity.tests.test_database_http.DatabaseAcceptance.test_legacy_control_migration_preserves_database_cli_and_redeployment -v
```

The frozen legacy schema comes from commit `27c98a8`. Checks exercise retained credentials, pending Google admission, login, actual service restart, publication, both sharing scopes, directory and gateway denials, role separation, invalid-state rollback/retry and authenticated second-workspace creation after upgrading to #20. The Docker/PostgreSQL test writes an app row, loads realistic running control state into that legacy schema, migrates/restarts the service at the same endpoint, uses the retained CLI credential and redeploys while checking the row, URL and sharing scope. These commands provide local acceptance; hosted deployment and migration outcomes are recorded separately in the acceptance report.
