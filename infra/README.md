# Hetzner operator infrastructure

The permanent CPX32 control and CPX42 runtime foundation for [#17](https://github.com/monkeysees/small-cloud/issues/17) is deployed in Nuremberg. The [infrastructure acceptance report](../docs/hosting-acceptance-2026-09-08.md) records live isolation, capacity, persistence, renewal, retention and alert checks. Creator admission remains closed pending the separate authentication, routing and product lifecycle tickets and final integrated verification #15.

## Prerequisites and scope

The CX watcher was removed at the operator’s request. The approved permanent deployment now uses CPX32 control and CPX42 runtime in Germany; use `apply --cpx` explicitly. Cost optimization back to CX is deferred and requires a migration, not automatic replacement.

Use Python 3.11+, OpenSSH and the documented owner-only [Hetzner/Cloudflare token files](../docs/agents/cloud-access.md). The automation has no Python package dependencies. Hosts use Ubuntu 24.04 amd64 signed distribution packages; capture actual package/kernel versions during deployment. gVisor requires an explicit versioned official artifact URL and verified SHA256, with no `latest` install. See each host directory for reviewed upstream references.

The operator identifies the Hetzner token's project as `small-cloud`; the API does not independently establish the project display name. The permanent CPX32/CPX42 pair stays in Germany (`nbg1`, `fsn1`). Builders may use EU locations, including Helsinki (`hel1`), as authorized by the operator. Inspect live account prices and availability before creating resources:

```bash
python3 infra/cloud.py inventory
python3 infra/cloud.py quote
python3 infra/cloud.py apply --cpx --admin-cidr YOUR_PUBLIC_IPV4/32
```

`apply --cpx` selects CPX32/CPX42; plain `apply` retains the explicit CX33/CX43 selection for future cost optimization. Provisioning fails before creating anything if neither German location reports the selected permanent pair available. It never replaces hosts or silently changes their SKU. Creation capacity is still not guaranteed by the availability indicator. Failures leave owned partial resources visible in inventory; reapply after inspection. Unknown POST outcomes must be reconciled by resource name before any new create. Resource names carry `managed-by=small-cloud,issue=17` ownership labels; unowned name collisions are refused.

Local state is under `~/.local/state/small-cloud/infra` with directory 0700. It contains a dedicated SSH key, resource metadata and known hosts; provider tokens stay in their separate credential files and are never written into cloud-init or Git. Keep state on an encrypted operator disk. SSH pins the first key seen at the API-returned address (`accept-new`) and rejects later changes; first-contact authentication is trust-on-first-use, so verify host fingerprints through a trusted provider console if stronger bootstrap assurance is required. Never delete a changed-key warning without investigating.

For a separately authorized temporary CPX32/CPX42 validation session, install an independent workstation cleanup timer **before** provisioning. From this checkout, the following schedules expiry at 105 minutes, leaving 15 minutes inside the two-hour authorization for retries:

```bash
python3 - <<'PYTHON'
import sys, time
sys.path.insert(0, 'infra')
from cloud import state_directory
expiry = state_directory() / 'validation-expiry'
expiry.write_text(str(int(time.time()) + 105 * 60))
expiry.chmod(0o600)
PYTHON
systemd-run --user --unit=small-cloud-validation-cleanup --on-calendar='*-*-* *:*:00' --timer-property=Persistent=true /usr/bin/python3 "$PWD/infra/validation.py"
systemctl --user is-active small-cloud-validation-cleanup.timer
python3 infra/cloud.py apply --validation --admin-cidr YOUR_PUBLIC_IPV4/32
```

Keep this workstation online and the checkout at that path. The timer deletes only owned validation hosts and their recorded addresses; it continues past individual failures and reports them. Builders inherit the same session expiry. Do not extend expiry to turn a temporary validation pair into permanent infrastructure. End the session early with `python3 infra/validation.py --now`, verify provider inventory and all address deletion journals, then remove the exact owned DNS record and unused network/firewalls/SSH key as described below. Disable the cleanup timer only after billable-resource deletion is confirmed. The local `foundation.json` is historical after teardown; a later apply writes fresh resource IDs.

After successful `apply`, configure hosts and the explicit platform DNS record:

```bash
python3 infra/remote.py configure --runsc-url VERSIONED_OFFICIAL_URL --runsc-sha256 VERIFIED_SHA256
python3 infra/cloud.py dns --control-ipv4 CONTROL_PUBLIC_IPV4
```

The DNS operation touches only its owned `small-cloud.monkeysees.one` A record, with Cloudflare proxying disabled. The existing `*.monkeysees.one` wildcard is preserved. Caddy initially returns 503 and automatically obtains/renews TLS after DNS resolves. Configuration can restart services and always reapplies the closed gateway; do not reapply blindly after #4/#5 install the authenticated gateway. PostgreSQL and registry/source/secret data persist on the control host disk; deleting the host destroys them. There is no backup or recovery guarantee.

`configure` installs the build coordinator and independent one-minute reconciliation timer on the trusted control host. It copies the project-bound Hetzner token and dedicated SSH key there, under root-only directories; neither credential goes to runtime or build VMs. After this handoff, run all builder admission on this single controller so its process lock coordinates the five-build limit. Do not run multiple controllers against the project. Configuration enables hourly staging, registry-release and runtime-image cleanup and health collection without email. Source and image staging become eligible after 23 hours, leaving an hourly sweep before the 24-hour deadline; diagnostics expire after seven days. See [retention rules](artifacts/README.md). The reconciliation timer survives coordinator process failure; during complete control-host loss the runtime observer alerts the operator, who must inspect and remove expired builders using the protected workstation state and provider inventory.

All three host roles disable automatic Apport/whoopsie/core-dump export and replace the kernel core handler. Build execution and runtime containers also have a zero core-file limit. This policy applies before untrusted code runs and survives reboot; do not enable external crash collectors without reviewing their content and EU destination.

## Build and runtime operations

Product terminology uses “app.” The deployed operator interfaces retain `tool`/`tool_id` JSON keys, the `small-cloud.tool` Docker label, the `tool_` database/role prefix, and `small-cloud-tool-database` (from `control/tool_database.py`). These identify existing stored records and installed commands; changing them requires a coordinated migration. Historical JSON evidence retains the identifiers and output actually observed. New product APIs use the app terminology in [the contracts](../docs/contracts.md).

See [builder enforcement](builder/README.md), [runtime enforcement](runtime/README.md), and [database handoff](control/README.md). On the German control host, a bounded uploaded tar can be built with:

```bash
python3 /opt/small-cloud/infra/artifacts.py --stage unique-upload < CONTEXT.tar
python3 /opt/small-cloud/infra/remote.py build --context /srv/small-cloud/source/upload-unique-upload/source.tar --output /srv/small-cloud/source/unique-build-result --job unique-build-id --admin-cidr CONTROL_PUBLIC_IPV4/32
```

The coordinator derives control/runtime public management addresses from its protected installed inventory and fresh provider reads, including another read immediately before execution. It refuses changed resource identities. Runtime policy must be reapplied before any address changes. Each fresh builder uses CX23 across EU locations before CPX22. Known capacity rejections permit the next approved candidate; ambiguous create outcomes stop for reconciliation. The VM gets no private network attachment or reusable credentials. SSH transfers one bounded context and retrieves the bounded image/log/result, outside Dockerfile authority; the trusted controller enforces download bounds while streaming. The entire Docker daemon and build/export execute under a host network namespace and bounded cgroup/filesystem. The ten-minute host watchdog kills the execution cgroup; the coordinator deletes the VM on normal success, failure, timeout and interruption. Thirty-minute provider expiry plus the independent timer covers an abandoned coordinator.

Use `builders.py reconcile` to retry expired VM/address cleanup. Deletion journals retain address IDs across an interrupted deletion. Inspect failures promptly: a stopped VM still bills, and a deleted server does not prove every associated resource was removed. Retained teardown results report estimated rounded hours, not verified invoice charges. The cost estimator retains completed builder deletion records and prices observed resources; it does not ingest invoices or implement the monthly product build-allowance ledger.

A successful build returns an image archive in the EU control directory. Follow the [release and service-identity handoff](artifacts/README.md#release-handoff) to publish, import and pin it before staging expires. New uploads, builds and registry publication refuse admission below 10 GiB free on their control storage filesystem; this is a pressure guard, not an atomic disk reservation. Monitor database and cleanup-backlog growth too. The runtime operator harness reserves five distinct apps plus one update candidate belonging to an already active app. It leaves the old allocation available; promotion/routing and product admission remain #5/#8/#9/#10. Supply only the owning app's database/environment, keep the environment file in root-only `/run`, and remove it after creation. Current environment-file input is a probe interface and does not implement the full multiline secret UX contract.

## Verification

Run the production Python typecheck and behavioral CLI/probe tests from the repository root:

```bash
npx --yes pyright@1.1.413
python3 -m unittest discover -s infra/tests -p 'test_*_cli.py'
python3 -m unittest discover -s probes/hosting/fixture -p 'test_*.py'
PROBE_POSTGRES_IMAGE=postgres:16 bash probes/hosting/database.sh
```

Pyright is a pinned development check, not a host runtime dependency. The database check removes its disposable local container on exit. Live checks and their limitations are recorded in [hosting validation](../docs/hosting-validation.md).

## Maintenance and teardown

Check disk/service/TLS health using [monitoring](monitor/README.md). Resend sender authority and operator receipt were verified on 2026-09-08. After configuring the foundation, run `python3 infra/remote.py enable-alerts` to install the protected local SMTP settings on both verified hosts. Run `python3 infra/remote.py enable-spending --config /path/to/spending-estimator.json` to install the approved API estimator on control. Each host independently probes the other's allowed private listener (runtime SSH; control PostgreSQL); complete host-loss alerts were delivered during separate shutdowns. This covers a single-host outage, not simultaneous loss of both hosts or the region. The operator must still inspect the account during a regional incident.

Patch one host at a time after recording installed package/kernel/runsc versions and draining affected work. Re-run isolation probes after kernel, gVisor, Docker, network policy or PostgreSQL changes. Do not patch a builder in place: create a fresh VM. For a gVisor change, supply a reviewed new immutable URL/hash, reinstall and re-run the gate. PostgreSQL minor upgrades use signed Ubuntu updates; major upgrades require an explicit data migration and fresh privilege/persistence probes. Package rollback does not imply database rollback.

Rotate Hetzner/Cloudflare tokens by replacing the exact protected files, verify read access, then propagate the Hetzner token to the trusted controller before revoking the old one. Replace the dedicated SSH key through overlapping authorized keys, verify access, then remove the old key. Rotate the age identity by decrypting and re-encrypting every bundle inside the trusted host without console output, verify recovery before removing the old key, and never delete the old key while any bundle still uses it. Rotate the database certificate before its one-year expiry and distribute the new CA to candidate images before switching PostgreSQL; failed trust checks must keep traffic closed. Public certificate renewal is Caddy-managed and must be tested live.

During an incident, keep gateway admission closed, inspect only redacted status, revoke compromised provider/operator authority and remove disposable builders through `builders.py delete ID`. A failed update leaves the old runtime allocation serving; rollback is an explicit routing action after readiness and never reverses database schema changes. Cleanup failures remain visible and retried by reconciliation; inspect billable resources in the provider account during controller outages.

Permanent foundation teardown is deliberately an explicit operator procedure, not automatic failure rollback: confirm the owned control/runtime IDs and acknowledge loss of all disposable data, stop builder admission, reconcile/delete owned builders, delete the two confirmed hosts, verify their primary IPs were deleted, then remove only the owned network/firewalls/SSH key and the exact owned DNS A record. Preserve unrelated account resources and wildcard DNS. The CLI has no permanent-host delete command; a failed deployment must not erase control data.

## Acceptance and handoff

The [dated report](../docs/hosting-acceptance-2026-09-08.md) maps #17 criteria to evidence and records the approved budget exception. Later invoices can reconcile estimates; they are not a prerequisite under the operator's decision. Product authentication/lifecycle, per-app log APIs, build allowance accounting and the final integrated gate remain their existing tickets. Keep the public gateway at 503 until those checks pass.
