# Disposable builder

This operator harness executes one uploaded Dockerfile on a fresh Ubuntu 24.04
x86_64 VM in the EU. The provisioner must create and delete the VM, reconcile
controller failures, and provide every platform management/database public IPv4
address. It must never install cloud API tokens, registry credentials, runtime
secrets or database credentials on this VM. An SSH public key is sufficient for
the trusted upload/export channel; its private key stays with the operator.

Run `bootstrap.sh` as root before uploading any creator content. Copy `run.sh`
and `worker.py` to `/opt/small-cloud-builder/`, then upload an **uncompressed** tar
archive to `/var/lib/small-cloud-build/context.tar`. Run:

```bash
bash /opt/small-cloud-builder/run.sh /var/lib/small-cloud-build/context.tar 203.0.113.10 203.0.113.20
```

Replace the example addresses with the actual control, database, runtime and
other public management endpoints. The harness cannot discover this inventory.
Private/link-local destinations and all traffic to the builder host are denied
regardless of the supplied addresses. IPv6 is disabled. DNS uses public
resolvers; addresses reached after resolution/redirects remain subject to the
host firewall. The Docker daemon and its containers run in a separate network
namespace, while the enforcing nftables rules remain in the host namespace.
No daemon TCP port, host socket mount, secret mount, build argument, SSH mount,
privileged build entitlement, or private dependency authentication is supplied.

The source validator rejects links, special files, traversal, mandatory excluded
names and archives larger than 116 MiB, and allows at most 100 MiB extracted
source and 10,000 archive entries. Packaging `.dockerignore` semantics and local
credential-file identity checks belong to the publishing CLI; this operator
harness does not replace them. The required root Dockerfile is executed through
BuildKit. A 10 GiB ext4 filesystem contains source, daemon state, cache and image
export. An ancestor systemd slice limits the daemon, builds and export together
to two CPUs, 3,500 MiB memory, no swap and 512 tasks. Memory is below the proposed
4 GiB ceiling to preserve some host capacity on a 4 GB provider VM.

An independent host systemd timer kills the entire slice 600 seconds after
execution admission, including daemon startup, downloads and image export.
It survives a lost operator SSH connection. The VM is single-use even if source
validation fails. Always delete the VM on success, error, cancellation or timeout;
the local timer does **not** delete the billable VM. Provider reconciliation is
also necessary if the guest or controller fails. Do not release a build allowance
reservation until termination has been confirmed by the controller.

After a successful SSH command, retrieve `output/result.json`, `output/image.tar`,
`output/build.log` and `output/daemon.log` from `/var/lib/small-cloud-build` over SSH. Check `ok` and
verify the archive SHA-256 before accepting the image. The image archive is at
most 500 MiB and each raw build/daemon log at most 10 MiB; further build log bytes are counted
and discarded while draining the child pipe. Daemon output is flushed continuously
so startup failures remain diagnosable before the controller deletes the VM.
A missing result (for example after
deadline/OOM) is failure, never a successful artifact. Treat log bytes as untrusted
and escape terminal controls before display. Retention, structured log records,
workspace aggregate quotas and the accounting ledger belong to the controller.
Results record UTC start/end and monotonic execution seconds from daemon readiness
through Dockerfile execution and image export, including ordinary build failure.
A forced kill may retain a start record with null end/duration; the controller
must reconcile termination rather than infer completed accounting from that record.
These measurements do not implement the workspace allowance ledger or prove guest
termination, and exclude bootstrap/daemon readiness before Dockerfile submission.

This is implementation for deployment evaluation, **not acceptance evidence**.
Run the build matrix and exhaustion/deadline checks in
[`probes/hosting/README.md`](../../probes/hosting/README.md) inside actual uploaded
Dockerfile `RUN` steps. Verify cgroup ancestry, namespace firewall counters,
healthy forbidden-endpoint controls, public HTTPS, IPv6 denial, export limits,
disconnect handling and cloud deletion before admitting creator workloads.
The VM boundary also needs evaluation against the current kernel/daemon versions;
this implementation does not claim protection from a guest kernel escape.

Package versions come from the Ubuntu archive at bootstrap time and must be
recorded in each evaluation result; no prepared image or shared cache is used.
The runner explicitly disables the containerd snapshotter and selects `overlay2`
so Docker 29's changed fresh-install default cannot redirect image storage outside
the bounded filesystem. Package bootstrap also clears Docker's leftover host
FORWARD drop policy; the runner installs its own default-deny nftables forwarding
rules before starting the isolated daemon.
Configuration follows the official [Docker daemon reference](https://docs.docker.com/reference/cli/dockerd/),
[Docker build driver](https://docs.docker.com/build/builders/drivers/docker/) and
[Docker firewall documentation](https://docs.docker.com/engine/network/packet-filtering-firewalls/).
Live acceptance must establish that the installed Ubuntu package versions honor
these controls; documentation alone cannot establish isolation.
