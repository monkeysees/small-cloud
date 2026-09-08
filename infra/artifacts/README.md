# Control staging retention

Install `infra/artifacts.py` at `/opt/small-cloud/infra/artifacts.py` and the provided hourly service/timer under `/etc/systemd/system`. The service requires no credentials and can write only `/srv/small-cloud/source`. Its 60-second deadline, 64 MiB memory ceiling and eight-task limit bound execution. Enable the timer after the root-owned mode-0700 staging directory exists.

The janitor only recognizes direct job subdirectories carrying a private operator-owned `.small-cloud-build.json` with numeric epoch `created_at`. `finished_at` may also be recorded but does not extend retention: builds have a separate shorter lifetime limit. `image.tar` and `source.tar` become eligible after 23 hours, leaving one hourly sweep before 24 hours; `admission.log`, `builder.json`, `build.log`, `daemon.log`, `result.json`, `teardown.json`, `resources.json` and the marker expire after seven days. Empty expired job directories are removed. Original caller contexts and all unknown names are preserved. Receive uploads through `artifacts.py --stage JOB` on stdin to bring them into managed retention: it creates a new private `upload-JOB/source.tar`, limits input to 116 MiB and refuses duplicate jobs. Do not leave original creator uploads in unmarked files.

Root and job directories must have mode 0700 and belong to the invoking operator; managed files must be private, regular and owned by that operator. Links cause refusal before any files in that job are removed. The scan never recurses: it streams root entries with constant memory, accepts at most 64 entries per job, and reads at most 4096 marker bytes per job. The service's 60-second deadline bounds each sweep; completed deletions remain effective if the next sweep must continue a backlog. Artifact contents are never read. A refusal returns nonzero and a bounded count without file contents. `--root` selects an isolated operator-owned directory for local verification.

## Release handoff

These are trusted root operator operations for #5/#8/#9/#10, not commands exposed directly to creators. The single control host holds provider/SSH authority. Caddy and the registry use their separate service accounts; PostgreSQL administration uses its OS account and local peer authentication. Tool roles cannot administer databases. Build VMs receive one bounded source archive and no reusable credentials; tool sandboxes run as UID 65532 with only their own environment. The private runtime SSH channel uses the pinned host identity. Neither the registry nor Docker exposes a network management API to tools.

After `remote.py build`, require `result.json` to report success and verify the returned archive's byte count/SHA256. On control, publish the private archive:

```bash
python3 /opt/small-cloud/infra/releases.py publish tool-a release-a /srv/small-cloud/source/unique-build-result/image.tar
python3 /opt/small-cloud/infra/releases.py list
```

Publication uses Ubuntu's signed `skopeo` package and the loopback-only registry. It records an immutable manifest digest and archive hash under root-only `/srv/small-cloud/releases`; each release has a separate repository `small-cloud/TOOL/RELEASE:release`, so deleting an identical manifest for another release cannot remove this reference. IDs use lowercase letters/digits separated by hyphens, at most 32 characters. Repeating a completed publication with the same archive returns its existing record. A different archive requires a new release ID. Pending publication is journaled before transfer; retry the same archive after interruption. New publication, source staging and build admission require 10 GiB free. Reads, retirement and cleanup remain available under storage pressure.

Transfer the checked archive over the operator's private SSH channel into a root-only runtime staging file, verify its hash there, and use trusted `docker load`. Delete that staging file immediately in the transfer's `finally` path. Resolve the loaded immutable image ID; never trust creator labels as retention authority. Pin it before starting the sandbox:

```bash
python3 /opt/small-cloud/runtime/sandbox.py --config /etc/small-cloud/runtime.json retain-image tool-a release-a sha256:IMAGE_ID
python3 /opt/small-cloud/runtime/sandbox.py --config /etc/small-cloud/runtime.json start tool-a sha256:IMAGE_ID
```

Use the [database handoff](../control/README.md) to supply only this tool's credentials through a private `/run` environment file, removed after creation. New candidates use `start ... --candidate`; keep the current container and release reference while checking readiness. Product code owns routing promotion, request identity, authorizations and lifecycle state. The harness offers no implicit promotion and never treats a sixth independent tool as update headroom.

Both release stores allow thirty tools and two retained releases per tool (current plus candidate/previous). On a further update, retire the superseded previous release explicitly. After traffic and allocation removal, retire both references:

```bash
python3 /opt/small-cloud/infra/releases.py retire tool-a release-a
python3 /opt/small-cloud/runtime/sandbox.py --config /etc/small-cloud/runtime.json forget-release tool-a release-a
```

The hourly registry janitor deletes pending/retired manifests after 23 hours, then stops the registry during garbage collection under the publication lock and restarts it even after an error. Retained releases never age out. Removal is retried idempotently; records disappear only after successful GC. This short registry maintenance window does not stop already-running tools. Runtime cleanup protects retained references and all containers, removes only operator-tracked images with `docker image rm --no-prune` without force, and starts a new one-hour grace when the final reference is forgotten. The `--no-prune` flag is essential: Docker otherwise may delete an untagged parent retained by another release. Its hourly sweep leaves substantial retry time inside the 24-hour cleanup contract. Pending/retired registry records and tracked runtime images each cap at 256; do not bypass a full inventory—repair cleanup. Timers and last oneshot results are monitored. A missed cleanup deadline remains an operational failure, not permission to extend retention.

Dependency check, 2026-09-08: Skopeo is the maintained containers/image transfer tool, with active upstream releases (1.24 series); the host installs Ubuntu 24.04's signed 1.13.3 package. See [upstream releases](https://github.com/containers/skopeo/releases), [copy semantics](https://github.com/containers/skopeo/blob/main/docs/skopeo-copy.1.md), and [registry garbage collection](https://distribution.github.io/distribution/about/garbage-collection/). Live publish/retire/GC and retained-manifest checks are recorded in the acceptance evidence.
