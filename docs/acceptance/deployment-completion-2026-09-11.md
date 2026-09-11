# Deployment completion acceptance — 2026-09-11

Feature acceptance is complete for [#34](https://github.com/monkeysees/small-cloud/issues/34), from specification #29. Deployment now waits for readiness by default. `--no-wait` explicitly returns acceptance, and the obsolete deploy `--wait` flag is removed. Local CLI/HTTPS/PostgreSQL acceptance was followed by Linux x86-64 standalone verification and five hosted deployments using implementation commit `a47bf5c`. [Redacted evidence](../evidence/deployment-completion-2026-09-11.json) records the hosted results and cleanup. Publishing a new native CLI release remains a separate shipping step.

## Completion and recovery

Human success names the ready app and URL. JSON success distinguishes `state: succeeded, ready: true` from immediate `state: accepted, ready: false`. Progress remains on stderr, with one final JSON envelope on stdout. The reusable observation module preserves request, operation and resolved workspace identity and never resubmits mutations.

An unavailable worker leaves accepted work pending. Identity-service outages retry operation reads within the original deadline, with recurring elapsed progress. Slow response bytes cannot extend that deadline. Timeout and Ctrl-C return exact inspection commands and continuing-work context; a lost or interrupted acceptance response instead reports an unknown outcome and request-based inspection. The command retains the original workspace after the saved default changes. Authentication loss stops observation with its original error and leaves accepted work intact.

Executable/HTTPS regressions cover ready results, first-deploy build/startup/capacity failures, immediate return, replay and changed-source conflicts, worker unavailability, identity restart and sustained outage, authentication loss, timeout, invalid wait options, SIGINT during observation and a blocked initial progress write, lost acceptance responses, and a slowly delivered successful operation response. Subsequent inspection and worker execution verify that stopped observation neither cancels nor duplicates the accepted operation.

## Redeployment and documentation

The existing PostgreSQL and authenticated app-gateway journeys now invoke default-wait deployment. They verify unchanged URLs, retained rows and both sharing scopes across successful updates; old-release availability and data after build/startup failures; and a candidate that commits an incompatible schema migration before failing. The last case still needs creator-owned compatible schema repair: retaining a container does not roll back its database.

Bundled publishing guidance, deploy help/catalog, publishing and redeployment runbooks, the database starter, CLI contracts and changelog describe the delivered behavior. Installed-wheel checks outside the checkout passed for the included completion module, deploy help/catalog, bundled publishing guide and dry-run source manifest.

## Verification results

The full suite passed **230 tests**: 137 identity/CLI/HTTP/database tests, 89 infrastructure CLI tests and four hosting-fixture tests. Pyright 1.1.413 reported zero errors or warnings. The sustained-outage regression also passed after increasing its timing margin, and the focused slow-response/blocked-progress regressions and three PostgreSQL redeployment journeys passed before the full run.

Repeat with the repository's pinned dependencies and local Docker available:

```bash
python3 -m unittest discover -s identity/tests -p 'test_*.py'
python3 -m unittest discover -s infra/tests -p 'test_*_cli.py'
python3 -m unittest discover -s probes/hosting/fixture -p 'test_*.py'
npx --yes pyright@1.1.413 --pythonpath "$(command -v python3)"
```

## Standalone and hosted follow-up

The user delegated completion of acceptance. A locally built Linux x86-64 executable passed all 11 completion tests through the separate frozen HTTPS fixture. The native release verifier now includes that suite for every supported target; its complete Linux run passed **21 tests** plus 14 installed-command checks, installer-integrity checks and public HTTPS verification without system CA paths. Typechecking the verifier passed. Other native targets and a new public installer release have not been exercised in this follow-up; public downloads remain v0.4.0.

Using the retained hosted credential, the standalone executable published only the temporary `completion-acceptance-34` app, with Python and Docker absent from its PATH. First deployment returned readable `Ready` output and a working protected URL. Unauthenticated JSON access correctly returned `401 AUTH_REQUIRED`; an initial harness assertion expecting 404 was corrected without changing the product or repeating the first deployment.

Three successful deployments verified creator-only and workspace-wide updates while retaining the URL, description and PostgreSQL row. Repeated authenticated probes reached the serving release during updates. On the shared update, immediate return reported acceptance without readiness; a one-second timeout and SIGINT returned the same request/operation identity and exact workspace-pinned inspection commands. Resuming default observation completed that same deployment, with no duplicate operation or build. Deliberate Dockerfile and startup failures returned `BUILD_FAILED` and `STARTUP_FAILED`; the latter exercised the hosted 120-second readiness window. Both retained the prior active deployment, HTTP release marker and saved row. Schema incompatibility/repair remains covered by the real local PostgreSQL suite above.

Worker unavailability, identity restart, prolonged outage and slow-response faults passed through the frozen HTTPS fixtures. Hosted services required no restart or upgrade for this CLI change. All five fresh EU builders were deleted, with **101 charged build seconds** retained in the allowance ledger. The temporary app, container, database/role, encrypted database credentials, source staging, diagnostics and request/session records were removed; release/image references were retired for the existing janitors. Its authenticated URL now returns 404.

Final provider inventory contains only the two permanent hosts. Both original apps (`fieldnotes` and `publishing-probe`) retain their recorded metadata, deployment IDs and sharing scopes. The saved credential file and workspace default are unchanged. Usage returned to two deployed apps and zero active apps, with zero reserved build seconds and 993 charged seconds in the selected workspace. All required hosted services are ready and maintenance is off. No human browser or manual acceptance step remains for #34; pushing the commits and publishing a new CLI release remain pending.

## Review

**Standards:** no remaining production findings. Sustained-outage progress is covered, and the outage test includes timing margin for a successful first read before disconnection.

**Spec:** no remaining findings. The interruption and elapsed-deadline edge cases identified in review have executable/HTTPS regressions and passed rechecks.

Both axes also reviewed the native-verifier integration and found no issues.
