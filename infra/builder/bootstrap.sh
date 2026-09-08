#!/usr/bin/env bash
# Trusted operator bootstrap on a fresh Ubuntu 24.04 x86_64 VM only.
set -euo pipefail
[[ "$(id -u)" == 0 && "$(uname -m)" == x86_64 ]]
[[ -f /sys/fs/cgroup/cgroup.controllers ]]
[[ ! -e /var/lib/small-cloud-build ]]
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq docker.io docker-buildx nftables iproute2 python3 e2fsprogs
systemctl disable --now docker.service docker.socket containerd.service
# Package post-install may have started Docker and left a host FORWARD drop policy.
# The runner installs its own external, default-deny forwarding policy before builds.
iptables -P FORWARD ACCEPT
install -d -m 0700 /var/lib/small-cloud-build /opt/small-cloud-builder
# All source, daemon state, cache and exported image share this hard disk bound.
fallocate -l 10G /var/lib/small-cloud-build.disk
chmod 0600 /var/lib/small-cloud-build.disk
mkfs.ext4 -q -F -m 0 /var/lib/small-cloud-build.disk
mount -o loop,nodev,nosuid /var/lib/small-cloud-build.disk /var/lib/small-cloud-build
chmod 0700 /var/lib/small-cloud-build
install -d -m 0700 /var/lib/small-cloud-build/output
cat > /etc/systemd/system/small-cloud-build.slice <<'EOF'
[Unit]
Description=Single disposable Small Cloud build
[Slice]
CPUQuota=200%
MemoryMax=3500M
MemorySwapMax=0
TasksMax=512
EOF
systemctl daemon-reload
printf '%s\n' 'Builder prepared; upload trusted runner and untrusted source separately.'
