#!/bin/sh
# Install an official release without changing shell configuration or signing in.
set -eu

fail() { echo "small-cloud installer: $*" >&2; exit 1; }
version=${SMALL_CLOUD_VERSION:-latest}
destination=${SMALL_CLOUD_INSTALL_DIR:-"$HOME/.local/bin"}
case "$version" in
    latest) release=latest ;;
    v[0-9]*)
        case "$version" in *[!a-zA-Z0-9._-]*) fail 'Invalid release version.' ;; esac
        release="$version" ;;
    *) fail 'Use latest or a release tag such as v0.1.0.' ;;
esac
case "$destination" in /*) ;; *) fail 'SMALL_CLOUD_INSTALL_DIR must be absolute.' ;; esac
case "$(uname -s)" in Linux) system=linux ;; Darwin) system=macos ;; *) fail 'Supported systems: Linux and macOS.' ;; esac
case "$(uname -m)" in x86_64|amd64) arch=x86_64 ;; arm64|aarch64) arch=arm64 ;; *) fail 'Supported architectures: x86-64 and ARM64.' ;; esac
command -v curl >/dev/null 2>&1 || fail 'Install curl first.'
if command -v sha256sum >/dev/null 2>&1; then checksum=sha256sum
elif command -v shasum >/dev/null 2>&1; then checksum=shasum
else fail 'Install sha256sum or shasum first.'; fi
asset="small-cloud-$system-$arch"
base="https://small-cloud.monkeysees.one/cli/releases/$release"
temporary=$(mktemp -d)
staged=
trap 'rm -rf "$temporary"; if [ -n "$staged" ]; then rm -f "$staged"; fi' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' "$base/$asset" -o "$temporary/$asset"
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' "$base/$asset.sha256" -o "$temporary/checksum"
expected=$(awk -v name="$asset" 'NF == 2 && $2 == name {print $1}' "$temporary/checksum")
[ "${#expected}" -eq 64 ] || fail 'Invalid release checksum.'
case "$expected" in *[!0-9a-f]*) fail 'Invalid release checksum.' ;; esac
if [ "$checksum" = sha256sum ]; then actual=$(sha256sum "$temporary/$asset")
else actual=$(shasum -a 256 "$temporary/$asset"); fi
actual=${actual%% *}
[ "$expected" = "$actual" ] || fail 'Checksum mismatch; existing installation kept.'
chmod 755 "$temporary/$asset"
"$temporary/$asset" --version
mkdir -p "$destination"
[ ! -d "$destination/small-cloud" ] || fail 'Destination is a directory.'
staged=$(mktemp "$destination/.small-cloud.XXXXXX")
cp "$temporary/$asset" "$staged"
chmod 755 "$staged"
mv -f "$staged" "$destination/small-cloud"
staged=
echo "Installed $destination/small-cloud"
case ":$PATH:" in
    *":$destination:"*) ;;
    *) echo "Add $destination to PATH in your shell configuration, then open a new terminal." ;;
esac
echo 'Run small-cloud --help, then small-cloud auth login when ready for browser approval.'
