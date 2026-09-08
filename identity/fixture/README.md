# Publishing acceptance app

Deploy this directory through the creator CLI, with no local Docker:

```bash
small-cloud deploy identity/fixture --name publishing-probe --description 'Disposable publishing acceptance probe' --wait
```

Open the returned app URL and complete Google sign-in. `/` and `/identity` return only the three trusted gateway identity headers; name and email remain their unpadded base64url wire encoding. The internal `/_small-cloud/ready` endpoint succeeds for the readiness probe and must return 404 through the public gateway.

`/network` checks the fixed source-controlled destinations in `targets.json`, with two-second socket timeouts and a 2.5-second aggregate deadline. It accepts no caller-supplied addresses and never renders environment variables, database credentials or provider errors. Public HTTPS should connect; metadata and private SSH should fail. A failure alone is not proof of isolation: the operator must independently verify the control/runtime SSH listeners are reachable from their permitted source. A `timeout` is inconclusive. Customize public management address probes only by editing `targets.json` before redeploying; never put credentials in that file.

The image uses the hosting fixture's existing pinned Python 3.12 image, no package downloads, and UID/GID 65532. This fixture does not initialize or exercise the app database and stores no durable data.
