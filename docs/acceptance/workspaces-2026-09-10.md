# Multiple workspace acceptance — 2026-09-10

Local implementation acceptance for [#20](https://github.com/monkeysees/small-cloud/issues/20), under specification #18 and ADR 0009. No hosted deployment or release was performed. Deployed multi-workspace isolation and infrastructure verification remain #28.

Follow-up: [hosted acceptance on 2026-09-11](workspaces-hosted-2026-09-11.md) deployed #20 and verified live isolation, preserving the dated local observations below. That report records remaining manual checks and distinguishes later #28 workflows.

## Verified behavior

- Real CLI subprocesses and authenticated HTTPS create a workspace with one pending owner, enforce platform-only creation, retain matching receipts through restart and concurrent retries, and reject changed inputs.
- Signed Google-provider fixtures bind the exact admitted owner email to an immutable identity. Owner/administrator status does not grant creator privileges; the same identity has independent roles across workspaces. Unadmitted same-domain accounts cannot enter through browser sign-in.
- Workspace listing, saved selection and per-command overrides work without initial prompts. Ambiguous names fail; IDs take precedence over names, and inaccessible IDs never fall back to a similarly named accessible workspace. Non-ASCII names work. A removed default remains unusable across restart and fresh sign-in until explicitly reselected.
- The real PostgreSQL fixture publishes the same name in two workspaces, with different immutable app IDs/URLs and separate data. Gateway reads preserve the distinct rows through control-service restart. Foreign operation IDs and conflicting operation/app identifiers fail.
- Changed-workspace deployment, admission and sharing retries cannot replay another workspace's receipt. The CLI pins its resolved target through command execution and polling. Existing initial-workspace receipt serialization is retained as the named persisted-data contract.
- Browser directory results and gateway requests distinguish creator-only and workspace-wide access, including a member admitted only elsewhere and an overlapping member. Explicit gateway workspace/URL mismatches fail. Browser-selected targets survive Google sign-in without changing the saved CLI default. Expired OAuth attempts are pruned before applying the live-attempt cap, including when no CLI login occurs.
- Additional workspaces do not multiply the installation build allowance. Existing creator, deployed-app and active-app safeguards remain installation-wide; usage distinguishes workspace consumption from shared limits.
- Legacy migration, original credentials, app URLs, roles, directory/sharing and PostgreSQL persistence remain covered by the existing acceptance suites.

## Validation

Focused workspace and real PostgreSQL tests passed, including regressions reproduced before the fixes. CLI discovery/help/catalog checks passed. Pyright reported zero errors or warnings using the repository's pinned dependencies. The initial system-Python run used PyJWT 2.6.0 and failed an unchanged sign-in test; validation uses the existing virtual environment with the pinned PyJWT 2.12.1 instead.

The full suite passed: 105 identity/CLI tests, 89 infrastructure tests and four probe tests (198 total). The browser-only OAuth-expiry regression was also rerun after its final cleanup fix and passed. No tests were skipped.

The independent Standards review's ID/name collision finding and optional duplicated receipt-rule finding were resolved and re-reviewed. The Spec review and targeted follow-up found no outstanding requirements or correctness issues. Reviews did not substitute for test execution.

Repeat from a Python environment containing the dependencies in `pyproject.toml` and `identity/fixture/requirements.txt`, with Docker available:

```bash
npx --yes pyright@1.1.413 --pythonpath "$(command -v python3)"
python3 -m unittest discover -s identity/tests -p 'test_*.py'
python3 -m unittest discover -s infra/tests -p 'test_*_cli.py'
python3 -m unittest discover -s probes/hosting/fixture -p 'test_*.py'
```

Google and build/runtime infrastructure are controlled local fixtures; PostgreSQL, the CLI, HTTP service, workspace authorization and gateway run their real implementations. These checks do not establish live cloud isolation, residency, deployment readiness or stronger data durability.
