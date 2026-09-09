#!/usr/bin/env python3
"""Root-only operator sandbox runner. No creator-facing admission API."""
import argparse
import fcntl
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile
import time
import math
import tempfile


def run(*args, input=None):
    return subprocess.run(args, input=input, text=True, check=True, capture_output=True, timeout=60).stdout.strip()


def policy(config):
    control = str(ipaddress.IPv4Address(config['control_private_ip']))
    database = str(ipaddress.IPv4Address(config['database_private_ip']))
    management = [str(ipaddress.IPv4Address(value)) for value in config['management_public_ips']]
    if not management:
        raise ValueError('management_public_ips must include every platform public management address')
    blocked = ['0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
               '169.254.0.0/16', '172.16.0.0/12', '192.0.0.0/24', '192.0.2.0/24',
               '192.168.0.0/16', '198.18.0.0/15', '198.51.100.0/24',
               '203.0.113.0/24', '224.0.0.0/4', '240.0.0.0/4']
    return f'''table inet small_cloud {{
 chain input {{
  type filter hook input priority -10; policy accept;
  iifname "sc-*" drop
 }}
 chain forward {{
  type filter hook forward priority -10; policy accept;
  iifname "sc-*" meta nfproto ipv6 drop
  oifname "sc-*" meta nfproto ipv6 drop
  iifname "sc-*" oifname "sc-*" drop
  iifname "sc-*" ip daddr {{ {', '.join(management)} }} drop
  iifname "sc-*" ip daddr {database} tcp dport 5432 accept
  iifname "sc-*" ip daddr {control} ct state established,related accept
  iifname "sc-*" ip daddr {{ {', '.join(blocked)} }} drop
  iifname "sc-*" accept
  oifname "sc-*" ct state established,related accept
  oifname "sc-*" ip saddr {control} tcp dport 8080 accept
  oifname "sc-*" drop
 }}
}}
'''


def containers():
    ids = run('docker', 'ps', '-aq', '--filter', 'label=small-cloud.tool').split()
    return json.loads(run('docker', 'inspect', *ids)) if ids else []


IMAGE_STATE = Path('/var/lib/small-cloud-runtime/images')


def private_record(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size > 65536):
            raise ValueError('unsafe release inventory')
        return json.load(stream)


def save_record(path, record):
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix='.record-')
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        Path(name).unlink(missing_ok=True)


def release_records():
    image_state(check_capacity=False)
    path = IMAGE_STATE.parent / 'releases.json'
    try:
        records = private_record(path)
    except FileNotFoundError:
        return {}
    if not isinstance(records, dict) or len(records) > 60:
        raise ValueError('invalid release inventory')
    for key, image in records.items():
        if (not re.fullmatch(r'[a-z0-9-]{1,32}/[a-z0-9-]{1,64}', key)
                or not isinstance(image, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', image)):
            raise ValueError('invalid retained release')
    return records


def retain_release(tool, release, image=None):
    if (not re.fullmatch(r'[a-z0-9-]{1,32}', tool)
            or not re.fullmatch(r'[a-z0-9-]{1,64}', release)):
        raise ValueError('invalid app or release identifier')
    records = release_records()
    key = tool + '/' + release
    if image is not None:
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
            raise ValueError('release image must be an immutable image ID')
        if key in records and records[key] != image:
            raise ValueError('release identity is immutable')
        if key not in records and (len(records) >= 60 or sum(k.startswith(tool + '/') for k in records) >= 2
                                   or len({k.split('/')[0] for k in records} | {tool}) > 30):
            raise ValueError('retain at most thirty apps and two releases per app')
        if json.loads(run('docker', 'image', 'inspect', image))[0]['Id'] != image:
            raise ValueError('loaded image identity mismatch')
        track_image(image)
        records[key] = image
    elif key in records:
        old = records.pop(key)
        # Start grace before unpinning, so a crash can only retain the image longer.
        save_record(IMAGE_STATE / (old[7:] + '.json'), {'image': old, 'created_at': time.time()})
    save_record(IMAGE_STATE.parent / 'releases.json', records)
    print(json.dumps({'retained_releases': len(records)}))


def image_state(check_capacity=True):
    IMAGE_STATE.parent.mkdir(mode=0o700, exist_ok=True)
    IMAGE_STATE.mkdir(mode=0o700, exist_ok=True)
    for directory in (IMAGE_STATE.parent, IMAGE_STATE):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('image inventory must be private and operator owned')
    if not check_capacity:
        return []
    with os.scandir(IMAGE_STATE) as scanner:
        records = []
        for entry in scanner:
            if len(records) >= 256:
                raise ValueError('image inventory capacity reached; prune before preparing more images')
            records.append(Path(entry.path))
    return records


def track_image(image):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
        raise ValueError('Docker did not return an immutable derived image ID')
    image_state(check_capacity=False)
    path = IMAGE_STATE / (image.removeprefix('sha256:') + '.json')
    if path.exists():
        if private_record(path)['image'] != image:
            raise ValueError('image inventory identity mismatch')
        return
    if len(image_state()) >= 256:
        raise ValueError('image inventory full; prune before tracking another image')
    path = IMAGE_STATE / (image.removeprefix('sha256:') + '.json')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump({'image': image, 'created_at': time.time()}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(IMAGE_STATE, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def image_records():
    # Trusted local metadata may predate the cap; stream it so cleanup can recover.
    with os.scandir(IMAGE_STATE) as scanner:
        for entry in scanner:
            yield Path(entry.path)


def prune_images():
    removed = 0
    retained = 0
    now = time.time()
    image_state(check_capacity=False)
    protected = set(release_records().values())
    for path in image_records():
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size > 4096):
            raise ValueError('unsafe derived-image inventory record')
        record = json.loads(path.read_text())
        image = record['image']
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', image) or path.name != image[7:] + '.json':
            raise ValueError('derived-image inventory identity mismatch')
        created = record['created_at']
        if isinstance(created, bool) or not isinstance(created, (int, float)) or not math.isfinite(created) or not 0 <= created <= now:
            raise ValueError('invalid derived-image timestamp')
        if image in protected or now - created < 3600:
            retained += 1
            continue
        try:
            # Parent images may be retained releases even without a container or tag.
            run('docker', 'image', 'rm', '--no-prune', image)
        except subprocess.CalledProcessError:
            retained += 1
            continue
        path.unlink()
        removed += 1
    print(json.dumps({'removed_images': removed, 'retained_images': retained}))


def image_with_ca(image, ca):
    # Docker rejects cp into read-only roots. Prepare an image without executing creator code.
    if len(image_state()) >= 256:
        raise ValueError('image inventory full; prune before preparing more images')
    container = run('docker', 'create', '--network', 'none', image)
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as bundle:
        directory = tarfile.TarInfo('etc/small-cloud')
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        bundle.addfile(directory)
        certificate = tarfile.TarInfo('etc/small-cloud/database-ca.crt')
        certificate.size = len(ca)
        certificate.mode = 0o644
        bundle.addfile(certificate, io.BytesIO(ca))
    try:
        subprocess.run(['docker', 'cp', '-', f'{container}:/'], input=archive.getvalue(),
                       check=True, capture_output=True, timeout=60)
        derived = run('docker', 'commit', container)
        try:
            track_image(derived)
        except (OSError, ValueError):
            run('docker', 'image', 'rm', '--no-prune', derived)
            raise
        return derived
    finally:
        run('docker', 'rm', container)


RESOLVER_FILE = Path('/etc/small-cloud/runtime-resolv.conf')
RESOLVER_CONTENT = 'nameserver 1.1.1.1\nnameserver 8.8.8.8\noptions timeout:2 attempts:2\n'


def resolver_file():
    try:
        descriptor = os.open(RESOLVER_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    except FileExistsError:
        pass
    else:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(RESOLVER_CONTENT)
    info = RESOLVER_FILE.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o644 or info.st_size != len(RESOLVER_CONTENT)
            or RESOLVER_FILE.read_text() != RESOLVER_CONTENT):
        raise ValueError('public resolver configuration must be an unmodified operator-owned regular file')
    return str(RESOLVER_FILE)


class ActiveCapacity(ValueError):
    pass


def allocation_role(entry):
    # Docker labels are immutable; the root-controlled name follows promotion.
    prefix = '/sc-' + entry['Config']['Labels']['small-cloud.tool'] + '-'
    name = entry['Name']
    if name not in (prefix + 'active', prefix + 'candidate'):
        raise ValueError('unknown app allocation name requires operator reconciliation')
    return name[len(prefix):]


def promote(tool):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,31}', tool):
        raise ValueError('invalid app identifier')
    own = [entry for entry in containers() if entry['Config']['Labels']['small-cloud.tool'] == tool]
    candidate = next((entry for entry in own if allocation_role(entry) == 'candidate'), None)
    active = next((entry for entry in own if allocation_role(entry) == 'active'), None)
    if candidate is None:
        if active is not None and active['State']['Running']:
            print(json.dumps({'container': 'sc-' + tool + '-active'}))
            return
        raise ValueError('no running allocation to promote')
    if not candidate['State']['Running']:
        raise ValueError('candidate must be running before promotion')
    if active is not None:
        run('docker', 'rm', '-f', 'sc-' + tool + '-active')
    run('docker', 'rename', 'sc-' + tool + '-candidate', 'sc-' + tool + '-active')
    print(json.dumps({'container': 'sc-' + tool + '-active'}))


def launch(config, tool, image, candidate=False, env_file=None, deployment=None):
    logging = ['--log-driver', 'none']
    if deployment is not None:
        if not re.fullmatch(r'd-[0-9a-f]{24}', deployment):
            raise ValueError('invalid diagnostic deployment')
        logging = ['--log-driver', 'syslog', '--log-opt', 'syslog-address=unix:///run/small-cloud-diagnostics.sock',
                   '--log-opt', 'syslog-format=rfc5424micro', '--log-opt', 'tag=' + deployment,
                   '--log-opt', 'cache-disabled=true', '--log-opt', 'mode=blocking']
    environment = []
    if env_file is not None:
        metadata = env_file.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise ValueError('environment file must be a root-owned regular file with mode 0600')
        environment = ['--env-file', str(env_file)]
    ca_path = Path('/etc/small-cloud/database-ca.crt')
    ca = ca_path.read_bytes()
    if not ca.startswith(b'-----BEGIN CERTIFICATE-----'):
        raise ValueError('database CA must be a PEM certificate')
    entries = containers()
    own = [entry for entry in entries if entry['Config']['Labels']['small-cloud.tool'] == tool]
    candidates = [entry for entry in entries if allocation_role(entry) == 'candidate']
    active = [entry for entry in entries if allocation_role(entry) == 'active']
    if candidate:
        if candidates or len(own) != 1 or allocation_role(own[0]) != 'active':
            raise ValueError('one update candidate requires exactly one existing active allocation')
    elif own:
        raise ValueError('app already allocated')
    elif len(active) >= 5:
        raise ActiveCapacity('five active allocations reserved')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,31}', tool):
        raise ValueError('app must be 1–32 lowercase letters, digits or hyphens')
    if not re.fullmatch(r'(?:[^\s]+@)?sha256:[0-9a-f]{64}', image):
        raise ValueError('image must be pinned by sha256 digest and already loaded')
    info = json.loads(run('docker', 'image', 'inspect', image))[0]
    if info['Config'].get('Volumes'):
        raise ValueError('image VOLUME declarations bypass temporary-write bounds')
    role = 'candidate' if candidate else 'active'
    name = f'sc-{tool}-{role}'
    used = {entry['Config']['Labels']['small-cloud.slot'] for entry in entries}
    slot = next(str(value) for value in range(6) if str(value) not in used)
    network = f'sc-slot-{slot}'
    try:
        run('docker', 'network', 'inspect', network)
    except subprocess.CalledProcessError:
        run('docker', 'network', 'create', '--driver', 'bridge', '--subnet', f'172.30.{slot}.0/24',
            '--opt', f'com.docker.network.bridge.name=sc-{slot}', network)
    network_info = json.loads(run('docker', 'network', 'inspect', network))[0]
    ranges = network_info['IPAM']['Config']
    if (network_info['Driver'] != 'bridge' or network_info.get('EnableIPv6')
            or network_info['Options'].get('com.docker.network.bridge.name') != f'sc-{slot}'
            or len(ranges) != 1
            or ranges[0].get('Subnet') != f'172.30.{slot}.0/24'
            or ranges[0].get('Gateway') != f'172.30.{slot}.1'
            or ranges[0].get('IPRange') not in (None, '')
            or ranges[0].get('AuxiliaryAddresses')
            or ranges[0].get('AuxAddress')
            or network_info.get('Containers')):
        raise ValueError('existing slot network does not match the isolated empty allocation')
    image = image_with_ca(image, ca)
    # Reinstall the full ruleset atomically before any untrusted process can run.
    install_policy(config)
    resolver = resolver_file()
    run('docker', 'create', '--name', name, '--runtime', 'runsc', '--pull', 'never',
        '--label', f'small-cloud.tool={tool}', '--label', f'small-cloud.role={role}',
        '--label', f'small-cloud.slot={slot}', '--network', network,
        '--ip', f'172.30.{slot}.2', '--dns', '1.1.1.1', '--read-only',
        '--mount', f'type=bind,src={resolver},dst=/etc/resolv.conf,readonly',
        '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=1073741824,mode=1777',
        '--shm-size', '1m', '--cpus', '0.5', '--memory', '512m', '--memory-swap', '512m',
        '--pids-limit', '128', '--ulimit', 'nproc=128:128', '--ulimit', 'core=0:0', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--user', '65532:65532', '--ulimit', 'nofile=1024:1024', *logging,
        '--publish', f"{config['runtime_private_ip']}:{18080 + int(slot)}:8080",
        *environment, '--env', 'PORT=8080', image)
    run('docker', 'start', name)
    print(json.dumps({'container': name, 'role': role, 'private_port': 18080 + int(slot)}))


def install_policy(config):
    rules = policy(config)
    try:
        run('nft', 'list', 'table', 'inet', 'small_cloud')
        rules = 'delete table inet small_cloud\n' + rules
    except subprocess.CalledProcessError:
        pass
    run('nft', '-f', '-', input=rules)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('policy', help='render firewall for inspection')
    commands.add_parser('apply-policy')
    commands.add_parser('prune-images', help='remove unreferenced tracked images after a one-hour grace period, without force')
    retain = commands.add_parser('retain-image', help='protect an imported image for a stored release')
    retain.add_argument('tool', metavar='app')
    retain.add_argument('release')
    retain.add_argument('image')
    forget = commands.add_parser('forget-release', help='release a stored image after a one-hour grace period')
    forget.add_argument('tool', metavar='app')
    forget.add_argument('release')
    promotion = commands.add_parser('promote', help='promote a candidate after the trusted controller verified readiness')
    promotion.add_argument('tool', metavar='app')
    start = commands.add_parser('start')
    start.add_argument('tool', metavar='app')
    start.add_argument('image')
    start.add_argument('--candidate', action='store_true')
    start.add_argument('--env-file', type=Path, help='root-owned mode-0600 DATABASE_URL/app environment')
    start.add_argument('--deployment', help='Product deployment ID for collected, redacted diagnostics')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    ipaddress.IPv4Address(config['runtime_private_ip'])
    if args.command == 'policy':
        print(policy(config), end='')
        return
    if os.geteuid() != 0:
        parser.error('requires root on the dedicated runtime host')
    with open('/run/small-cloud-runtime.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.command == 'apply-policy':
            install_policy(config)
        elif args.command == 'prune-images':
            prune_images()
        elif args.command == 'retain-image':
            retain_release(args.tool, args.release, args.image)
        elif args.command == 'promote':
            promote(args.tool)
        elif args.command == 'forget-release':
            retain_release(args.tool, args.release)
        else:
            launch(config, args.tool, args.image, args.candidate, args.env_file, args.deployment)


if __name__ == '__main__':
    try:
        main()
    except ActiveCapacity:
        print(json.dumps({'error': {'code': 'ACTIVE_CAPACITY'}}))
        raise SystemExit(5)
