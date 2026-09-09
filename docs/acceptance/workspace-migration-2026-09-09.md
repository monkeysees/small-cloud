# Initial workspace migration acceptance — 2026-09-09

Local implementation acceptance for [#19](https://github.com/monkeysees/small-cloud/issues/19), following [specification #18](https://github.com/monkeysees/small-cloud/issues/18) and [ADR 0009](../adr/0009-multiple-workspaces.md). Upgrade instructions and preserved-data contracts are in the [migration runbook](../../identity/WORKSPACE-MIGRATION.md).

## Observed results

A frozen pre-workspace schema populated with an operator, creator, member, pending admission, credential verifiers, app sessions and a shared app migrates into `ws-initial`. Retained credentials report unchanged identity IDs and workspace roles, the saved default and separate platform-administrator status. The operator becomes owner without gaining creator privileges. Pending admission, signed-provider browser approval and CLI sign-in work without a workspace prompt; a real service restart preserves the endpoint and credential usability.

Authenticated CLI/HTTP and app-cookie checks preserve the app URL across publication and both sharing scopes. Directory and gateway access follow workspace membership and sharing. The operator cannot publish without a creator grant or access another creator's private content; a platform-only role cannot manage admission. An inactive membership denies retained credentials and app sessions. Second-workspace creation routes remain unavailable. Invalid operator or app ownership fails visibly, rolls back and permits repair/retry.

The real Docker/PostgreSQL test writes an app row before serializing running control state into the frozen legacy schema. The service migrates and restarts at the same endpoint; the saved CLI credential remains usable and reports the first workspace. The row, app URL and workspace-wide sharing survive migration and subsequent CLI redeployment. PostgreSQL provisioning and runtime persistence use the existing production implementations with local infrastructure adapters.

## Verification

The pinned project and starter dependencies were installed into `/tmp/small-cloud-19-venv`. Commands from the repository root:

```bash
npx --yes pyright@1.1.413 --pythonpath /tmp/small-cloud-19-venv/bin/python3
/tmp/small-cloud-19-venv/bin/python3 -m unittest discover -s identity/tests -p 'test_*.py' -q
/tmp/small-cloud-19-venv/bin/python3 -m unittest discover -s infra/tests -p 'test_*_cli.py' -q
/tmp/small-cloud-19-venv/bin/python3 -m unittest discover -s probes/hosting/fixture -p 'test_*.py' -q
```

Typechecking passed with zero errors. All 46 identity, 81 infrastructure and four hosting-fixture tests passed (131 total). `git diff --check` passed. Independent Standards and Spec reviews against starting commit `27c98a8` reported zero findings on both axes.

## Limits

Google is replaced by a signed-token provider fixture and Docker supplies disposable local PostgreSQL. This change has not been deployed to the hosted installation and establishes no new live infrastructure or residency evidence. The implementation supports only the initial workspace; creation and selection of a second workspace and the other management workflows remain later tickets. Disposable-data guarantees are unchanged.
