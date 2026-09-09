# CLI discovery acceptance — 2026-09-09

Acceptance for [#30](https://github.com/monkeysees/small-cloud/issues/30), the discovery and app-inspection slice of [#29](https://github.com/monkeysees/small-cloud/issues/29). The tested implementation is commit `437714e`. [Machine-readable evidence](../evidence/cli-discovery-2026-09-09.json) records 68 successful installed-executable checks and redacted hosted observations.

## Installed executable and offline discovery

Built the Python wheel from the committed source and installed it into `/tmp/small-cloud-30-final-installed` using the existing project dependency environment. Invoked its generated `bin/small-cloud` entry point from `/tmp`, with `PYTHONPATH` selecting the installed package. This exercised the installed package outside the checkout; it does not establish standalone binary distribution acceptance.

With a temporary empty home/state/config directory and an invalid endpoint, bare invocation, root/group/leaf help, all 18 scoped command-catalog queries, app-group querying and all four bundled guides succeeded. Help displayed complete examples, JSON guidance and guide links. Help took precedence over missing required input. Catalog version 1 included only delivered commands; unknown scopes, missing required inputs and all eight superseded top-level paths returned versioned usage errors without prompting.

## Hosted inspection

The installed executable used the retained workstation credential against `https://small-cloud.monkeysees.one`. Authentication status succeeded without a new browser approval. Human and JSON app lists agreed on the accessible app's name, description and URL. Both app-status formats agreed with that directory entry, and the latest operation was inspectable by its returned ID. JSON reads preserved schema version 1 and null request identity.

The accessible `publishing-probe` app reported `stopped`; these management reads did not start it. An intentionally nonexistent app returned `NOT_FOUND` and exit 4 in both modes. The human error used stderr and pointed to `small-cloud app list`; JSON returned one error envelope on stdout. No hosted build, source upload, sharing change, secret change, credential revocation, app request or server deployment was performed.

## Automated verification

All 85 identity tests passed together on the final implementation in 311.959 seconds, with no failures or skips. Its subprocess/HTTPS fixtures cover successful app inspection, an empty accessible directory, denial to a different member, terminal-control escaping, request identity, help precedence, scoped catalogs, guide syntax and prompt-free missing-input errors. The same suite also exercises the renamed commands through real local Docker/PostgreSQL publication, redeployment, migration, runtime-secret and sharing journeys.

```bash
/tmp/small-cloud-19-venv/bin/python -m unittest discover -s identity/tests -p 'test_*.py'
```

The implementation run also passed all 89 infrastructure tests, four hosting-fixture tests and typechecking. Independent Standards and Spec reviews reported zero remaining findings after correcting catalog accounting fields, readiness guidance and the documented operation kind. The operation wire kind remains `deploy`.

## Boundaries

Hosted inspection used the existing administrator; cross-role authorization denial was verified through the isolated authenticated HTTPS fixtures. Google is replaced only in those fixtures by the existing signed-token provider, and Docker supplies disposable local PostgreSQL. No new interactive Google approval, unfamiliar-agent trial or human walkthrough is claimed.

Acceptance for #30's delivered discovery/inspection slice is complete. Standalone releases, split login, project linking, default completion waits, live logs and additional workspace workflows remain later implementation tickets; the complete fresh-agent/human journey acceptance remains #45. No new infrastructure isolation, residency or durability claim follows from this report.
