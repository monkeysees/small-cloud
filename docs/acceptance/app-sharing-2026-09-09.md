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

## Hosted deployment — 2026-09-09

Commit `641621e` was pushed and installed on the existing German control host. The management proxy now routes `/api/directory`. Caddy validation passed; identity, publishing and Caddy services are active. Deployed CLI, HTTP adapter and publishing source hashes match the commit. The workstation CLI was updated while retaining its existing operator credential.

[Deployed evidence](../evidence/app-sharing-2026-09-09.json) records authenticated CLI directory results, both sharing directions on the disposable `publishing-probe`, and owner HTTP 200 before and while shared. Unauthenticated directory and app requests return 401. The probe was restored to creator-only with the same active deployment; no runtime rebuild or data mutation was needed.

During guided live acceptance, the operator reported that `islambegkatibov@gmail.com` (an admitted non-administrator creator) received `NOT_FOUND` while the probe was creator-only, loaded the fixture with their own stable identity after workspace-wide sharing, and received `NOT_FOUND` again on refreshing the same browser session after returning to creator-only. These observations establish live other-creator content access and existing-session revocation. The probe remains creator-only.

After updating the Mac CLI from the local repository, the operator confirmed Islambeg’s CLI identity and member/creator roles. His directory returned no apps while the probe was private, then returned its name, description, creator and URL while shared. Attempts to share the private probe and unshare the shared probe both returned `NOT_FOUND`. The probe was restored to creator-only after these checks.

Islambeg published the database-backed `sharing-acceptance-7` from the updated Mac CLI (deployment `d-3ba4a171d346430cad297322`). The initial packaging failure came from running outside the repository; retrying from its root succeeded. Using the existing administrator credential, automated live requests confirmed the private app was absent from the administrator’s directory and returned `NOT_FOUND` at both `/` and `/data`, while authorized diagnostic status remained available.

The operator confirmed that Islambeg saved `Owner acceptance entry` and could still see it after refreshing. At the operator’s request, `ishanmoscow43@gmail.com` was admitted with membership only (`creator:false`, `administrator:false`). The operator then confirmed this ordinary member received `NOT_FOUND` while the app was private; after Islambeg shared it, the member could enter, read the owner’s data, add an entry and see the entries. Returning to creator-only denied the member’s existing browser session on refresh while both entries remained visible to the owner.

The pending live checks listed for this increment are complete. Final authenticated status checks confirm both `publishing-probe` and `sharing-acceptance-7` are running and creator-only. The data-backed acceptance app and ordinary-member admission are retained; no cleanup or membership removal was performed.

## Limits

These are local CLI/HTTPS/PostgreSQL results. Google is replaced by a signed-token provider fixture and Docker supplies disposable PostgreSQL; the production identity, publishing and gateway implementations run locally. The hosted deployment and operator smoke results are recorded above; the guided Google-account observations are explicitly identified above. No new EU infrastructure isolation claim is made. Creator-configured secrets and their acknowledgement remain #12; this change does not introduce secret management. Streaming and WebSocket support remain unavailable.
