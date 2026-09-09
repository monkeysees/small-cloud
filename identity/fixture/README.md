# HTTP/database starter and acceptance app

Deploy this directory through the creator CLI, with no local Docker:

```bash
small-cloud deploy identity/fixture --name publishing-probe --description 'Disposable database starter' --wait
```

Open the returned app URL and complete Google sign-in. Browser requests to `/` show a disposable-data notice and a form for saving entries. JSON requests to `/`, and all requests to `/identity`, return the three trusted gateway identity headers; name and email remain their unpadded base64url wire encoding. The internal `/_small-cloud/ready` endpoint succeeds only after database initialization and returns 404 through public authenticated ingress. The fixture relies on the platform to check every route before forwarding. Run it locally only on a trusted development machine.

`/network` checks the fixed source-controlled destinations in `targets.json`, with two-second socket timeouts and a 2.5-second aggregate deadline. It accepts no caller-supplied addresses and never renders environment variables, database credentials or provider errors. Public HTTPS should connect; metadata and private SSH should fail. A failure alone is not proof of isolation: independently verify the control/runtime SSH listeners are reachable from their permitted source. A `timeout` is inconclusive. Customize public management address probes only by editing `targets.json` before redeploying; never put credentials in that file.

## Database contract

The platform supplies `DATABASE_URL` only at runtime. Each app has a persistent logical PostgreSQL 16 database and a restricted role on the shared German control host. The supplied URL verifies the server certificate using `/etc/small-cloud/database-ca.crt`; retain its TLS parameters. Do not print the URL, put it in source/build arguments, or return it from HTTP handlers. The starter uses the existing pinned Python 3.12 image, UID/GID 65532, and pinned Psycopg 3.3.5 binary wheels. Psycopg is confined to the starter; the platform CLI does not require it.

The author owns initialization and migrations. `app.py` initializes its table in a transaction before listening, takes a database-local advisory lock to serialize overlapping startups, and uses `CREATE TABLE IF NOT EXISTS` without dropping or reseeding existing rows. Request values use SQL parameters. Each request opens and closes its connection; there is no separate migration runner. For future schema changes, write compatible migrations in app startup: `IF NOT EXISTS` alone does not migrate an existing table. A failed startup does not undo previously committed schema changes or repair incompatibility with the old release.

**Data is disposable.** Use only data users can afford to lose. Database rows survive ordinary process/container restarts and redeployments, but the pilot provides no backup or recovery guarantee. Container filesystems, `/tmp`, and in-memory state are temporary; never use them as durable storage. `/tmp` also consumes the app memory budget. Reset and deletion are separate platform work; this starter supplies no destructive endpoint.

| Authenticated HTTP request | Result |
| --- | --- |
| `GET /` with `Accept: text/html` | Entry form and visible disposable-data notice. |
| `POST /data` with JSON `{"value":"Weekly priority"}` | HTTP 201 with the inserted `id` and `value`; accepts 1–4096 UTF-8 bytes, excluding NUL. |
| `GET /data` | First 100 entries in insertion order. |
| `GET /database/isolation?database=tool_OTHER_APP_DATABASE_ID` | Own-database success, other-database authorization denial, other-role authentication denial and maintenance-database denial. |

The isolation endpoint accepts only another app's nonsecret database identifier, never a host, URL, password or SQL statement. It keeps its own URL's host, TLS settings and password, changing only the target database/role. Obtain the other identifier from the operator provisioning metadata. Each expected denial is distinguished from an inconclusive network/TLS error; no driver error text or credentials are returned. Keep this diagnostic endpoint only while useful for acceptance; it is not a general database query API.

## Repeatable acceptance

Install the platform and starter dependencies in a Python 3.11+ virtual environment, then run:

```bash
python -m pip install . -r identity/fixture/requirements.txt
python -m unittest identity.tests.test_database_http.DatabaseAcceptance
npx --yes pyright@1.1.413 --pythonpath "$(command -v python)"
```

The database suite requires local Docker, builds a test-only PostgreSQL 16 image with `age` and Python, and removes its database container/volume afterward. This requirement belongs to the acceptance harness; creators still publish without local Docker. Tests exercise the real provisioning helper, CLI, authenticated gateway and starter processes. Local PostgreSQL uses loopback TCP without TLS; deployed TLS, gVisor and network isolation require separate live evidence.

For live acceptance, publish two instances with distinct names, save a row through the protected app, restart the first app through the operator runtime CLI, and read the same row. Publish the same source to the same name again and repeat the read. Run isolation probes in both directions and verify `/network`. Never paste a CLI credential into shell arguments; load it inside a trusted HTTP client process. See [database acceptance](../DATABASE.md) for recorded outcomes.

Dependency health checked 2026-09-09: Psycopg 3.3.5 was released 2026-08-31; its active upstream repository has approximately 2,500 stars. Sources: [official download](https://www.psycopg.org/download/), [upstream repository](https://github.com/psycopg/psycopg).
