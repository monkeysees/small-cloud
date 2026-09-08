#!/usr/bin/env python3
"""Trusted host observations after execution, never run inside the Dockerfile."""
import json
import os
from pathlib import Path
import platform
import subprocess
import socket

group = subprocess.check_output(['systemctl', 'show', 'small-cloud-build.slice',
                                 '--property=ControlGroup', '--value'], text=True, timeout=5).strip()
if not group.startswith('/') or not group.endswith('/small-cloud-build.slice') or '..' in group:
    raise ValueError('build cgroup is unavailable')
root = Path('/sys/fs/cgroup') / group.lstrip('/')
values = {}
for name in ('cpu.max', 'cpu.stat', 'memory.max', 'memory.peak', 'memory.events',
             'memory.swap.max', 'pids.max', 'pids.peak', 'pids.events', 'cgroup.events'):
    path = root / name
    if path.exists():
        values[name] = path.read_text()[:4096].strip()
volume = os.statvfs('/var/lib/small-cloud-build')
with socket.create_connection(('169.254.169.254', 80), timeout=3):
    metadata_listener = True
namespace_ipv6 = subprocess.check_output(['ip', 'netns', 'exec', 'sc-build', 'sysctl', '-n',
    'net.ipv6.conf.all.disable_ipv6'], text=True, timeout=5).strip()
print(json.dumps({'kernel': platform.release(), 'cgroup': values,
                  'filesystem_bytes': volume.f_blocks * volume.f_frsize,
                  'filesystem_free_bytes': volume.f_bavail * volume.f_frsize,
                  'ipv6_disabled': Path('/proc/sys/net/ipv6/conf/all/disable_ipv6').read_text().strip(),
                  'build_namespace_ipv6_disabled': namespace_ipv6, 'trusted_host_metadata_listener': metadata_listener,
                  'core_handler': Path('/proc/sys/kernel/core_pattern').read_text().strip(),
                  'apport_state': subprocess.run(['systemctl', 'is-enabled', 'apport.service'],
                      capture_output=True, text=True, timeout=5).stdout.strip(),
                  'docker_version': subprocess.check_output(['docker', '--version'], text=True, timeout=5).strip()}))
