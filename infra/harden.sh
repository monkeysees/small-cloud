#!/usr/bin/env bash
# Shared host policy: no automatic crash exports or process-memory artifacts.
set -euo pipefail
[[ "$(id -u)" == 0 ]]
units=(apport.service apport-autoreport.service apport-autoreport.path apport-autoreport.timer apport-forward.socket whoopsie.service systemd-coredump.socket)
for unit in "${units[@]}"; do
  if systemctl cat "$unit" >/dev/null 2>&1; then
    systemctl stop "$unit"
  fi
  systemctl mask "$unit"
done
systemctl mask apport-forward@.service apport-coredump-hook@.service systemd-coredump@.service
printf 'enabled=0\n' > /etc/default/apport
install -d -m 0755 /etc/sysctl.d
cat > /etc/sysctl.d/90-small-cloud-no-core.conf <<'POLICY'
# Piped core handlers ignore RLIMIT_CORE; replace the reporter itself too.
kernel.core_pattern=|/bin/false
kernel.core_pipe_limit=1
POLICY
sysctl -p /etc/sysctl.d/90-small-cloud-no-core.conf >/dev/null
ulimit -c 0
