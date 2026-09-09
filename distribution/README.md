# Standalone CLI distribution

Small Cloud runs without a Python installation or source checkout. The native executable bundles the repository's Python 3.11 runtime and pinned runtime dependencies using PyInstaller. The CLI always connects to `https://small-cloud.monkeysees.one`; installation and login are separate.

## Install and sign in

Version 0.1.0 is published and verified on all four supported targets; see the [acceptance record](../docs/acceptance/cli-distribution-2026-09-09.md).

```sh
curl --fail --silent --show-error --proto '=https' https://small-cloud.monkeysees.one/cli/install.sh | sh
```

The installer selects your OS and architecture, downloads the executable over HTTPS, verifies its SHA-256 checksum, checks that it starts, and atomically installs `~/.local/bin/small-cloud`. It requires `curl` plus `sha256sum` (Linux) or `shasum` (macOS). A failed download, checksum or startup check preserves the existing installation. Installation never starts login or edits shell startup files. If the directory is missing from PATH, the installer explains the required change. For Bash or Zsh, add this yourself to your shell configuration and open a new terminal:

```sh
export PATH="$HOME/.local/bin:$PATH"
small-cloud --help
small-cloud auth login
```

In Fish, use `fish_add_path "$HOME/.local/bin"`. Login requires human Google browser approval; compare the displayed code before approving. `small-cloud auth login --no-browser` prints the approval link for manual opening. Existing hosted-service credentials remain usable at their original location. Endpoint flags are rejected, and old endpoint environment variables and configuration are ignored.

To select an existing release and another absolute install directory:

```sh
curl --fail --silent --show-error --proto '=https' https://small-cloud.monkeysees.one/cli/install.sh | SMALL_CLOUD_VERSION=v0.1.0 SMALL_CLOUD_INSTALL_DIR="$HOME/bin" sh
```

Ordinary CLI commands do not update the executable. Rerunning the installer explicitly replaces it; the dedicated update command and completion generators belong to later #29 tickets.

## Standalone downloads

Download the executable and matching `.sha256` file from `https://small-cloud.monkeysees.one/cli/releases/VERSION/`, replacing `VERSION` with a published tag or `latest`:

| System | Architecture | Executable | Minimum supported OS |
| --- | --- | --- | --- |
| Linux | x86-64 | `small-cloud-linux-x86_64` | Ubuntu 24.04 / glibc 2.39 |
| Linux | ARM64 | `small-cloud-linux-arm64` | Ubuntu 24.04 / glibc 2.39 |
| macOS | Intel x86-64 | `small-cloud-macos-x86_64` | macOS 15 |
| macOS | Apple Silicon ARM64 | `small-cloud-macos-arm64` | macOS 15 |

Verify the downloaded checksum (`sha256sum -c FILE.sha256` or `shasum -a 256 -c FILE.sha256`), rename the executable to `small-cloud`, and `chmod +x small-cloud` before placing it on PATH. Linux requires glibc and system CA certificates; musl/Alpine and native Windows are unsupported. PyInstaller performs ad-hoc signing on macOS; releases are not Developer ID signed or notarized. Browser-downloaded macOS files can require explicit approval in System Settings → Privacy & Security. No installer step disables Gatekeeper or removes quarantine.

Native macOS Keychain and Linux Secret Service support, including their Python dependencies, are bundled. Linux desktop Secret Service requires the OS session's D-Bus/keyring service; headless systems use the existing owner-only file fallback. A locked available native store still fails instead of silently writing plaintext. Credential files and lock behavior retain the existing protection and exact-origin rules. Public HTTPS trust includes a bundled Mozilla CA set from certifi, so the executable does not depend on its build machine's certificate paths; system trust remains available as well.

## Build and acceptance

Use the repository's Python/pip tooling, in a build environment outside the checkout:

```sh
python3 -m venv /tmp/small-cloud-build
OPENSSL_STATIC=1 /tmp/small-cloud-build/bin/python -m pip install --no-cache-dir . -r distribution/requirements.txt
/tmp/small-cloud-build/bin/python distribution/build.py
/tmp/small-cloud-build/bin/python distribution/build.py --fixture
/tmp/small-cloud-build/bin/python distribution/verify.py build/release/small-cloud-linux-x86_64 build/release/small-cloud-fixture
```

Substitute the native target filename on other systems. Linux builders need a shared `libpython3.11`; Debian packages it separately as `libpython3.11`. Output is in ignored `build/release/`. PyInstaller is a native packager, not a cross compiler: [upstream usage](https://pyinstaller.org/en/latest/usage.html) and [architecture/signing notes](https://pyinstaller.org/en/stable/feature-notes.html). Dependency review on 2026-09-09: PyInstaller 6.22.2 and its 2026.7 community hooks are maintained upstream (latest repository push September 6, over 13,000 stars); they are build-only dependencies, pinned in `requirements.txt`. Runtime remains Python with the existing pinned keyring/PyJWT dependencies.

The [native workflow](../.github/workflows/cli-release.yml) uses four GitHub-hosted runners. It installs each production binary outside the checkout, checks offline help/catalog/guides, rejects endpoint flags, ignores environment/config endpoint overrides, and verifies installer checksum failure preserves the previous binary. It also makes a hosted authentication-status request using an invalid synthetic credential and unavailable system CA paths: the expected authentication refusal proves bundled public TLS trust without a real credential or hosted mutation. A separate frozen fixture executable exercises actual browser-protocol login, retained credentials, exact-origin refusal and logout against the existing signed-provider HTTPS harness. Both file fallback and native OS keyring roundtrips must pass per target. Installer tests supply local build bytes at the HTTPS-download boundary; published installation needs an additional real download check. The harness uses Python to operate the test service; the executable contains its own runtime.

CA dependency review on 2026-09-09: [certifi 2026.7.22](https://pypi.org/project/certifi/) is the established Requests ecosystem's Mozilla CA bundle, maintained at [certifi/python-certifi](https://github.com/certifi/python-certifi) (latest push August 25). Pinning it makes bundled trust reviewable; refresh it deliberately with CLI releases.

Release builds also pin the existing transitive cryptography dependency to 50.0.1. Where upstream provides a wheel, its OpenSSL is already static. Intel macOS currently builds it from source and needs Rust plus Homebrew OpenSSL headers/static libraries; `OPENSSL_STATIC=1` prevents a collision between Homebrew's OpenSSL and frozen Python's OpenSSL. See [upstream build instructions](https://cryptography.io/en/latest/installation/). These are maintainer build prerequisites only. Native macOS acceptance creates an unlocked disposable Keychain in the runner; its test credentials are never exported.

Production calls `identity.cli.main()` with its fixed default. Source tests call the same function through `identity/tests/cli.py`, supplying the isolated origin as an internal Python argument. The frozen fixture uses that test launcher; it is never uploaded by the release workflow. Production has no environment/flag/config path to that argument, and `identity.tests` is excluded from wheels and frozen imports.

## Operator publication

The source repository is private. Native CI artifacts and draft GitHub releases stay private; public downloads expose only the four verified production binaries, their checksums and the installer, not the source or fixture executable.

Dispatch `Standalone CLI` to build and verify the current branch. A `v*` tag runs the same checks and creates a draft GitHub release only after all four targets pass. Before tagging, ensure the tag matches the version in `pyproject.toml` and `identity/commands.py`. Keep both per-target acceptance JSON files with the release evidence.

On the existing control host, merge [the static-download fragment](Caddyfile.fragment) into the management site, preserving its TLS, logging, authentication and app routing. Validate the complete Caddyfile before restarting Caddy (this installation has `admin off`). Upload verified production files into a new `/srv/small-cloud/cli/releases/VERSION` directory, readable by Caddy. Never reuse a published version with different bytes. Install `install.sh` at `/srv/small-cloud/cli/install.sh`, then atomically replace the `releases/latest` symlink with the verified version. Do not expose a fixture executable or release evidence containing credentials. The download route is intentionally unauthenticated and has no directory browsing.

Verify all eight public asset/checksum URLs and execute the real one-command installer into a temporary directory. Run its installed binary's help and hosted `auth status` using retained credentials, then remove only that temporary installation. Preserve the current `latest` link if any target fails acceptance.

After publication, dispatch [Published CLI installation](../.github/workflows/cli-installation.yml) with the released version. It verifies the real HTTPS installer on all four native targets without a source checkout or Python setup, including unchanged shell files and installation without login. Keep those results with the native build evidence before marking a release accepted.
