# Uploaded Dockerfile and runtime fixture

Prepare a temporary context containing this `Dockerfile`, `targets.json`, and
`../network.py`. Replace the public HTTPS target with a controlled endpoint and
include a unique request nonce in its `path`; correlate that nonce with endpoint
logs. Add every actual public management listener and private canary. Confirm
forbidden targets are listening from a trusted control before **and after** each
run, and only then set their `control_verified` fields to true. A timeout against
an absent service is not isolation evidence. The example configuration deliberately
leaves these checks inconclusive. Record the resolved base-image digest separately
or replace the base reference with its verified immutable digest before building.

The Dockerfile runs the network probe during a real `RUN` step. Its output contains
status metadata only, with no HTTP bodies or credential values. It does not stop
the build for failed/inconclusive checks so that the same image can reach runtime
evaluation; use `--strict` for a fail-closed standalone probe. Runtime serves
readiness at `/_small-cloud/ready`, a lightweight liveness response at `/`, and
the independently executed runtime network matrix at `/probes`. Only trusted
operator ingress may reach this evaluation fixture.

Each connection has a three-second timeout and bypasses proxy settings. DNS
failure, connection refusal, and unverified target health never pass a denial
check. An HTTP error from a forbidden endpoint fails because TCP connected.
The IPv6 interface count supplements direct IPv6 attempts; zero interfaces alone
does not prove disabled IPv6. Run direct IP and hostname targets separately.
Proxy-aware paths, redirects, DNS rebinding and independent canary health remain
explicit extra acceptance work from the parent probe README.

Optional commands `python3 /probe/network.py cpu|memory|pids|disk` run separate
bounded exhaustion fixtures. They have a 15-second internal alarm and finite
allocation ceilings (768 MiB memory, 192 children, 1,152 MiB disk). Run each with
an independent operator timeout and a neighboring liveness check. An OOM kill
may prevent a result; retain the container exit state and host cgroup counters.
The disk fixture uses `/tmp`, so runtime memory may stop it before its disk bound.
These results expose observations, never a blanket resource-isolation pass.
The fixed memory/disk ceilings cannot validate the larger build limits; use
separate externally bounded build exhaustion fixtures for that evidence.

The image includes Debian's signed-repository `postgresql-client` package for
the runtime-only database check. Supply `DATABASE_URL` through the protected
runtime env file and set `PROBE_OTHER_DATABASE` to the second app's database
name. For the control helper, the name is `tool_` followed by the first 24 hex
characters of SHA-256 of the immutable app ID (for example `probe-a`/`probe-b`).
Never supply these credentials to the build. `GET /database` or
`python3 /probe/network.py database` performs repeatable own-database table
creation, upsert and readback, then changes only the URL database path to the
other app, `postgres` and `template1`. Only an explicit database permission
denial passes each cross-database check; timeout/authentication failures do not.
Run once with each app's own credentials and reverse the other database name.
The URL is split into libpq's `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`,
`PGPASSWORD`, `PGSSLMODE` and `PGSSLROOTCERT` environment variables; `PGDATABASE`
alone does not parse a connection URI. Passwords never appear in process arguments or probe results. Output contains
only configuration status and check booleans. The public CA must already be
installed by the runtime harness at the URL's configured `sslrootcert` path.
