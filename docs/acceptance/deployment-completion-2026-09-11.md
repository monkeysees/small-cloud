# Deployment completion acceptance — 2026-09-11

Local implementation and acceptance for [#34](https://github.com/monkeysees/small-cloud/issues/34), from specification #29. Deployment now waits for readiness by default. `--no-wait` explicitly returns acceptance, and the obsolete deploy `--wait` flag is removed. This report covers the CLI, authenticated HTTPS service fixtures and real local PostgreSQL/app gateway journeys. It does not claim a hosted deployment or a published native release.

## Completion and recovery

Human success names the ready app and URL. JSON success distinguishes `state: succeeded, ready: true` from immediate `state: accepted, ready: false`. Progress remains on stderr, with one final JSON envelope on stdout. The reusable observation module preserves request, operation and resolved workspace identity and never resubmits mutations.

An unavailable worker leaves accepted work pending. Identity-service outages retry operation reads within the original deadline, with recurring elapsed progress. Slow response bytes cannot extend that deadline. Timeout and Ctrl-C return exact inspection commands and continuing-work context; a lost or interrupted acceptance response instead reports an unknown outcome and request-based inspection. The command retains the original workspace after the saved default changes. Authentication loss stops observation with its original error and leaves accepted work intact.

Executable/HTTPS regressions cover ready results, first-deploy build/startup/capacity failures, immediate return, replay and changed-source conflicts, worker unavailability, identity restart and sustained outage, authentication loss, timeout, invalid wait options, SIGINT during observation and a blocked initial progress write, lost acceptance responses, and a slowly delivered successful operation response. Subsequent inspection and worker execution verify that stopped observation neither cancels nor duplicates the accepted operation.

## Redeployment and documentation

The existing PostgreSQL and authenticated app-gateway journeys now invoke default-wait deployment. They verify unchanged URLs, retained rows and both sharing scopes across successful updates; old-release availability and data after build/startup failures; and a candidate that commits an incompatible schema migration before failing. The last case still needs creator-owned compatible schema repair: retaining a container does not roll back its database.

Bundled publishing guidance, deploy help/catalog, publishing and redeployment runbooks, the database starter, CLI contracts and changelog describe the delivered behavior. Installed-wheel checks outside the checkout passed for the included completion module, deploy help/catalog, bundled publishing guide and dry-run source manifest. No native binary release or hosted mutation was performed.

## Verification results

The full suite passed **230 tests**: 137 identity/CLI/HTTP/database tests, 89 infrastructure CLI tests and four hosting-fixture tests. Pyright 1.1.413 reported zero errors or warnings. The sustained-outage regression also passed after increasing its timing margin, and the focused slow-response/blocked-progress regressions and three PostgreSQL redeployment journeys passed before the full run.

Repeat with the repository's pinned dependencies and local Docker available:

```bash
python3 -m unittest discover -s identity/tests -p 'test_*.py'
python3 -m unittest discover -s infra/tests -p 'test_*_cli.py'
python3 -m unittest discover -s probes/hosting/fixture -p 'test_*.py'
npx --yes pyright@1.1.413 --pythonpath "$(command -v python3)"
```

## Review

**Standards:** no remaining production findings. Sustained-outage progress is covered, and the outage test includes timing margin for a successful first read before disconnection.

**Spec:** no remaining findings. The interruption and elapsed-deadline edge cases identified in review have executable/HTTPS regressions and passed rechecks.
