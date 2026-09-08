# Hosting acceptance probes

Retained from [issue #2](https://github.com/monkeysees/small-cloud/issues/2) for live acceptance in [#17](https://github.com/monkeysees/small-cloud/issues/17). These checks exercise the infrastructure boundaries in `docs/spec.md`. Hetzner provisioning is authorized; creator admission stays closed until every mandatory deployment check passes. A local pass is not deployment evidence. See [current results](../../docs/hosting-validation.md).

## Database probe

Run `bash probes/hosting/database.sh` with Docker available. It creates and removes its own network-disconnected PostgreSQL container, publishes no ports and uses disposable fixture passwords. It verifies schema initialization, write/read access and explicit cross-database connection denial in both directions, including the maintenance databases. Set `PROBE_POSTGRES_IMAGE` to the recorded digest to repeat against exactly the same image. It does not test deployed credentials, TLS, network policy or persistence.

The #17 control bootstrap uses PostgreSQL 16; the earlier PostgreSQL 18 fixture remains historical privilege-pattern evidence. Database owners remain administrative: app roles own their schema objects, but cannot grant themselves access to another database. New databases must revoke PUBLIC connection privileges before app credentials are distributed. Audit all databases and role memberships, including template and maintenance databases. Managed PostgreSQL must expose enough privilege control to reproduce this result. PostgreSQL documents [connection privileges and authentication rules](https://www.postgresql.org/docs/current/auth-pg-hba-conf.html).

## Separate build and runtime runs

Run the following matrix twice in the candidate EU environment: first inside an actual uploaded Dockerfile `RUN` instruction, then inside an unprivileged deployed app. A shell on the worker host or a separate diagnostic container does not substitute for either. Build containers receive no runtime database credentials or runtime secrets; they must deny the database endpoint entirely. Runtime receives only its own scoped database credentials.

Before each run, record UTC time, account/project alias, region, immutable image digest, build/runtime ID, sandbox version, resource settings and network-policy revision. Record exit codes and response status only; never retain metadata bodies, tokens, connection URLs or secret values. Use dedicated test endpoints and disposable credentials.

| Destination or boundary | Expected result | Evidence required |
| --- | --- | --- |
| Controlled public HTTPS endpoint | Success in build and runtime | Matching request nonce in endpoint logs; DNS and TLS succeed |
| Cloud metadata, all provider IPv4/IPv6 addresses and advertised metadata URI | No connection in both | Probe link-local endpoints and provider-specific task metadata, with and without proxy settings |
| Private-network canary | No connection in both | Known listening endpoints in each attached private subnet; verify healthy from a trusted control before and after |
| Platform API, worker management, Docker socket, orchestration API, secret store | No connection/access in both | Include public management addresses, internal DNS names, host gateway and mounted sockets |
| Scoped database endpoint | Runtime succeeds; build denied | Runtime initializes/writes/reads through scoped credentials; build TCP cannot connect |
| Other database on shared endpoint | Runtime connection denied | Same valid own credentials with only database name changed; require explicit authorization denial, not timeout |
| Another app's listener/files/secrets | No access in both | Controlled canaries; verify no host directories/private files, privileged execution or shared build daemon; the runtime’s fixed read-only public resolver file is the documented exception |

For each HTTP destination, repeat with direct IP and hostname, proxy bypass and normal proxy settings; test IPv4 and IPv6 (or prove IPv6 disabled). Include DNS resolving to private addresses, public-to-private redirects and DNS rebinding. Public internet permission cannot allow a path back into platform management. A 401/403/404 from a forbidden endpoint proves reachability and **fails** the network boundary. A refused connection to an absent service is inconclusive; use a known-live control and inspect enforced policy.

A bounded HTTP attempt, inside the actual build/app, is:

```bash
curl --noproxy '*' --connect-timeout 3 --max-time 5 \
  --output /dev/null --silent --write-out '%{http_code}\n' "$PROBE_URL"
```

Set `PROBE_URL` to each approved non-secret target; record the exit status. This command alone cannot establish denial: correlate with canary health and policy evidence. For non-HTTP listeners use an equivalent bounded TCP connection probe. Do not classify DNS failure as network isolation.

Repeat the database SQL setup on a disposable candidate database through the administrator channel, then run the same own/cross-database operations through the real app connection. Use a protected libpq password file, never a password in command arguments. Verify both app roles, maintenance databases, role membership and inability to create roles/databases or elevate privileges. A local database pass is only evidence that this privilege pattern works.

## Capacity and update checks

Proposed evaluation limits: runtime 0.5 vCPU, 512 MiB RAM, 1 GiB temporary writable storage and 128 processes per app; build 2 vCPU, 4 GiB RAM, 10 GiB temporary storage and ten-minute deadline. These require enforcement evidence before acceptance. Run CPU, memory, process and disk exhaustion fixtures separately in build and runtime; verify the offender is bounded and a neighboring healthy app still responds. Verify cleanup after timeout and failed builds. Capture watchdog activation and execution timestamps, configured ancestor cgroup limits and final empty/removed cgroup state before deleting the VM. A missing observation after otherwise successful deletion is inconclusive for the measured deadline; retain that distinction. Keep an independent provider expiry during any manual observation.

Keep five apps receiving requests while five creators submit builds concurrently. Record latency, memory, CPU and disk high-water marks. Store 30 deployed images and databases. Start a sixth app and require immediate capacity feedback without eviction. Exercise an update with failed startup while the old version serves; reserve replacement capacity but do not admit a sixth active app. Record how replacement execution respects the five-active-app contract before accepting orchestration. Restart/redeploy an app and verify its committed database row remains.

## Residency, billing and evidence record

Export deployed configuration with values redacted: source bucket region and replication, image registry and cache region, database and volume region, encrypted secret storage and key location, build/runtime execution regions, and log sinks/retention/exports. Include crash reports, provider build logs, staging artifacts and backup defaults. A provider's availability in the EU does not prove these resources reside there. Keep content out of non-EU telemetry and disable cross-region replication/export unless the destination is also EU.

Verify actual and forecast spending alerts to the operator at $50, $80 and $100, including a delivered test notification. These thresholds are proposed settings. Include tax, exchange-rate sensitivity, traffic, update overlap and ongoing maintenance in the estimate; alerts cannot enforce a cap.

Retain a redacted result row per check: `check | build/runtime | expected | observed | pass/fail/inconclusive | artifact | UTC`. Missing runs are **not run**, not pass. Include teardown confirmation and actual probe charges. Re-run after changes to sandbox, networking, database roles or provider configuration.

## Reproducing the completed matrix

The [2026-09-08 report](../../docs/hosting-acceptance-2026-09-08.md) links separate actual Dockerfile and gVisor observations. `adversarial.py --config PATH --phase build|runtime` combines the direct targets in `network.py` with controlled HTTPS nonce correlation, proxy bypass, redirect, filesystem and real DNS-change checks. Its configuration and exact target addresses are retained alongside the synthetic results. Do not reuse dated canary addresses: the temporary VM and DNS records were deleted.

For a new session, obtain a disposable EU builder through the normal controller admission/reaper with an explicit expiry. Before execution, create a root-only canary directory with `dns.json` containing `{"build.rebind.YOUR_DOMAIN":"PUBLIC_CANARY_IPV4","runtime.rebind.YOUR_DOMAIN":"PUBLIC_CANARY_IPV4"}`. `canary.py --public-ip PUBLIC_CANARY_IPV4 --zone rebind.YOUR_DOMAIN --directory PRIVATE_DIRECTORY` serves authoritative UDP DNS and a loopback HTTP nonce sink. Point a dedicated A record at that VM and delegate the isolated rebinding zone to it. Run Caddy in front of loopback port 8081 for valid HTTPS on a dedicated hostname; open only TCP 80/443 and UDP/TCP 53 in a temporary canary firewall. Bound the service lifetime with systemd and the provider expiry; this helper is not a public production DNS service. It stores only bounded synthetic `/issue17-...` nonces, never request bodies or headers.

Run the probe inside an actual Dockerfile `RUN`, then inside an actual runtime candidate. After the initial public nonce arrives, atomically change the relevant build/runtime hostname in the canary's `dns.json` to the live private control address. The guest records the changed `getaddrinfo` result and attempts that exact socket address; a second name lookup could reuse a stale public answer and invalidate the test. Keep trusted before/after health checks for denied listeners. Prove IPv6 disabled in the host and build namespace plus no non-loopback guest address and an unreachable external IPv6 connection; an unavailable IPv6 service is not a positive control. Delete the canary through `builders.py delete`, confirm address removal, and remove only its dedicated DNS/firewall records.

`build_pressure.py cpu|memory|pids|disk` runs only in an actual disposable Dockerfile build. Use a separate builder per mode. `--peer-host` can test another live builder's SSH denial. The host-owned `builder/evidence.py` collects ancestor cgroup peaks/events, filesystem capacity, IPv6 and metadata-listener controls after execution and before deletion; it is never run with Dockerfile authority. An OOM build failure is expected for memory exhaustion. Disk exhaustion is recovered inside the synthetic fixture to permit result export. Retain both failure status and successful teardown; successful deletion alone does not prove resource enforcement.
