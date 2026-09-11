# Workspace CLI release — 2026-09-11

Version **v0.3.1**, tagged at `3cb50ed`, is published through the [public installer](https://small-cloud.monkeysees.one/cli/install.sh), versioned downloads and `latest`. The hosted identity service also runs 0.3.1. [Redacted evidence](../evidence/cli-workspaces-2026-09-11.json) records artifact hashes, native credential-storage acceptance, public installation and hosted checks.

## Release verification

The [native release workflow](https://github.com/monkeysees/small-cloud/actions/runs/34578255649) passed on Linux and macOS, each on ARM64 and x86-64. Production executables passed installed discovery, file credential fallback, native OS credential storage, frozen HTTPS authentication, split login and installer-integrity checks. Only production binaries, checksums and the installer were published.

The [public installation workflow](https://github.com/monkeysees/small-cloud/actions/runs/34578917104) then passed on all four native targets using actual HTTPS downloads without a source checkout or Python setup. All eight versioned asset/checksum URLs matched the verified artifacts, and all four `latest` checksum aliases matched v0.3.1.

The actual public installer also succeeded on this glibc 2.36 workstation. Its installed executable reported `small-cloud 0.3.1`, retained the existing operator credential, and created a temporary workspace whose owner immediately had member, creator and administrator roles. Matching retries returned the same workspace, explicit targeting worked, and the existing first-workspace default remained unchanged. The temporary workspace and its receipt were removed afterward.

## Compatibility correction

The initial v0.3.0 build passed on Ubuntu 24.04 but failed this workstation's direct installation check: its Linux x86-64 binary required `GLIBC_2.38`. The installer failed before replacing an existing executable. The public `latest` link was restored to v0.2.0, and v0.3.0 was marked as a prerelease. Its published bytes were not overwritten.

Version v0.3.1 builds and verifies Linux x86-64 on Ubuntu 22.04, targeting glibc 2.35. Linux ARM64 remains tested on Ubuntu 24.04. The corrected x86-64 artifact passed directly on this workstation before `latest` moved to v0.3.1.

## Hosted upgrade and cleanup

The service upgrade retained the admin's credential and saved default. Its pinned `certifi` dependency was installed, and `pip check` passed. New workspace owners receive creator privileges automatically; additional ordinary administrators still require separate creator grants. These grants count toward installation creator capacity.

Preflight identified one catalog entry left by the earlier requested user deletion: the removed creator's disabled, stopped acceptance app had no membership and would fail startup validation. Its catalog entry and a control-state snapshot were archived under the root-only `/srv/small-cloud/operator-archives/deleted-users-2026-09-11` directory. The entry was removed from the active app catalog; its PostgreSQL database and retained data were preserved. An initial upgrade attempt failed preflight and restored the previous package; retrying after closing the operator database connection succeeded.

Final inventory is one user (the existing platform administrator), one workspace, two catalogued apps and all three preserved app databases. The admin's running app remains running. The identity service is active; publishing, lifecycle and diagnostics retain their original stopped states. This release did not create cloud builders or run new app builds.

The [earlier hosted workspace acceptance](workspaces-hosted-2026-09-11.md) covers real cloud builds and database isolation. Its owner-role expectations describe the earlier policy and are superseded by this release. Fresh human Google approval and rendered-browser checks remain the manual checks recorded there; native release fixtures do not substitute for those observations.

## Worker activation follow-up — 2026-09-11

At the user's request, diagnostics, lifecycle and publishing were started and left active. All four services, including identity, are enabled for boot and remained running with zero restarts during verification. The runtime host connected to the forwarded diagnostics socket. An authenticated request to an existing idle app progressed from HTTP 503 startup responses to HTTP 200, verifying lifecycle startup and runtime reachability. No new cloud builds were submitted. [Worker evidence](../evidence/workers-ready-2026-09-11.json) records this later state, superseding the stopped-worker inventory above. The [publishing runbook](../../identity/PUBLISHING.md#keep-the-hosted-workers-running) now requires explicitly restarting dependent workers after identity upgrades.
