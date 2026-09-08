# Runtime host operator harness

This operator harness was exercised on the permanent German runtime VM for #17. It is not the product admission controller. Creator admission remains closed pending product integration and verification #15; see the [infrastructure acceptance report](../../docs/hosting-acceptance-2026-09-08.md).

`install.sh` installs Ubuntu's Docker package and a supplied immutable, checksum-verified gVisor release. Set `RUNSC_URL` to an official versioned `gvisor.tar.bz2` release bundle and `RUNSC_SHA256` to its independently obtained hash. Record the resulting Docker/runsc/kernel versions in evidence. Reapplication accepts the matching managed daemon configuration and refuses unknown settings; do not use this bootstrap on a shared machine.

Copy `sandbox.py` to the host and provide a root-owned configuration:

```json
{
  "control_private_ip": "10.42.0.2",
  "database_private_ip": "10.42.0.2",
  "runtime_private_ip": "10.42.0.3",
  "management_public_ips": ["203.0.113.10", "203.0.113.11"]
}
```

Replace every address with the deployed inventory. Include all public control/runtime/registry management addresses. DNS aliases are not an IP policy: refresh and apply the inventory before an address changes. Load an immutable image on the host through trusted operator tooling; the runner never pulls images or receives platform credentials.

```bash
python3 sandbox.py --config /etc/small-cloud/runtime.json policy
sudo python3 sandbox.py --config /etc/small-cloud/runtime.json start app-a registry.example/app@sha256:REPLACE
sudo python3 sandbox.py --config /etc/small-cloud/runtime.json start app-a registry.example/app@sha256:REPLACE --candidate
```

The host lock and Docker labels reserve five distinct active apps and one candidate belonging to an existing app. Stopped/failed allocations still reserve capacity. Root may explicitly remove an allocation with `docker rm -f NAME` after confirming it is disposable. No automatic candidate promotion or routing change exists: the old app stays running, and the gateway must not route normal traffic to a candidate. This harness exposes separate private probe ports 18080–18085 to the control host only. Application HTTP must listen on port 8080 as UID 65532.

Each sandbox uses runsc, a read-only root, no capabilities, one read-only public DNS configuration mount, 0.5 CPU, 512 MiB memory without swap, 128 processes, 1 GiB maximum `/tmp` tmpfs and a 1 MiB shared-memory mount. Tmpfs pages count toward the tighter memory budget, so applications cannot expect to fill 1 GiB. Images declaring volumes are rejected. Logs are disabled for this harness to prevent disk exhaustion; production bounded log collection remains separate work. Root-owned Docker images and host package files are outside these runtime write limits and require host storage accounting.

An nftables chain runs before Docker's filter chains and enforces both bridge forwarding and host-input denial. App-to-app traffic is denied, private/reserved IPv4 ranges and management public IPs are blocked, and PostgreSQL on the configured database address is the sole new private egress exception. Existing control connections may receive replies. New inbound app connections must originate at the control private address. IPv6 forwarding to/from app bridges is denied independently of the host IPv6 disable setting. The atomic policy is reinstalled before every launch. Containers have no restart policy, so a reboot cannot start workloads before policy installation. Do not start these containers directly with Docker after reboot.

Provisioning must also restrict runtime host SSH to the operator/control source, expose no Docker API, allow PostgreSQL only from the runtime private address, and keep registry credentials outside sandboxes. Separate per-app database authorization is still mandatory. Live probes must establish internet and own-database success; private, metadata, public-management, peer-app and IPv6 denial; gVisor operation; all resource limits; host restart behavior; five apps plus candidate; and candidate failure preserving the old allocation. See the dated hosting evidence for observed results and remaining gaps.

Design sources: [gVisor Docker integration](https://gvisor.dev/docs/user_guide/quick_start/docker/), [gVisor installation](https://gvisor.dev/docs/user_guide/install/), and [Docker firewall behavior](https://docs.docker.com/engine/network/packet-filtering-firewalls/). Docker port publishing passes through forwarding; host INPUT rules alone do not protect it.

The runner also accepts Docker image IDs (`sha256:` plus 64 hex characters) after trusted `docker load`. Supply optional `--env-file /root/app-a.env` for `DATABASE_URL` and owning-app secrets: the file must be root-owned with mode 0600. Values are never printed or put in command arguments. Docker's root-only metadata holds the injected environment; keep Docker access restricted to trusted operators. `PORT=8080` is always set after the supplied environment.

Place the public database CA at `/etc/small-cloud/database-ca.crt` on the runtime host. The runner copies the CA into a temporary stopped container, commits a derived image without executing creator code, removes the temporary container, then creates the read-only sandbox from the resulting immutable image ID. Docker forbids copying into an already read-only root; no host bind mount is used. Derived images require the same host storage accounting and pruning as imported images. Configure `DATABASE_URL` with `sslmode=verify-full` and `sslrootcert=/etc/small-cloud/database-ca.crt`. Failed preparation leaves a stopped allocation reserved for operator inspection/removal. Host journald is bounded to seven days, 1 GiB persistent and 256 MiB runtime storage.

The runner sets both the cgroup PID limit and guest `RLIMIT_NPROC` to 128. The selected gVisor release must still pass a guest fork/thread probe; configuration alone does not prove the guest task bound.

Since July 2026, gVisor requires the bundled `gvisor-bin/` sidecars beside `runsc`. The installer verifies the complete `gvisor.tar.bz2` archive and extracts it into `/usr/local/bin`; a standalone runsc binary is insufficient. `RUNSC_URL` names the bundle and `RUNSC_SHA256` its complete archive digest.

Imported and derived CA images are registered by immutable image ID in the operator's private `/var/lib/small-cloud-runtime/images` directory, independently of creator-controlled image labels. `retain-image APP RELEASE IMAGE_ID` protects an imported image even when its app has no container; `forget-release APP RELEASE` explicitly unpins it and restarts its cleanup grace. The private release inventory permits thirty apps and two references each. `prune-images` removes only unpinned registered images older than one hour, using `docker image rm` without force so container references remain protected too. Unknown images are never removed. The hourly `small-cloud-runtime-images` unit bounds each cleanup run to five minutes, with retry headroom inside 24 hours. At most 256 tracked images may be staged. Records are mode 0600; malformed or linked records are refused. Abrupt process loss between Docker commit and inventory persistence still requires explicit operator reconciliation; no label-based adoption is attempted. Follow the [release handoff](../artifacts/README.md#release-handoff) for registry publication and bounded import staging.

Docker user-defined bridges expose embedded loopback DNS that gVisor cannot reach. The runner therefore mounts only its fixed public resolver file (`/etc/small-cloud/runtime-resolv.conf`) read-only at `/etc/resolv.conf`; it contains Cloudflare/Google public resolver IPs, no host data or credentials. This named exception preserves sandbox networking and per-app bridges. The file must remain operator-owned, regular and unmodified; no creator chooses its source or contents.
