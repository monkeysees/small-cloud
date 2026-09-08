# Hosting validation outcome

2026-09-07 — [issue #2](https://github.com/monkeysees/small-cloud/issues/2).

**Hetzner setup is authorized; deployment acceptance remains unverified.** The operator's decision in [#17](https://github.com/monkeysees/small-cloud/issues/17) supersedes this report's original selection hold. The approved [builder provisioning policy](hosting-research.md#approved-implementation-direction--2026-09-08) uses fresh CX23 VMs with CPX22 fallback across the EU, initially without a prewarmed pool. The operator expanded builder placement beyond Germany on 2026-09-08. Implementation may proceed, but creator workloads must not be admitted on the strength of this report.

## Permanent CPX deployment — 2026-09-08

The operator cancelled the CX watcher and approved the higher-cost permanent CPX32/CPX42 pair, with optimization deferred. Both hosts are running in Nuremberg, with no temporary-expiry labels. Initial configuration succeeded, PostgreSQL/registry/Caddy and Docker/gVisor health checks passed, and public HTTPS presents verified TLS with the intentional HTTP 503. SMTP configuration and hourly monitoring are enabled on both hosts. [Permanent deployment evidence](evidence/permanent-foundation-2026-09-08.json) records the new inventory and checks.

The fixed host-plus-IPv4 quote is EUR 105.98/month net before builders and other usage. This higher baseline is explicitly accepted; the earlier USD 100 target is not currently met. Actual invoices, five-builder quota/capacity, full isolation acceptance, certificate renewal/reboot and independent host-loss observation remain outstanding. Earlier empty-inventory statements below describe the completed temporary session, not the current deployment.

## Infrastructure validation — 2026-09-08

Temporary CPX32 control and CPX42 runtime hosts were provisioned in Nuremberg with explicit operator authorization for a maximum two-hour validation session. Permanent CX33/CX43 capacity was unavailable in Germany. An independent workstation timer enforces the temporary expiry; the final resource disposition is retained in [deployment evidence](evidence/hosting-2026-09-08.json). This temporary pair is not the approved permanent cost model.

Validation ended at **02:40 UTC on 2026-09-08**. All 11 builders, both foundation VMs, all primary IPs and the owned network/firewalls/SSH key were deleted. The temporary platform A record was removed and the unrelated Cloudflare wildcard preserved. Final account inventory was empty; the independent cleanup timer was stopped after verification. The foundation is reproducible code, not a currently running deployment.

Observed lifetimes and account list prices give a temporary compute-plus-IPv4 estimate of **EUR 0.4454–0.4678 net**, excluding any extra traffic, tax or service charges. One early builder type was not retained and is bounded by the approved CX23/CPX22 prices. This is not an invoice. Permanent deployment still needs available CX33/CX43 capacity in Germany and enough account quota for the builder fleet.

Version-controlled [operator automation](../infra/README.md) now provisions the private network and firewalls, configures PostgreSQL 16, loopback registry, persistent control directories, encrypted per-tool credentials, closed Caddy gateway, gVisor runtime and disposable EU builders. Initial deployment and reapplication succeeded. A database row survived reconfiguration. Public HTTPS presented a valid certificate and returned the intended 503; actual certificate renewal has not yet been exercised.

The deployment exposed and corrected real compatibility failures: Docker 29's storage-driver configuration, cgroup visibility when entering a builder network namespace, recycled builder IPs with SSH host-key pinning, Docker network IPAM response shape, and preservation of an application's entrypoint while adding its database CA. A representative Python Dockerfile then built successfully on a fresh CX23 in Falkenstein; its VM and address were confirmed deleted. Thirty separate database/role allocations were created on the control host. Actual runtime, capacity and cleanup observations are recorded in the linked evidence; code-level tests alone do not establish live acceptance.

| Check | Result | Evidence and limitation |
| --- | --- | --- |
| Provisioning, private networking, DNS and reapplication | Live pass | Temporary Nuremberg CPX pair; explicit Cloudflare A record, unrelated wildcard preserved |
| Persistent control data | Live pass | Administrative probe row survived full configuration reapplication; host deletion still destroys data |
| Public TLS and closed gateway | Live pass | Valid certificate, HTTP 503; renewal configured, execution untested |
| Database role provisioning | Live pass | 30 distinct databases/credentials with no elevated flags or role memberships; all six allocations wrote/read their own database over verified TLS and were denied other/maintenance databases |
| Build execution | Live pass for representative fixture | Fresh EU CX23, bounded image transfer, direct network and redirect-to-private denial; complete adversarial matrix remains required |
| Builder timeout and teardown | Live pass | Watchdog fired after 600.006 seconds; cgroup had zero tasks and the long-running process was absent. All 11 builders and addresses deleted across success, failed Dockerfile, SIGTERM cancellation, independent expiry and timeout cases |
| Runtime sandbox and egress | Live pass for retained cases | gVisor release-20260831.0, Docker 29.1.3, UID 65532; public HTTPS plus metadata/private/management/peer/host-local denial, DNS-resolved management denial, private CONNECT proxy denial and redirect-to-private denial with healthy controls |
| Runtime resource limits | Live pass with competing-limit caveat | Host CPU measurement ~5.27 CPU seconds over ~10.6 wall seconds; 126 guest threads then refusal at 128 total tasks; candidate memory/disk/fork pressure killed the candidate while five serving tools stayed healthy; 1 GiB tmpfs is constrained first by 512 MiB memory |
| Five active tools and update headroom | Live pass for operator harness | Five busy CPU fixtures remained ready while a candidate started in 2.849 seconds; sixth independent tool refused; no product promotion/routing workflow claimed |
| Complete adversarial coverage | Incomplete | DNS rebinding and controlled public-endpoint nonce/log correlation untested; IPv6 disabled in host/Docker policy but independent healthy IPv6 endpoint control unavailable; complete build proxy/exhaustion matrix remains outstanding |
| Five simultaneous builds | Blocked by account quota | Controlled retry retained Hetzner HTTP 403 `resource_limit_exceeded` when another builder existed; no five-way overlap or live sixth-request refusal is claimed |
| Thirty deployed tools | Partial | 30 databases are allocated; 30 stored release/image records and product lifecycle are not demonstrated |
| EU residency | Resource placement observed | Source, images, database, encrypted credentials and logs on German hosts; builders restricted to supported EU locations; full telemetry/replication review still required |
| Health monitoring | Live collection pass | Service, disk and TLS checks; external host-loss observer remains absent |
| Spending estimate and delivery | Partial | Current EUR prices and rounding sensitivity documented; actual billing/FX ingestion remains pending; Resend workstation test delivered and operator-confirmed on 2026-09-08, deployed spending alerts untested |
| Two-week timebox | Not established | Initial foundation validation does not prove end-to-end pilot delivery or adoption |

The retained runtime settings are 0.5 CPU, 512 MiB memory without swap, 128 guest tasks and a 1 GiB `/tmp` ceiling. Tmpfs pages consume the same memory budget, so the observed memory limit takes effect before a tool can fill that disk ceiling. Builder configuration uses two CPUs, 3,500 MiB without swap, 512 host tasks, a 10 GiB filesystem and a ten-minute watchdog. The memory setting preserves host headroom on the approved 4 GiB builder; full build exhaustion still needs separate validation.

Detailed [builder evidence](evidence/builders-2026-09-08.json) records provisioning failures, cleanup, the repeated watchdog observation and list-price cost bounds. The first timeout run deleted its VM but lost the observation; the repeat retained the exact timing and empty cgroup before deletion.

Detailed [runtime evidence](evidence/runtime-2026-09-08.json) records positive controls, pressure observations and probe cleanup. [Control evidence](evidence/control-2026-09-08.json) records role properties, storage paths, registry binding and observed absence of snapshots/replication. Neither report claims a full provider telemetry audit.

Creator admission stays closed. The provider quota needs increasing before five-build capacity can be retested. Missing or inconclusive mandatory isolation checks, capacity results and delivered spending notifications keep #17 open. Product authentication and routing remain in their separate implementation tickets.

The existing probe was also rerun on 2026-09-08 with `PROBE_POSTGRES_IMAGE=postgres:16`, matching the control bootstrap's engine major. Both own-database initialization/write/read checks and all six cross-tool/maintenance denials passed. The resolved image was `postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94`; its disposable container was removed by the probe's exit trap. This checks the existing SQL privilege fixture locally, not the new provisioner, deployed TLS, persistence or runtime network policy.

The earlier PostgreSQL 18 local probe output was:

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

## Implementation review

The implementation was reviewed against issue #17 and baseline `105516ec8eaffbec00a9c83faabf026a7f1c984f`, including all new files. The baseline is the implementation starting point.

### Standards

No blocking static findings remained after the final review. Corrections include bounded subprocess output/deadlines, shared address deletion, continued reconciliation after malformed journals or local failures, and cleanup that still makes progress with more than 256 staged jobs. Regression tests exercise real subprocesses, tar archives and the provider boundary. Final verification passed 59 infrastructure CLI tests, three network-fixture tests, eight local PostgreSQL 16 privilege checks, Pyright 1.1.413, shell syntax and whitespace checks.

### Spec

The runtime image-inventory admission/cleanup defect was fixed and re-reviewed. A single fixed, validated, read-only public resolver file is the documented gVisor DNS exception; no host directory or credentials are exposed. The remaining acceptance gaps are explicit: account quota and billing evidence, complete adversarial isolation, stored-release capacity, renewal execution and integrated product handoffs. Static review does not turn these missing live results into passes.

## Gate to admit creator workloads

Use the retained [acceptance procedures](../probes/hosting/README.md) in the operator's identified EU test environment. Obtain an available-host quote, run the build and runtime matrices independently, export redacted residency configuration, demonstrate resource/update behavior, and deliver an alert notification. Attach observed results, immutable versions, charges and teardown confirmation here. Any failed or inconclusive mandatory boundary keeps the gate closed; do not substitute low-permission metadata access for metadata denial.
