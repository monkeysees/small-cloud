# Hosting validation outcome

2026-09-07 — [issue #2](https://github.com/monkeysees/small-cloud/issues/2).

**Infrastructure selection remains blocked.** No candidate has sufficient evidence to meet the accepted contract. The [provider assessment and cost model](hosting-research.md) identify a VM sandbox candidate for a bounded EU trial, but do not establish its feasibility. This is an explicit no-go under currently available evidence, not proof that every possible provider is infeasible. Do not begin production infrastructure implementation or mark deployment acceptance checks passed on the strength of this report.

## Evidence obtained

| Check | Result | Evidence and limitation |
| --- | --- | --- |
| Provider/orchestration/build evaluation | Assessed, not selected | First-party sources and cost assumptions in hosting research; managed metadata boundary unresolved |
| Database engine and scoped role pattern | Local pass | PostgreSQL 18, real TCP authentication; each role initializes/writes/reads own database and receives permission denial for other tool, `postgres` and `template1` databases |
| Build isolation | Not run in candidate environment | No EU build environment identified; retained separate Dockerfile execution procedure |
| Runtime isolation and public/database exceptions | Not run in candidate environment | Local database result is not network or sandbox evidence |
| EU content storage and execution | Not verified | Proposed placement only; no deployed resource inventory |
| Five active tools, five concurrent builds, 30 deployed tools, updates | Estimated, not demonstrated | Resource envelope includes replacement headroom; concurrency and update semantics still need measurement |
| Full monthly cost and operations | Estimated | Published compute rates plus explicit allowances, storage/traffic assumptions, tax sensitivity and labor; available VM quote still required |
| Two-week timebox | Not established | 9–14 engineering days estimated before adoption observation |
| Budget conflict | Resolved | ADR 0001 and specification now consistently use $100/month spending target excluding labor, with alerts, not guaranteed cap |
| Spending alert delivery | Not run | Thresholds and delivered-notification check retained in probe procedure |

The local database probe ran successfully with:

```text
bash probes/hosting/database.sh
PASS: probe_a can initialize, write and read its database
PASS: probe_a denied connection to probe_b
PASS: probe_a denied connection to postgres
PASS: probe_a denied connection to template1
PASS: probe_b can initialize, write and read its database
PASS: probe_b denied connection to probe_a
PASS: probe_b denied connection to postgres
PASS: probe_b denied connection to template1
Image: postgres@sha256:4ef4dbc939d61acea57712655ddb4b4ab27419c913f94cca0cd57cb3ea3c2280
```

The probe used an ephemeral local Docker container with no published ports and no external network, and removed it on exit. Its credentials are public disposable fixtures, not platform secrets. Reproduce the exact engine with:

```bash
PROBE_POSTGRES_IMAGE='postgres@sha256:4ef4dbc939d61acea57712655ddb4b4ab27419c913f94cca0cd57cb3ea3c2280' bash probes/hosting/database.sh
```

## Gate to reopen selection

Use the retained [acceptance procedures](../probes/hosting/README.md) in the operator's identified EU test environment. Obtain an available-host quote, run the build and runtime matrices independently, export redacted residency configuration, demonstrate resource/update behavior, and deliver an alert notification. Attach observed results, immutable versions, charges and teardown confirmation here. Any failed or inconclusive mandatory boundary keeps the gate closed; do not substitute low-permission metadata access for metadata denial.
