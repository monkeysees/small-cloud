# App preparation acceptance — 2026-09-11

Issue [#33](https://github.com/monkeysees/small-cloud/issues/33), from specification #29, is implemented and accepted. Version **v0.4.0**, tagged at `063e9cc`, is published through the public installer, versioned downloads and `latest`. [Redacted evidence](../evidence/app-preparation-2026-09-11.json) records the native results, public installation and artifact hashes. The user delegated completion of acceptance and shipping to the agent; no additional human walkthrough is claimed.

## Behavior and local acceptance

`small-cloud guide runtime` explains remote Dockerfile builds, the HTTP port/readiness contract, database TLS and initialization, runtime secrets, disposable data, and source exclusions. `small-cloud app check FOLDER` exposes the existing source-packaging boundary without authentication, an app/workspace target, local Docker, file generation, upload or build allowance consumption.

Human and JSON results report included/excluded paths, uncompressed bytes, limits, source rules and local/remote verification boundaries. Success explicitly disclaims remote build feasibility and readiness. Rejections retain `UPLOAD_REJECTED` (exit 2), explain the source problem and point to the bundled repair guide. No partial manifest is presented as valid and no file contents are displayed.

All **219 tests** passed for the implementation: 126 identity, 89 infrastructure and 4 probe tests. Pyright reported no errors. Independent Standards and Spec reviews found no issues in either the implementation or release-testing follow-up. The identity suite emitted one socket ResourceWarning without a test failure.

The five app-preparation CLI tests cover valid/invalid source, mandatory exclusions surviving negation, platform-storage overlap, symlinks, hardlinks, special files, byte/file-count limits, invalid ignore patterns, safe terminal rendering, guide examples and equivalence with deploy dry run. A listening endpoint observes no connection during checking. Tests also verify unchanged source and absent credential/config writes. An invalid Dockerfile instruction is deliberately accepted as source while the result disclaims build validation.

Installed-wheel checks passed outside the checkout. The initial standalone build lacked the shared Python library; rebuilding with the existing extracted Debian library succeeded, and all five preparation tests passed against the frozen executable. The test harness resolves temporary paths for macOS and supports the same frozen fixture launcher used by release acceptance.

## Native and public release acceptance

The [native release workflow](https://github.com/monkeysees/small-cloud/actions/runs/34589727031) passed on Linux and macOS, each on ARM64 and x86-64. Every target passed installed human/JSON preparation checks and the full preparation suite through the frozen fixture, alongside file/native credential storage, HTTPS authentication, split login and installer integrity checks. The Linux x86-64 build retains Ubuntu 22.04/glibc 2.35 compatibility.

All eight public binary/checksum URLs matched the verified release artifacts. Only production binaries and checksums were uploaded; the existing public installer matched the repository bytes. The `latest` symlink moved atomically from v0.3.1 to v0.4.0. The [public installation workflow](https://github.com/monkeysees/small-cloud/actions/runs/34590365825) then passed on all four targets using actual HTTPS downloads, including runtime guidance and source checks without Python or Docker on PATH.

On the workstation, the real HTTPS installer succeeded into an isolated temporary directory. The installed executable passed the five preparation tests, checked the existing HTTP/database fixture, and performed read-only hosted authentication using the retained credential. Its saved credential file stayed byte-identical. Installation did not log in or change shell startup files; the temporary installation was removed afterward.

The hosted service passed readiness checks. Publishing the static CLI assets required no identity-service upgrade or restart and no cloud app build. Existing apps, databases, workspaces, secrets and saved defaults were preserved. This acceptance establishes #33's offline preparation behavior; it does not assert remote build feasibility for checked source or complete the broader fresh-agent journeys in #45, which retains other open prerequisites.
