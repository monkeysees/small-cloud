#!/usr/bin/env python3
"""Prepare bounded deployed database probes through SSH without credential output."""
import argparse
import io
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'infra'))
from cloud import Failure
from remote import Host, stream_command


WRITE_ENV = '''import os,sys
path=sys.argv[1]
os.umask(0o077)
value=sys.stdin.buffer.read(65537)
if len(value)>65536: raise SystemExit(1)
fd=os.open(path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW, 0o600)
with os.fdopen(fd,"wb") as output:
 os.fchmod(output.fileno(),0o600)
 output.write(value)
 output.flush()
 os.fsync(output.fileno())
'''


def prepare(control_ip, runtime_ip, count=2):
    if not 2 <= count <= 30:
        raise ValueError('Probe count must be between 2 and 30')
    labels = [chr(ord('a') + index) if index < 26 else 'a' + chr(ord('a') + index - 26)
              for index in range(count)]
    control, runtime = Host(control_ip), Host(runtime_ip)
    metadata = {}
    for label in labels:
        metadata[label] = json.loads(control.command('small-cloud-tool-database', f'hosting-probe-{label}'))
        if not re.fullmatch(r'tool_[0-9a-f]{24}', metadata[label]['database']):
            raise Failure('Unexpected probe database identifier')
    result = {}
    for label in labels:
        other = 'b' if label == 'a' else 'a'
        credential_path = metadata[label]['encrypted_credentials']
        if credential_path != f"/srv/small-cloud/secrets/{metadata[label]['database']}.json.age":
            raise Failure('Unexpected encrypted credential path')
        decrypted = io.BytesIO()
        stream_command(['ssh', *control.options, 'root@' + control.address,
                        shlex.join(['age', '--decrypt', '-i', '/srv/small-cloud/secrets/identity.age',
                                    credential_path])], decrypted, 65536, 60)
        saved = json.loads(decrypted.getvalue())
        if saved['database'] != metadata[label]['database'] or saved['tool_id'] != f'hosting-probe-{label}':
            raise Failure('Probe credential identity mismatch')
        url = saved['database_url']
        if any(character in url for character in ('\n', '\r', '\x00')):
            raise Failure('Invalid database URL')
        destination = f'/run/sc-probe-{label}.env'
        data = f"DATABASE_URL={url}\nPROBE_OTHER_DATABASE={metadata[other]['database']}\n".encode()
        transfer = subprocess.run(['ssh', *runtime.options, 'root@' + runtime.address,
                                   shlex.join(['python3', '-c', WRITE_ENV, destination])],
                                  input=data, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=60, check=False)
        if transfer.returncode:
            raise Failure('Runtime environment handoff failed')
        result[label] = {'database': metadata[label]['database'], 'environment_file': destination}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control-ip', required=True)
    parser.add_argument('--runtime-ip', required=True)
    parser.add_argument('--count', type=int, default=2, choices=range(2, 31), metavar='2..30')
    args = parser.parse_args()
    try:
        result = prepare(args.control_ip, args.runtime_ip, args.count)
        print(json.dumps({'count': len(result), 'databases': result}, indent=2))
        return 0
    except (Failure, OSError, ValueError, KeyError, subprocess.SubprocessError):
        print('Database probe preparation failed; no credentials returned.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
