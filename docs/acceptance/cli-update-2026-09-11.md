# Explicit CLI updates — #43

Implementation `f9ba163` is based on `55066d900c3777af301551b1171ec7b29202cd4f`. This report preserves the local development evidence. v0.7.1 subsequently passed native and public acceptance on all four targets and is published as `latest`; see the [September 13 release acceptance](cli-update-2026-09-13.md). Public v0.6.0 artifacts remain available unchanged and require installer bootstrap because they do not contain `update`.

## Delivered behavior

`small-cloud update` and `small-cloud update --json --no-input` download the official latest native executable and SHA-256 checksum over HTTPS. A matching installed checksum returns `already_current` without rewriting the file. Otherwise, the command stages the download in the installation directory, verifies its checksum and startup/version, then atomically replaces the resolved executable. Custom directories and symlinks are supported. Older versions are refused; differing bytes with the same version are reinstalled.

Human and JSON outcomes include installed/resulting versions and recovery guidance. Interrupted updates report an unknown resulting version and direct the caller to inspect `--version`. Network, integrity and startup failures leave the previous executable usable. Source/Python installations are refused before download or mutation. Ordinary commands never check for updates; update does not read credentials, initiate login or modify shell startup files.

Help, the shared command catalog, bundled `updating` guide, distribution instructions, CLI contract and changelog document the behavior. No new dependency was added.

## Local verification

Tests use the agreed executable/subprocess boundary and a controlled HTTPS artifact service. The undistributed launcher alone supplies the fixture origin and source-test executable path; production exposes no override. Each update fixture verifies unchanged shell files and absence of credential/configuration state.

- Source CLI checks cover human/JSON replacement, current-release inode preservation, corrupt/nonexecutable/failing/older candidates, unavailable/redirected/truncated downloads, interruption, custom symlinks, source-install refusal and offline discovery.
- Linux x86-64 production and fixture executables were rebuilt using the pinned PyInstaller 6.22.2 toolchain. The installed frozen fixture successfully replaced itself with the real production artifact, whose version/help/catalog then ran with no Python on PATH.
- The native update checks also exercise usable-executable preservation, no-update behavior, interruption and custom paths. A separate slow-header run tests the actual two-minute deadline, beyond the source test's accelerated OS signal.
- The full identity suite ran 155 tests in 855.416 seconds: 154 passed and the native-only artifact case was skipped, then covered by installed acceptance. Three additional source regressions added during review passed separately. Together with the 89 infrastructure and 4 hosting-probe tests, 250 source/infrastructure/probe cases passed. Five discovery checks also passed after review.
- All 11 update cases passed through the native-artifact harness across the installed suite and focused deadline/directory-permission runs. The real slow-header deadline check completed in 120.973 seconds including fixture setup/cleanup. Pyright reports zero errors or warnings.
- Standards review found a slow-header deadline gap; Spec review found omitted human failure versions. Both were reproduced, fixed and cleared in independent follow-up reviews. There are no remaining implementation findings.

This workstation uses Linux x86-64 with glibc 2.36. These builds establish local native execution, not the Ubuntu 22.04 minimum-version acceptance or another platform's compatibility. Build files are ignored and have not replaced any published version. Artifact hashes and final regression results are recorded in the [evidence file](../evidence/cli-update-2026-09-11.json).

## Subsequent release acceptance

The `Standalone CLI` workflow calls `distribution/verify.py` on Ubuntu 22.04 x86-64, Ubuntu 24.04 ARM64, macOS Intel and macOS ARM64. Its verifier includes the update suite, including replacement with each target's real production artifact. On September 13, a macOS access-time assertion was corrected, and making the repository public resolved the subsequent Actions execution blocker.

All four v0.7.1 targets passed both credential modes and the public installation/update/no-update workflow. Verified artifacts were published without changing backend services, and workstation acceptance preserved existing credentials and shell files. The [release report](cli-update-2026-09-13.md) and [release evidence](../evidence/cli-update-release-2026-09-13.json) complete #43's acceptance; broader human/fresh-agent journeys remain in #45.
