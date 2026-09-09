#!/usr/bin/env bash
# Usage: run.sh /var/lib/small-cloud-build/context.tar MANAGEMENT_IPV4...
set -euo pipefail
[[ "$(id -u)" == 0 && "$#" -ge 2 ]]
root=/var/lib/small-cloud-build
[[ "$1" == "$root/context.tar" && -f "$1" && ! -L "$1" ]]
mountpoint -q "$root"
[[ ! -e "$root/started" ]]
archive="$1"
shift
umask 077
# Consume this VM even when validation or setup fails; never reuse its daemon.
(set -o noclobber; : > "$root/started")
mkdir -p "$root/output"
cleanup() {
  python3 /opt/small-cloud-builder/worker.py terminate 2>/dev/null || true
  systemctl stop sc-build-worker.service sc-build-daemon.service 2>/dev/null || true
}
trap cleanup EXIT
python3 /opt/small-cloud-builder/worker.py prepare "$archive" "$@"
sysctl -q -w net.ipv4.ip_forward=1 net.ipv6.conf.all.disable_ipv6=1 net.ipv6.conf.default.disable_ipv6=1
ip netns add sc-build
ip link add sc-host type veth peer name sc-peer
ip link set sc-peer netns sc-build
ip addr add 192.0.2.1/30 dev sc-host
ip link set sc-host up
ip netns exec sc-build ip addr add 192.0.2.2/30 dev sc-peer
ip netns exec sc-build ip link set sc-peer up
ip netns exec sc-build ip link set lo up
ip netns exec sc-build ip route add default via 192.0.2.1
ip netns exec sc-build sysctl -q -w net.ipv6.conf.all.disable_ipv6=1 net.ipv6.conf.default.disable_ipv6=1
install -d /etc/netns/sc-build
printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' > /etc/netns/sc-build/resolv.conf
nft -f "$root/policy.nft"
# This host timer is outside the build slice and survives an SSH disconnect.
systemd-run --unit=sc-build-deadline --on-active=600s --timer-property=AccuracySec=1us \
  /usr/bin/python3 /opt/small-cloud-builder/worker.py terminate
systemd-run --unit=sc-build-daemon --slice=small-cloud-build.slice \
  --property=Delegate=yes --property=TimeoutStopSec=1s \
  --property=LimitCORE=0 \
  --property=StandardOutput=null --property=StandardError=null \
  /usr/bin/unshare --mount --propagation private \
  /usr/bin/python3 /opt/small-cloud-builder/worker.py daemon \
  /usr/bin/nsenter --net=/run/netns/sc-build /usr/bin/dockerd \
  --host=unix:///run/sc-build.sock --data-root="$root/docker" \
  --exec-root=/run/sc-build-docker --pidfile=/run/sc-build-docker.pid \
  --exec-opt=native.cgroupdriver=systemd --cgroup-parent=small-cloud-build.slice \
  --feature=containerd-snapshotter=false --storage-driver=overlay2 \
  --dns=1.1.1.1 --dns=8.8.8.8 --ipv6=false \
  --log-driver=local --log-opt=max-size=1m --log-opt=max-file=1
systemd-run --wait --unit=sc-build-worker --slice=small-cloud-build.slice \
  --property=TimeoutStopSec=1s --property=StandardOutput=null --property=StandardError=null \
  --property=LimitCORE=0 \
  /usr/bin/python3 /opt/small-cloud-builder/worker.py execute
printf '%s\n' 'Build succeeded: retrieve output/image.tar, output/build.log and output/result.json over SSH, then delete this VM.'
