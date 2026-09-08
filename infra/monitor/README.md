# Operator monitoring

`infra/monitor.py` collects disk usage, systemd service state and a verified public TLS certificate's expiry. Disk usage at 80%, an inactive service, failed TLS verification or less than 14 certificate days remaining produces an alert. Output contains statuses and provenance, never process logs or SMTP credentials. Every report is limited to 64 KiB; the root-only report directory retains at most seven days and 10 MiB. Host journals have their separate bootstrap retention policy.

Install the script at `/opt/small-cloud/infra/monitor.py`. Put configuration at `/etc/small-cloud/monitor.json`, owned by root with mode 0600:

```json
{
  "disks": ["/"],
  "services": ["docker.service"],
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

The first command collects evidence without sending. The second explicitly requests a real delivery check. An SMTP acceptance response is not recipient receipt: independently confirm the received message before recording delivery as verified. Provider error text is withheld because it can contain credentials. The workstation SMTP path has verified recipient receipt; deployed host delivery remains to be exercised after provisioning.

Spending alerts require a separately computed, redacted evidence file supplied with `--spend`. For example (replace amounts, sources and timestamps with observed evidence):

```json
{
  "actual_usd": 0,
  "forecast_usd": 0,
  "actual_basis": "provider-metered",
  "as_of": "2026-09-08T12:00:00Z",
  "source": "REPLACE: provider metering export identifier and billing month",
  "fx_source": "REPLACE: observed FX source, pair and conversion rate; identity conversion for USD",
  "fx_as_of": "2026-09-08T12:00:00Z"
}
```

`actual_basis` must be `provider-metered` or `invoice`; list-price estimates do not establish actual spend. The producer must include compute, hourly rounding, addresses, storage, traffic and applicable tax, explain forecast assumptions in its source artifact, and convert to USD with the recorded FX rate. This script checks structure/freshness, not the truth of external metering. The data must be at most 48 hours old and FX evidence at most seven days old; unavailable or stale data alerts that cost monitoring is unavailable. Actual and forecast totals independently alert at USD 50, 80 and 100, reporting the highest crossed threshold. Quotes and estimates must remain labeled in separate planning artifacts until actual billing evidence exists.

The supplied service/timer runs hourly, with at most one message per run containing all current alerts. A persistent problem therefore repeats hourly; there is no suppression or escalation controller. Run independent availability monitoring outside each observed host: a local timer cannot report its own host, network or SMTP outage. Public TLS verifies the configured endpoint and does not prove origin certificate renewal when a proxy terminates TLS. No external availability service or end-to-end notification receipt is claimed here.
