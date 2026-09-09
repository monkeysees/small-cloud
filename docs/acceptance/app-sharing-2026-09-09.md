# App sharing acceptance — 2026-09-09

Local implementation acceptance for [#7](https://github.com/monkeysees/small-cloud/issues/7), following [specification #1](https://github.com/monkeysees/small-cloud/issues/1) and [ADR 0002](../adr/0002-pilot-sharing-boundary.md). Repeatable usage and installation instructions are in [sharing and discovery](../../identity/SHARING.md).

## Observed results

The real CLI switches from the creator-only default to workspace-wide and back. Same-request retries return the original receipt without restoring a superseded scope; changed inputs conflict. Unsupported scopes and unknown fields leave the scope unchanged.

Authenticated HTTPS checks cover creator, ordinary member, other creator and administrator. Directory results contain only accessible app names, descriptions, creator IDs/display names and URLs. Administrators and other creators cannot change another creator's sharing or discover its private app. Gateway checks cover assets, reads, writes and attempted upgrades: unauthorized requests return 404 before runtime-readiness checks; authorized requests to a pending app return 503. Unauthenticated HTTP requests receive 401, and the signed Google fixture's unadmitted user receives 403 at sign-in.

The running PostgreSQL starter verifies that a member can read an owner's existing entry and contribute to the same dataset after sharing. Returning to creator-only blocks that member's subsequent reads and writes while preserving both entries for the owner. A real app OAuth handoff establishes a member browser session: the same cookie reads successfully while shared and receives 404 after returning to creator-only.

## Verification

Executed from the repository root with the pinned project and starter dependencies in `/tmp/small-cloud-sharing-venv`:

```bash
npx --yes pyright@1.1.413 --pythonpath /tmp/small-cloud-sharing-venv/bin/python
/tmp/small-cloud-sharing-venv/bin/python -m unittest discover -s identity/tests -p 'test_*.py' -q
/tmp/small-cloud-sharing-venv/bin/python -m unittest discover -s infra/tests -p 'test_*_cli.py' -q
/tmp/small-cloud-sharing-venv/bin/python -m unittest discover -s probes/hosting/fixture -p 'test_*.py' -q
```

Typechecking passed with zero errors. All 40 identity, 81 infrastructure and four hosting-fixture tests passed (125 total). The expanded existing-browser-session check was added during review and then passed in a targeted rerun of `identity.tests.test_database_http.DatabaseAcceptance.test_shared_members_read_and_modify_the_same_app_database`. `git diff --check` passed.

Independent standards/specification review found no blocking implementation mismatch. The standards review noted optional duplication in request-receipt handling, consistent with existing mutation code. The specification review's browser-session evidence gap was addressed by the additional regression above.

## Limits

These are local CLI/HTTPS/PostgreSQL results. Google is replaced by a signed-token provider fixture and Docker supplies disposable PostgreSQL; the production identity, publishing and gateway implementations run locally. No production deployment, live Google sharing check or new EU infrastructure isolation claim is recorded here. Install the service package and updated Caddy directory route before using these commands on the hosted pilot. Creator-configured secrets and their acknowledgement remain #12; this change does not introduce secret management. Streaming and WebSocket support remain unavailable.
