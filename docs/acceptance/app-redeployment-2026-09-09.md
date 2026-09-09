# App redeployment acceptance — 2026-09-09

Issue [#8](https://github.com/monkeysees/small-cloud/issues/8), against specification [#1](https://github.com/monkeysees/small-cloud/issues/1). The existing worker already builds and checks a candidate before selecting it; this increment adds executable proof and creator recovery documentation without changing the deployment protocol.

## Verified behavior

The reusable HTTP/database acceptance suite passes eight tests. Three new tests upload source through the real creator CLI, build that uploaded archive with Docker, and launch its resulting image against a real, app-scoped PostgreSQL database. Assertions use CLI status and authenticated HTTP through the platform gateway. Each uploaded variant returns a distinct release marker, so retaining an old version cannot accidentally satisfy a successful-update assertion.

- Successful updates change the serving release while preserving URL, sharing scope and previously written rows in both creator-only and workspace-wide modes. An ordinary member remains denied in creator-only mode and gains access in workspace-wide mode.
- A Dockerfile with `RUN false` fails its build. A separately built image exits before readiness. Both leave the previous deployment ID and HTTP release marker selected, with saved data readable. App status and request-ID operation status identify `BUILD_FAILED` and `STARTUP_FAILED` separately. A corrected update subsequently succeeds with the rows preserved.
- A candidate commits an incompatible column rename and then exits. The old release still answers its identity route, while reads and writes requiring the original column return HTTP 503. A creator-authored repair restores the column and the original rows through a subsequent deployment. This explicitly demonstrates that previous-container availability is not database rollback or old-schema compatibility.

The first release-marker regression failed against the old harness, which ignored uploaded source, and passed after the harness built and ran the actual archive. Successful promotion stops the previous test container; failure cleanup stops only the candidate. Test cleanup removes the containers, per-deployment image tags and disposable PostgreSQL volume.

## Reproduce and interpret

Final verification passed 156 tests: 66 identity tests (including all eight HTTP/database checks), 86 infrastructure CLI tests and four hosting-fixture tests. Pyright 1.1.413 reported zero errors and warnings; `git diff --check` passed. Independent Standards and Spec reviews found no issues.

Use the dependencies and Python environment described in the [identity runbook](../../identity/README.md). Local Docker is required for the acceptance harness, not for creators publishing to the platform.

```bash
python3 -m unittest identity.tests.test_database_http
python3 -m unittest discover -s identity/tests -p 'test_*.py'
python3 -m unittest discover -s infra/tests -p 'test_*_cli.py'
python3 -m unittest discover -s probes/hosting/fixture -p 'test_*.py'
npx --yes pyright@1.1.413 --pythonpath "$(command -v python3)"
```

These are local regression results. Google identity uses the existing signed-token fixture; database transport uses loopback without TLS; app containers use Docker host networking. Cloud build provisioning, gVisor, production readiness timing, runtime promotion commands and EU hosting are not revalidated by this adapter. No production deployment or destructive hosted-schema experiment was performed for this increment. Existing infrastructure evidence remains in the [foundation report](hosting-foundation-2026-09-08.md).

[Creator guidance](../../identity/REDEPLOYMENT.md) explains compatible migrations, creator-led schema repair and explicit reset as a future recovery option under #13. No automatic schema rollback, backup guarantee, migration runner or reset implementation is claimed.
