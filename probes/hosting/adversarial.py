#!/usr/bin/env python3
"""Run inside a real Dockerfile RUN or tool sandbox, with an operator-controlled canary."""
import argparse
import json
import os
from pathlib import Path
import socket
import time
import urllib.error
import urllib.request

from network import matrix, attempt


def accessible(path):
    try:
        return Path(path).exists()
    except PermissionError:
        return False


def request(url, proxy=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({} if proxy is None else {'http': proxy, 'https': proxy}))
    try:
        with opener.open(url, timeout=3) as response:
            return {'connected': True, 'status': response.status}
    except urllib.error.HTTPError as error:
        return {'connected': True, 'status': error.code}
    except (OSError, urllib.error.URLError) as error:
        reason = error.reason if isinstance(error, urllib.error.URLError) else error
        return {'connected': False, 'timeout': isinstance(reason, (TimeoutError, socket.timeout))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--phase', choices=['build', 'runtime'], required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    config['targets'].extend(config.get(args.phase + '_targets', []))
    result = matrix(config, args.phase)
    result['limitation'] = 'Denials require independent healthy controls; correlate public nonces with canary logs.'
    nonce = config['nonce'] + '-' + args.phase
    public = config['public_origin'] + '/' + nonce
    result['public_nonce'] = nonce
    result['public_https'] = request(public)
    result['private_proxy'] = request(public, config['private_proxy'])
    result['proxy_bypassed'] = request(public)
    result['redirect_to_private'] = request(config['public_origin'] + '/redirect/' + nonce)
    result['filesystem'] = {name: accessible(name) for name in
        ('/var/run/docker.sock', '/run/sc-build.sock', '/srv/small-cloud/secrets/identity.age',
         '/root/.config/small-cloud/secrets/hetzner-token')}
    result['uid'] = os.getuid()
    host = args.phase + '.' + config['rebind_domain']
    result['rebind'] = []
    # The operator flips this real authoritative DNS record after the public nonce appears.
    deadline = time.monotonic() + 150
    seen_public = False
    while time.monotonic() < deadline:
        record = socket.getaddrinfo(host, 80, family=socket.AF_INET, type=socket.SOCK_STREAM)[0]
        address = record[4][0]
        observed = attempt({'host': host, 'port': 80, 'family': 'ipv4'}, record)
        result['rebind'].append({'resolved': address, **observed})
        if address == config['public_ipv4'] and observed.get('connected'):
            seen_public = True
            request('http://' + host + '/' + nonce + '-rebind-ready')
        elif address == config['private_ipv4']:
            result['rebind_pass'] = seen_public and not observed.get('connected') and observed['observed'] in ('timeout', 'unreachable')
            break
        time.sleep(3)
    else:
        result['rebind_pass'] = False
    result['ipv6_attempt'] = attempt({'host': '2606:4700:4700::1111', 'port': 443, 'family': 'ipv6'})
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
