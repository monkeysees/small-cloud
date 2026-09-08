# CX procurement watcher

The operator authorized waiting for and automatically procuring one permanent CX33 control host and one CX43 runtime host in Germany on 2026-09-08. CPX substitution is excluded. The watcher checks Nuremberg and Falkenstein once per minute and provisions the pair as soon as a check finds capacity and the provider accepts creation. Capacity can disappear between a quote and creation, and account quota can still block procurement.

`cx_watch.py` is a bounded, one-shot worker for a persistent scheduler. It uses the existing protected Hetzner token and dedicated SSH key. The price ceilings are EUR 24.48/month net for the two servers and EUR 1/month net for their two primary IPv4 addresses, with corresponding hourly ceilings. Builders, DNS changes and application activation are outside this worker. Provisioned hosts begin billing immediately and are retained for subsequent configuration; there is no automatic deletion.

The installed workstation cron job uses a frozen copy under `~/.local/lib/small-cloud/cx-watch/`, independent of checkout edits. It runs every minute with a five-minute process deadline. Cron runs without an active login, but the workstation must remain powered on and connected. No separate paid monitoring host or model API is required.

The worker serializes runs with a lock and retains state in `~/.local/state/small-cloud/infra/cx-watch.json`. It records intent before resource creation; an ambiguous response prevents another create unless inventory resolves the recorded resource. Known capacity/quota rejections are retried on later checks. A partial pair stays in its original location. Completion is durable: subsequent invocations cannot buy replacements or another pair. The watcher sends email when procurement completes or a blocking condition changes, and retries failed notification delivery. SMTP acceptance cannot guarantee inbox receipt or exactly-once notification after a crash.

Inspect the installed schedule and most recent result:

```bash
crontab -l
cat ~/.local/state/small-cloud/infra/cx-watch-last.log
cat ~/.local/state/small-cloud/infra/cx-watch.json
```

Stop future checks by removing only the line marked `small-cloud-cx-watch` with `crontab -e`. This does not delete any provisioned resources. Keep the fixed SSH administrator CIDR current; changes require checking the watcher state and existing firewalls before restarting. Do not run another procurement controller concurrently with the watcher. Manual changes to procurement state require inventory reconciliation first.

For a read-only capacity and price check from the repository:

```bash
python3 infra/cx_watch.py --admin-cidr YOUR_PUBLIC_IPV4/32 --check
```

After procurement, configure the hosts using the versioned gVisor artifact and verified hash, apply DNS, then run `python3 infra/remote.py enable-alerts`. Follow the acceptance gates in [hosting validation](../docs/hosting-validation.md); procurement alone does not enable creator admission. Independent host-loss observation and actual billing ingestion remain separate work.
