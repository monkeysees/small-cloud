# Update an app and recover from failure

Publish to the same app name to update its code:

```bash
small-cloud app deploy ./my-app --name my-app --wait
small-cloud app status my-app --json
small-cloud operation status --request-id UUID_FROM_DEPLOY --json
small-cloud app logs my-app --source build --json
```

The app keeps its URL, creator-only or workspace-wide sharing scope, and database. The old container remains selected during the build and candidate startup. Routing switches only after the candidate answers `GET /_small-cloud/ready` with HTTP 200. Implement readiness after initialization has completed. Successful replacement discards the old container's temporary files and in-memory state.

A failed build or startup leaves the previous release selected. Status reports that release in `active_deployment_id` and the failed attempt in `latest_operation`, with `BUILD_FAILED` or `STARTUP_FAILED` and an explanatory message. Reading a failed operation exits successfully because the read succeeded; `app deploy --wait` returns the operation's failure exit code. Correct the source and deploy again with a new request ID. After a timeout or lost connection, inspect the original request ID before retrying. Infrastructure or cleanup failures that report `reconciliation_required` need operator inspection before another update can proceed.

## Schema changes are the creator's responsibility

The candidate and old release use the **same database**. Keeping the old container does not roll back committed schema changes, restore rows, or guarantee that its database queries still work. Status `availability: running` describes the selected runtime; it does not prove every app feature remains healthy.

Use compatible migrations in app initialization. Prefer adding structures that both releases can use, move code and data over in stages, and remove old structures only after no running release needs them. Make initialization repeatable, serialize overlapping migrations, and use transactions where appropriate. The [starter](fixture/README.md) demonstrates transactional initialization with an advisory lock; `CREATE TABLE IF NOT EXISTS` alone does not upgrade an existing table. There is no separate platform migration runner or automatic database rollback.

For example, a candidate can commit a rename of `entries.value` and then fail startup. The old container still answers its identity route, but its reads and writes using `value` fail. Recovery requires creator-owned compatible code or schema repair. A reviewed repair can restore the expected column and preserve rows; make repair initialization safe to repeat before relying on it in a running release.

If the data can be discarded, explicit database reset is another recovery option once lifecycle issue [#13](https://github.com/monkeysees/small-cloud/issues/13) is implemented. Its specified contract requires confirming the app name and retains code, URL, secrets and sharing while erasing database contents. Reset is not currently available in the CLI and is not automatic failed-update recovery. Do not substitute an unreviewed destructive migration for confirmation. The pilot provides no backup or recovery guarantee.

The [redeployment acceptance report](../docs/acceptance/app-redeployment-2026-09-09.md) records regression coverage and its local infrastructure limits.
