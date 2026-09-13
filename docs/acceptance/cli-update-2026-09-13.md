# CLI update shipping follow-up — September 13

Source shipping is complete for #43: implementation `f9ba163`, release preparation `bd5ab22`, and the macOS test correction `785304f` are pushed on `main`. Tags v0.7.0 and v0.7.1 are retained without rewriting history. No new CLI release is published; public `latest` remains v0.6.0.

## Native attempt and correction

The [v0.7.0 run](https://github.com/monkeysees/small-cloud/actions/runs/34731758639) built all four native targets. Apple Silicon ran 42 frozen tests: 41 passed, and the source-install preservation assertion failed because executing Python changed its access timestamp. Its bytes and modification/creation times were not reported changed. The updater replacement, no-update, failure preservation and deadline cases passed there. Linux ARM64 completed its file-credential pass and reached native credential verification before the run was cancelled to avoid continuing a failed release gate.

The corrected test compares exact bytes, inode, modification time and mode; normal reads may change access time. Its focused local test, Pyright and workflow lint passed, and independent review found no issue with the correction. v0.7.1 contains that test correction; production updater behavior is unchanged.

## Current blocker

GitHub refused to start every native job in the [v0.7.1 run](https://github.com/monkeysees/small-cloud/actions/runs/34732254382). Each job has no executed steps. Its annotation says: “The job was not started because recent account payments have failed or your spending limit needs to be increased.” This identifies an account billing/spending-limit blocker; it does not identify which account setting is responsible. No code failure was observed in that run.

The public download host was checked read-only: `latest` is v0.6.0, the planned release directory was absent, and identity, diagnostics, lifecycle and publishing were active. Publication scripts were prepared but never executed. No backend service, hosted app, credential or published download was changed.

## Remaining acceptance

1. Restore GitHub Actions billing/spending access and rerun `34732254382`; all four native targets must pass both file and native OS credential modes with the update suite.
2. Download only successful production artifacts, verify checksums, publish a new v0.7.1 directory, verify all eight public URLs, and atomically switch `latest`. Retain v0.6.0.
3. Dispatch `Published CLI installation` at ref `v0.7.1` with `version=v0.7.1`. The workflow first verifies source-free/Python-free public installation, then builds an undistributed fixture to test real public HTTPS replacement and JSON/human no-update through the resulting production executable on all four platforms. It never uploads the fixture. The selected version must match public `latest`.
4. Verify the workstation's retained credential and shell files remain unchanged, record final evidence, update the release notes and close #43. The existing unpublished 0.6.0 fixture can also prove a real version advance to public v0.7.1; public v0.6.0 itself requires installer bootstrap because it lacks `update`.

The broader human/fresh-agent journey acceptance belongs to #45 and remains separate. [Local implementation evidence](cli-update-2026-09-11.md) remains valid; [release attempt evidence](../evidence/cli-update-release-2026-09-13.json) records the blocker.
