# App runtime secrets

Creators can configure their own apps through `small-cloud secret set`, `secret delete` and name-only `secret list`. Administrator diagnostics authority does not grant secret management or secret-name access to another creator's app. There is no saved-value readback route.

```bash
small-cloud secret set example SERVICE_TOKEN --stdin < /secure/disposable-token
small-cloud secret list example
small-cloud secret delete example SERVICE_TOKEN --wait
```

Omit `--stdin` for a hidden terminal prompt. JSON mode, `--no-input` and non-terminal input require explicit `--stdin`. Values are never command arguments. Stdin preserves trailing newlines, accepts 1–16,384 UTF-8 bytes without NUL, and is bounded before submission. Names match `[A-Z_][A-Z0-9_]{0,127}`; `PORT`, `DATABASE_URL` and `SMALL_CLOUD_*` are reserved. Each app has at most 50 names.

Set always replaces saved configuration and restarts execution. Delete restarts only when the name exists. Changed configuration is encrypted and saved atomically with an operation receipt; traffic is denied before acknowledgement, the old runtime is stopped, and the retained release starts using the saved environment. URL, release, database and sharing are preserved. This does not run a build or consume build allowance. Previously stopped apps start subject to the five-app capacity limit; refusal occurs before saving when all slots are occupied. Other pending app operations conflict.

`--wait` observes completion; `--timeout` bounds only waiting. Without it, success means accepted. Reconcile a disconnected request with `operation status --request-id UUID`; retrying the same ID and input rechecks authority and returns the original receipt. Different input conflicts. Fingerprints use a keyed digest rather than a guessable plain value hash.

Startup failure leaves the new configuration saved and the app unavailable, with `STARTUP_FAILED`, `configuration_saved:true` and the operation ID. Retry startup through the existing app retry route, or redeploy. A first deployment that never became ready can still receive configuration: its secret operation reports saved configuration and failed startup because no ready release exists; redeploy with the saved values. There is no fallback to old credentials. Unconfirmed stop retains capacity and requires operator reconciliation before another start.

## Sharing and trust

Sharing a secret-bearing app workspace-wide requires `--acknowledge-secret-authority` or an interactive acknowledgement. Setting a secret on an already shared app requires the same acknowledgement. Authorized users can trigger credential-backed actions exposed by the app. Creators must choose appropriately scoped credentials and their external destinations; app code can disclose entrusted secrets. Returning to creator-only denies subsequent member requests but cannot recall actions already performed.

## Storage, delivery and diagnostics

The identity service creates `app-secrets.key` beside its protected SQLite database, owned by the service with mode 0600. Preserve this key with the database; losing it makes configured and retained values unreadable. Fernet authenticated encryption protects current and retired values. The key is separate from the root-only diagnostics key. The trusted identity service and root workers can decrypt configuration; app and management APIs cannot read it back.

Only runtime startup and wake-up load saved values. Source archives and builders receive none. The controller sends bounded JSON through pinned SSH stdin into a root-only temporary file under `/run`; the sandbox sends environment values to the local Docker socket without putting them in argv or the Docker client's environment. JSON preserves multiline values. Platform `DATABASE_URL` and `PORT` take precedence. Runtime staging files are removed on completion; uncertain cleanup is visible as an operation failure.

Diagnostics redact current values and encrypted retired values before persistence and truncation. Replaced/deleted values remain until seven days after confirmed old-runtime termination; an uncertain stop retains them until reconciliation. The existing collector prunes expired history even without CLI reads. Literal redaction cannot prevent deliberate encoding or disclosure by app code.

Upgrade the identity service before workers/collector to create the schema and key; drain workers during the coordinated upgrade and install the updated sandbox before restarting publishing and lifecycle workers. No cloud resource or new dependency is required. Existing operator `--env-file` remains supported; product startup uses `--env-json`.

## HTTP interface and verification

`GET /api/apps/<app>/secrets` returns `{names:[...]}`. `POST /api/apps/<app>/secrets/set` accepts `{name,value,acknowledge_secret_authority?}`; `/secrets/delete` accepts `{name}`. Mutations require a bearer credential and UUID `X-Request-ID`. Changed mutations return HTTP 202 and a `secret-change` operation; absent deletion returns HTTP 200 with `changed:false`.

Local automated acceptance covers CLI stdin, sharing acknowledgement, exact multiline runtime delivery to a controlled external HTTP service, replacement/deletion, owning-app isolation, unauthorized access, capacity refusal, saved startup failure, request reconciliation and retained-value redaction. See `identity/tests/test_secrets_http.py` and the secret test in `identity/tests/test_database_http.py`. These checks are local evidence; the separate [hosted acceptance report](../docs/acceptance/app-secrets-2026-09-09.md) records deployed verification and its identity/browser boundary.

The runtime handoff follows Docker's [container-create API](https://docs.docker.com/reference/api/engine/version/v1.49/), using `Env` and the existing host restrictions. The local socket test checks request contents and safe failure; hosted acceptance also verified this handoff on gVisor.
