# Explicit CLI update release acceptance — September 13

Issue #43 is accepted. v0.7.1 is published for Linux x86-64/ARM64 and macOS Intel/Apple Silicon, and the public `latest` link points to that release. All four platforms passed both native credential modes and independent public installation/update/no-update acceptance. No #43 acceptance item remains pending.

Implementation `f9ba163`, release preparation `bd5ab22`, and macOS test correction `785304f` are pushed on `main`. v0.7.1 is built from `785304fd4f26e65d64ebd6cc7f881bcca5f3cca0`. Tags v0.7.0 and v0.7.1 are retained without rewriting history; v0.7.0 was not published. See the [local implementation report](cli-update-2026-09-11.md) for source tests and independent review, and the [release evidence](../evidence/cli-update-release-2026-09-13.json) for exact artifact hashes and acceptance records.

## Native and public acceptance

The successful second attempt of the [v0.7.1 native workflow](https://github.com/monkeysees/small-cloud/actions/runs/34732254382) passed all four targets. Each target passed 42 frozen tests in file-credential mode and another 42 with native OS credential storage: 336 test passes, plus 14 installed-production checks per target/mode and installer integrity checks.

| Target | Native file credentials | Native OS credentials | Public install | Public update/no-update |
| --- | --- | --- | --- | --- |
| Ubuntu 22.04 x86-64 | Passed | Passed | Passed | Passed |
| Ubuntu 24.04 ARM64 | Passed | Passed | Passed | Passed |
| macOS 15 Intel | Passed | Passed | Passed | Passed |
| macOS 15 Apple Silicon | Passed | Passed | Passed | Passed |

The installed update suite covers executable replacement, matching-byte inode preservation, human/JSON outcomes, corrupt/nonexecutable/failing/older candidates, unavailable/redirected/truncated downloads, the real two-minute slow-header deadline, interruption, custom symlinks, unwritable installation directories, source-install refusal, and offline discovery. Failure cases preserve a usable executable. The same frozen runs retain login, credential, app preparation and deployment completion/recovery coverage.

The [public acceptance workflow](https://github.com/monkeysees/small-cloud/actions/runs/34734926737) first installed each pinned v0.7.1 artifact directly over HTTPS before checkout or Python setup. Help, version, catalog, guides and local app checks ran with no Python on PATH; installation did not log in or alter shell files.

It then built an undistributed fixture and exercised real public HTTPS replacement. The updated executable's bytes matched the independently installed production artifact. That production executable passed JSON and human `already_current` checks while preserving inode/mtime, shell files and state markers. This same-version fixture-to-production check proves actual public artifact replacement; controlled native tests separately prove advancement to a newer version. The fixture was never uploaded, and production exposes no endpoint override.

## Publication and workstation verification

Only successful production artifacts and their checksums were uploaded to a new `/srv/small-cloud/cli/releases/v0.7.1` directory. Local and remote hashes matched; all eight pinned HTTPS URLs passed verification before the `latest` symlink was atomically advanced from v0.6.0. All four latest checksum URLs then matched. The previous v0.6.0 directory remains available. Service readiness was true and maintenance false before and after publication; no backend service or hosted app was changed.

The workstation ran the real public installer into a temporary directory and verified v0.7.1, retained-credential authentication, human/JSON no-update, catalog and updating guide with no Python on PATH. The existing credential's bytes and permissions and the user's shell files were unchanged; the temporary installation was removed.

An existing unpublished development fixture containing the updater also advanced from 0.6.0 to the exact public v0.7.1 bytes over HTTPS, then passed no-update checks. This fixture was not the previously published v0.6.0 executable. Public v0.6.0 and earlier lack `update`; rerun the installer once to bootstrap v0.7.1, then use `small-cloud update` for future releases.

## Earlier attempts and resolution

The [v0.7.0 run](https://github.com/monkeysees/small-cloud/actions/runs/34731758639) was cancelled after Apple Silicon passed 41 of 42 frozen tests but failed a source-install preservation assertion: executing Python changed its access timestamp. The corrected test compares exact bytes, inode, modification time and mode, excluding normal read access time. Its focused local test, Pyright, workflow lint and independent review passed. Production updater behavior did not change in that correction.

The first v0.7.1 attempt was refused before any job steps because GitHub reported an account payments/spending-limit blocker. The operator made the repository public; rerunning the same workflow then executed and passed all four native targets. No billing limit was changed by this task. The historical failed-attempt evidence is retained alongside the successful retry.

## Scope remaining elsewhere

The broader human/fresh-agent journey acceptance remains in #45. Its other open prerequisites include secrets/sharing, destructive commands, project linking, streaming logs, workspace controls and shell completion. This release completes #43 and does not establish those unfinished journeys or alter parent specification #29.
