# App idle lifecycle acceptance — 2026-09-09

Issue [#9](https://github.com/monkeysees/small-cloud/issues/9), against specification [#1](https://github.com/monkeysees/small-cloud/issues/1). Implementation `f550a3c` adds authenticated idle stopping, retained-release startup, shared active-capacity reservations, loading/retry responses and worker recovery.

## Local verification

All 164 tests passed: 72 identity tests, 88 infrastructure CLI tests and four hosting-fixture tests. Pyright 1.1.413 reported zero errors. Standards and Spec reviews had no remaining findings after moving request-framing validation before startup reservation.

The tests cover the exact deterministic 30-minute boundary, forwarded versus denied requests, in-flight protection, competing starts, publication sharing the active limit, database persistence, browser sign-in while stopped, explicit failure retry and interrupted-worker cleanup. The gateway/CLI runs against the real identity implementation; Google and infrastructure use controlled fixtures. The database acceptance uses real PostgreSQL and the actual starter.

## Hosted execution

The reviewed commit was pushed and installed on the permanent German control/runtime hosts. The new lifecycle service runs independently of publishing. Existing app routing and selected deployments were unchanged. A temporary shared-lock guard protects only the two pre-existing apps from this acceptance's idle experiments; it is removed after cleanup.

Four dedicated `lifecycle-acceptance-9-*` apps were published through the creator CLI using four fresh CPX22 builders in Nuremberg. The fixture adds authenticated controls for a one-shot failed or delayed startup, plus a temporary file and process identifier. It stores those startup controls in its own PostgreSQL database; consuming the failure flag before exiting permits a real explicit retry without changing production runtime state by hand.

App A tests an untouched 30-minute interval after an authenticated write. Separate acceptance apps use explicitly recorded `last_http` adjustments to reach the idle boundary promptly for capacity and recovery scenarios. Those adjustments never target the pre-existing apps or App A's natural-idle interval.

The live full-workspace check returned HTTP 503 with the capacity message and Retry button at five active apps. A deliberate one-shot startup failure used the production 120-second readiness timeout, released its slot after cleanup and recovered through explicit retry with its saved row intact. Killing the lifecycle worker during startup left all five reservations counted; the restarted worker removed the uncertain allocation before releasing the slot, and a subsequent request restored the app and its data.

App A remained running at 1,799 seconds, was observed stopping at 1,801 seconds and was confirmed stopped at 1,803 seconds. Its `last_http` value stayed unchanged throughout, despite repeated denied requests and management observations. Two cold apps then competed for the freed slot: A received `STARTING`, while C received `ACTIVE_CAPACITY` in approximately 155 ms. Active usage remained five, and actively requested apps B and D kept serving. C started after another dedicated app idled and freed capacity.

After wake-up, A retained its exact database row and selected deployment ID. Its process identifier changed and its temporary file was absent. Authenticated HTML returned the loading page with `Retry-After: 2`; capacity and failure pages included Retry without automatic refresh. Malformed framing and real WebSocket upgrade requests returned 400, foreign-origin mutations returned 403, unauthenticated JSON returned 401 and unauthenticated HTML redirected to Google with a secure host-bound flow cookie. These denied requests did not wake the stopped app.

A second interruption probe confirmed the new gVisor container was actually running while its product state was still `starting`, killed the lifecycle worker, observed all five reservations still counted, and then verified the container was absent before its slot was released. Retrying preserved the saved database row. A separate runtime inspection confirmed five physical running gVisor app containers at full capacity. Installed source hashes match the pushed commit on both hosts.

The [hosted evidence](../evidence/app-lifecycle-2026-09-09.json) records the observations and final inventory. Live HTTP/CLI checks are complete; the rendered-browser boundary below remains open.

## Cleanup and retained state

Removed all four acceptance apps, containers, PostgreSQL databases/roles, encrypted database credentials, source staging, diagnostic/request/session records and temporary deployment staging. Their authenticated URLs return 404. Registry/runtime image references were retired for the existing janitors; the normal grace period still applies to physical image removal. All four build VMs and their addresses were deleted, and final provider inventory contains only the two permanent hosts and their two addresses.

The four real builds charged **43 seconds**, retained in the allowance ledger. Wake-ups and recovery added no build charges. Final usage is two deployed apps, one active app, 777 charged seconds and zero reserved seconds.

Both pre-existing containers retained their exact IDs and start times throughout acceptance, and their selected deployments and sharing scopes remain unchanged. The temporary preservation guard was removed. `publishing-probe` returns authenticated HTTP 200 and remains running; the other creator's private `sharing-acceptance-7` still returns 404 to the administrator and has now stopped under the normal idle policy. Its release and database remain retained. Identity, publishing, diagnostics, lifecycle and Caddy services are active, as are the cleanup timers.

## Browser evidence boundary

Authenticated live HTML and HTTP response checks use the retained creator credential. This session has no callable Chrome plugin, MCPorter/OpenClaw executable or reachable local Chrome debugging endpoint. No isolated browser was substituted; explicit authorization was requested and remains pending. Rendered-browser verification and a fresh hosted Google browser sign-in therefore remain unverified; local tests cover the browser handoff and response behavior. Issue #9 remains open rather than claiming this last requested acceptance check was completed.

## Operator and creator guidance

The [lifecycle guide](../../identity/LIFECYCLE.md) describes idle timing, loading delays, five-slot capacity, explicit retry, database/temporary-state behavior and service installation/recovery. Startup failure releases a slot only after confirmed cleanup; a lost worker cannot release capacity merely because its process disappeared.
