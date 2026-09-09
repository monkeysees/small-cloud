# CLI distribution acceptance — 2026-09-09

Acceptance for [#31](https://github.com/monkeysees/small-cloud/issues/31) is complete. Version `v0.1.0`, tagged at `4419e01`, is available through the [public installer](https://small-cloud.monkeysees.one/cli/install.sh) and versioned standalone downloads. The source repository remains private. [Machine-readable evidence](../evidence/cli-distribution-2026-09-09.json) records artifact hashes and results.

## Four native targets

The [tagged release workflow](https://github.com/monkeysees/small-cloud/actions/runs/34371563986) built and verified all four artifacts, then created the release assets. The independent [public-installation workflow](https://github.com/monkeysees/small-cloud/actions/runs/34372352212) installed those published downloads on fresh runners without checking out the source or setting up Python.

| Target | Native build and installed executable | File credentials | Native OS credentials | Public installation |
| --- | --- | --- | --- | --- |
| Ubuntu 24.04 x86-64 | Passed | Passed | Secret Service passed | Passed |
| Ubuntu 24.04 ARM64 | Passed | Passed | Secret Service passed | Passed |
| macOS 15 Intel | Passed | Passed | Keychain passed | Passed |
| macOS 15 Apple Silicon | Passed | Passed | Keychain passed | Passed |

Each native build passed nine installed-executable checks covering bare invocation, help, version, catalog, bundled guide, unauthenticated status, both removed endpoint-flag forms, and hosted HTTPS with unavailable system CA paths. Old endpoint environment/configuration values and the fixture-origin variable did not redirect the production executable. A synthetic invalid credential received the hosted service's authentication refusal, establishing verified public TLS without a real credential or mutation.

The separate frozen fixture executable completed signed-provider HTTPS browser approval, credential saving and reuse, exact-origin metadata refusal, and revocation/removal on logout. File storage retained 0600 permissions. Linux used a real D-Bus/Secret Service session; macOS used an unlocked disposable Keychain and the runner's real OS account home, with Small Cloud state/configuration isolated in temporary directories. The fixture executable was excluded from release assets and public downloads.

## Published installation and retained credentials

The public installer and all eight versioned executable/checksum URLs matched their release artifacts byte-for-byte. Four `latest` checksum aliases matched as well. Directory browsing, the fixture executable and internal acceptance JSON were unavailable (404): 16 public URL/content checks passed.

All four fresh native runners installed from the real HTTPS URL, exercised help/version/catalog/guides with no programs on PATH, and received the expected unauthenticated status. Installation created no credential state and left shell startup files unchanged. The native build tests additionally verified that a corrupt download preserves the existing installation and that a missing PATH entry is explained.

A separate Ubuntu 24.04 container with neither Python nor Python 3 installed passed both `latest` and explicitly pinned `v0.1.0` installation. Its installed binary reused the workstation's retained hosted credential for authentication status and the app directory. The temporary protected credential copy was removed automatically. No new Google approval, hosted app mutation, build, sharing change, secret change or credential revocation was needed for those reads.

The operator published only the installer, four production binaries and four checksums under the existing control host's `/cli/` route. Caddy configuration validation passed before activation; Caddy and identity services remained healthy afterward. Versioned files are retained at `/cli/releases/v0.1.0/`, with `latest` pointing to that version. The previous management fragment is retained as a rollback copy. Existing authentication and app routing were preserved.

## Regression verification and portability fixes

The final regression run passed all 86 identity tests in 317.369 seconds, all 89 infrastructure tests and all four hosting-fixture tests, with no skips. Production and distribution-script typechecking, workflow `actionlint` and installer shell syntax checks passed. Independent Standards and Spec reviews found no remaining implementation defects or acceptance gaps after the native and public checks completed.

Native testing resolved three portability problems: macOS temporary paths use a `/var` symlink, so fixtures canonicalize their temporary homes without weakening credential guards; native Keychain tests must retain the real OS account home; and Intel macOS cryptography source builds need static OpenSSL linkage to avoid colliding with frozen Python's OpenSSL. The bundled certifi CA set separately removed dependence on build-machine certificate paths. Release asset collection was also corrected to match GitHub's artifact directory layout.

This completes #31's standalone-distribution and fixed-service scope. Dedicated updates, completion, split login, other CLI journeys and the broader human/fresh-agent trials remain their separate #29 implementation tickets. macOS executables are ad-hoc signed, not Developer ID signed or notarized; the documented browser-download approval behavior remains applicable.
