# Operator monitoring

`infra/monitor.py` collects disk usage, systemd service/timer state, the last result of scheduled oneshots, peer TCP reachability and verified public TLS expiry. Disk usage at 80%, inactive service/timer, failed oneshot, unreachable peer, failed TLS verification or less than 14 certificate days remaining produces an alert. Output contains statuses and provenance, never process logs or SMTP credentials. Every report is limited to 64 KiB; the root-only report directory retains at most seven days and 10 MiB. Host journals have their separate bootstrap retention policy.

Install the script at `/opt/small-cloud/infra/monitor.py`. Put configuration at `/etc/small-cloud/monitor.json`, owned by root with mode 0600:

```json
{
  "disks": ["/"],
  "services": ["docker.service"],
  "oneshot_services": ["small-cloud-runtime-images.service"],
  "peers": [{"name": "control", "host": "10.42.0.2", "port": 5432}],
  "tls_hostname": "small-cloud.monkeysees.one",
  "smtp": {
    "host": "SMTP_HOST",
    "port": 587,
    "security": "starttls",
    "sender": "AUTHORIZED_SENDER",
    "username": "SMTP_USERNAME",
    "password": "SMTP_PASSWORD"
  }
}
```

Use `postgresql@16-main.service`, `caddy.service` and `docker-registry.service` on the control host; verify the deployed inventory first. SMTP supports certificate-verified STARTTLS or implicit TLS (`security: "tls"`, typically port 465). The fixed recipient is `monkeyseesone@gmail.com`. The operator verified receipt of a Resend test on 2026-09-08. Protected workstation configuration is recorded in [cloud access](../../docs/agents/cloud-access.md); the example above remains a placeholder. `remote.configure` installs a collection-only systemd override without `--send`, so the health timer is useful before sender access exists. It preserves existing private monitor configuration. After foundation configuration, run `python3 infra/remote.py enable-alerts` from the workstation. This checks both live server identities, ownership, German location and addresses against the protected inventory before transferring SMTP settings over SSH. It preserves existing health settings, removes the collection-only override and enables both timers. It does not send another delivery-check message. Reapplying `configure` restores collection-only mode; run `enable-alerts` again afterward.

```bash
sudo python3 /opt/small-cloud/infra/monitor.py --config /etc/small-cloud/monitor.json
sudo python3 /opt/small-cloud/infra/monitor.py --config /etc/small-cloud/monitor.json --send --delivery-check
```

The first command collects evidence without sending. The second explicitly requests a real delivery check. SMTP acceptance, provider delivery and human receipt are distinct. The original workstation test has human-confirmed receipt; Resend reports delivered for both later host-loss alerts and all three threshold tests, with no claim that those later messages were read. Provider error text is withheld because it can contain credentials. See [delivery evidence](../../docs/evidence/alert-delivery-2026-09-08.json).

`configure` installs reciprocal private TCP probes: control observes runtime SSH (22), and runtime observes control PostgreSQL (5432), each with an independent timer and SMTP authority. Probes use configured numeric IPs with a five-second connection bound and do not add firewall exceptions. The surviving host detected and sent an alert during each separate shutdown. An hourly schedule permits up to roughly one hour of detection delay; this is single-host-loss coverage, not a regional observer or recovery service. Reconcile expired builders manually during control-host loss. Managed cleanup/reconciliation/spending timers are monitored as active; their oneshot services are checked by `Result`, so a successfully completed inactive oneshot is healthy and a failed last run alerts.

The operator approved API-based cost estimates on 2026-09-08; an invoice is no longer a prerequisite for alerting. `spending.py` runs on the trusted control host every five minutes using the existing Hetzner token. The runtime host never receives provider credentials and sends health alerts only. Enable the estimator after configuring the hosts and SMTP:

```bash
python3 infra/remote.py enable-spending --config /path/to/spending-estimator.json
```

The configuration may be `{}` or contain a documented historical opening estimate:

```json
{
  "opening_estimate": {
    "month": "2026-09",
    "amount_eur": "0.4678",
    "source": "Retained temporary-validation estimate upper bound; not an invoice"
  }
}
```

The installed configuration is `/etc/small-cloud/spending-estimator.json`. September's opening amount covers the temporary resources already deleted before collection began. It applies only to the named month; it is never carried into later months.

The collector reads all servers and primary IPv4 addresses in the project, including stopped servers and unassigned addresses. It estimates rounded resource-hours with each resource's monthly cap, plus reported outgoing traffic above its included allowance, using the current account price list. Completed builder deletion journals retain the VM's creation timestamp, type, location, final traffic counters and IPv4 IDs so short-lived builds are counted between polls. A lost deletion response retains the journal for reconciliation; completed archives are retained through the following month. The month ledger is under the controller's root-only infrastructure state directory.

Amounts include the API-quoted VAT percentage and use a dated ECB EUR/USD reference rate. Current EUR account prices are required. The output at `/var/lib/small-cloud/spending.json` explicitly uses `basis: api-resource-estimate`, `estimated_usd` and `forecast_usd`; it does not claim actual invoiced charges. Month-to-date estimates and month-end forecasts independently trigger USD 50/80/100 alerts. The forecast retains currently live resources until month end; future unallocated builds and future traffic are excluded. An idle or leaked builder therefore remains in the forecast until deletion is observed.

Unsupported billable resources (volumes, snapshots, backups, floating IPs or load balancers) generate explicit coverage alerts. Estimates may miss resources created and deleted outside this controller between polls; detecting deletion on a later poll can overestimate its lifetime. The provider price API may not reflect grandfathered tariffs, credits or final invoice adjustments. Other projects, support, domains and external services are outside scope. These limits appear in the estimate report rather than being presented as a spending cap.

Evidence older than 15 minutes or FX older than seven days is rejected. Collection gaps over 15 minutes remain flagged for that month even after recovery. On collection failure the previous report remains unchanged and becomes stale; it is never refreshed with invented zero costs. The collector's own systemd deadline is three minutes. Existing verified invoice/provider-metered input remains supported separately under its original 48-hour freshness rule.

The supplied service/timer runs hourly, with at most one message per run containing all current alerts. A persistent problem therefore repeats hourly; there is no suppression or escalation controller. Run independent availability monitoring outside each observed host: a local timer cannot report its own host, network or SMTP outage. Public TLS verifies the configured endpoint and does not prove origin certificate renewal when a proxy terminates TLS. No external availability service or end-to-end notification receipt is claimed here.
