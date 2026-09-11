# Server deployment and readiness

Identity, diagnostics, lifecycle and publishing are required installation-wide services. Workspaces need no worker setup. An HTTP `/health` response only establishes identity readiness; the supported deployment procedure succeeds only when all four services are ready and the runtime host receives an acknowledgement through its forwarded diagnostics socket.

## Deploy an existing installation

Build a wheel from the reviewed checkout (`python -m pip wheel --no-deps --wheel-dir DIST .`) and copy it and all four `identity/small-cloud-*.service` files to a root-owned staging directory on the control host. Verify their checksums against the local bundle. Retain the current package, unit files and protected configuration for rollback. This procedure upgrades the Python package and service units; changes to infrastructure scripts, runtime sandbox, Caddy or dependencies still need their documented coordinated installation. It does not reapply the original closed gateway.

Run as control-host root, substituting the staged wheel and directory:

```bash
/opt/small-cloud-identity/bin/python -m identity.services deploy \
  --wheel /root/deployment/small_cloud-0.3.1-py3-none-any.whl \
  --units-directory /root/deployment
```

When first installing this procedure, stage the complete source checkout too and run the command from that checkout with the existing environment's Python; the previously installed package lacks this module. Before this first upgrade, drain accepted operations because the older workers do not support graceful shutdown. Subsequent upgrades signal workers to finish their current operation before stopping diagnostics and identity. Accepted, unstarted work remains queued. The 35-minute stop bound permits the existing 30-minute remote-build deadline and handoff; forced termination retains existing uncertain-operation and accounting rules. No deployment replay, reservation clearing or application-state repair is performed.

The command serializes against other deployment/maintenance commands, enters persistent maintenance, stops workers, installs the wheel without changing dependencies, installs/enables the units, starts identity and verifies the complete service. An installation failure leaves maintenance active. A readiness failure exits nonzero and must not be reported as a successful deployment. A readiness check is a point-in-time observation, not a future availability guarantee.

## Restart, readiness and recovery

```bash
systemctl restart small-cloud-identity
/opt/small-cloud-identity/bin/python -m identity.services check
```

Starting identity pulls in all required workers, including after a separate stop/start or control-host boot. Identity's HTTP check completes before dependents start. Diagnostics establishes a pinned SSH Unix-socket forward and answers a random challenge from the runtime host; file existence, connect success and a live SSH process are insufficient. Publishing/lifecycle start after diagnostics startup, independently verify dependencies, acquire exclusive process locks, and report ready after their existing recovery completes. They recheck dependencies while idle and immediately before runtime start/resume.

Collector/tunnel outages have a 45-second recovery deadline. Workers wait at most 45 seconds for dependency recovery between operations; individual probes also have network timeouts. Systemd retries failed services after five seconds, with at most four starts per ten minutes. Persistent failure stays failed until operator intervention; ordinary commands do not reset these limits. Runtime diagnostics gaps retain their existing visible interruption markers. Systemd owns child processes and the kernel releases process locks only when their owners exit.

Inspect `systemctl status small-cloud-{identity,diagnostics,lifecycle,publishing}` and their journal entries after failure. Check root-owned configuration, pinned SSH access to the runtime, the runtime Docker service and the collector's root-only sockets. Run `identity.services dependencies` to retest identity plus the end-to-end socket path. Raw app output stays suppressed; do not enable Docker log caching to investigate. After repairing the cause, use `resume` below to reset only these services' restart counters and verify readiness. Inspect any reported `reconciliation_required` operation separately using [publishing recovery](PUBLISHING.md); resuming services does not repair it.

The supported boot case assumes the runtime host is available. Runtime-host reboot reconciliation and disaster recovery remain outside this procedure.

## Intentional maintenance

```bash
/opt/small-cloud-identity/bin/python -m identity.services maintenance-stop
# Perform the intended maintenance, then explicitly resume:
/opt/small-cloud-identity/bin/python -m identity.services resume
```

Maintenance creates `/etc/small-cloud/maintenance` before draining and stopping services. All four units refuse startup while it exists, including across boot or an accidental identity start. `deploy` refuses to override existing maintenance. `resume` removes the marker, resets service failure counters, starts identity with its dependents and verifies full readiness. Keep the marker if repairs are incomplete. These commands preserve app URLs, data, sharing, memberships, credentials and workspace defaults.

## Local verification

`python -m unittest identity.tests.test_services identity.tests.test_service_readiness identity.tests.test_service_commands` exercises operator deployment, readiness and maintenance commands and actual user-systemd dependency transactions. Systemd tests require a running Linux user manager (`XDG_RUNTIME_DIR`) and explicitly skip elsewhere. Isolated units retain the shipped dependency/restart/maintenance graph; controlled process fixtures replace privileged cloud work, use real kernel locks and emit real readiness notifications. Command tests redirect host paths, root identity, package installation and SSH transport at their external boundaries; the actual commands, systemd manager, HTTP readiness and collector challenge remain in use. Hosted acceptance separately verifies the installed privileged processes and actual runtime tunnel.
