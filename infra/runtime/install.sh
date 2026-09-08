#!/usr/bin/env bash
# Dedicated Ubuntu 24.04 x86_64 runtime host only. Supply a reviewed immutable gVisor bundle.
set -euo pipefail
: "${RUNSC_URL:?Set an immutable https gVisor release artifact URL}"
: "${RUNSC_SHA256:?Set its independently verified SHA256}"
[[ "$(id -u)" == 0 && "$(uname -m)" == x86_64 ]]
[[ "$RUNSC_URL" == https://storage.googleapis.com/gvisor/releases/release/*/x86_64/gvisor.tar.bz2 ]]
[[ "$RUNSC_URL" != *latest* && "$RUNSC_SHA256" =~ ^[0-9a-f]{64}$ ]]
daemon_config='{"runtimes":{"runsc":{"path":"/usr/local/bin/runsc","runtimeArgs":["--network=sandbox"]}},"ipv6":false,"live-restore":false,"log-driver":"none"}'
if [[ -e /etc/docker/daemon.json ]]; then
  python3 -c 'import json,sys; sys.exit(0 if json.load(open("/etc/docker/daemon.json")) == json.loads(sys.argv[1]) else "Refusing unknown Docker configuration")' "$daemon_config"
fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io nftables curl ca-certificates bzip2
artifact="$(mktemp)"
trap 'rm -f "$artifact"' EXIT
curl --fail --silent --show-error --location "$RUNSC_URL" --output "$artifact"
printf '%s  %s\n' "$RUNSC_SHA256" "$artifact" | sha256sum --check --status
# The verified release contains runsc and its required adjacent gvisor-bin sidecars.
tar -xjf "$artifact" -C /usr/local/bin
[[ -x /usr/local/bin/runsc && -d /usr/local/bin/gvisor-bin ]]
mkdir -p /etc/docker
printf '%s\n' "$daemon_config" > /etc/docker/daemon.json
cat > /etc/sysctl.d/80-small-cloud-runtime.conf <<'SYSCTL'
net.ipv6.conf.all.disable_ipv6=1
net.ipv6.conf.default.disable_ipv6=1
SYSCTL
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/80-small-cloud.conf <<'JOURNAL'
[Journal]
SystemMaxUse=1G
RuntimeMaxUse=256M
MaxRetentionSec=7day
JOURNAL
systemctl restart systemd-journald
sysctl --system
systemctl restart docker
/usr/local/bin/runsc --version
docker version --format '{{.Server.Version}}'
