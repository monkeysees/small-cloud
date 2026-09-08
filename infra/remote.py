#!/usr/bin/env python3
"""Operator SSH configuration and one-build execution with finally-path VM deletion."""
from __future__ import annotations

import argparse
import io
import ipaddress
import json
import os
from pathlib import Path
import shlex
import shutil
import selectors
import signal
import stat
import subprocess
import sys
import time
import tempfile

from cloud import API, Failure, OWNER, SECRET_DIR, SELECTOR, private_file, state_directory
from artifacts import require_space

HERE = Path(__file__).resolve().parent


def stream_command(args: list[str], output, limit: int, timeout: int, stderr_output=None) -> None:
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               stdin=subprocess.DEVNULL, start_new_session=True)
    if process.stdout is None or process.stderr is None:
        raise Failure('Remote command pipes were not created')
    deadline = time.monotonic() + timeout
    totals = {"stdout": 0, "stderr": 0}
    try:
        with selectors.DefaultSelector() as selector:
            for pipe, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Failure("Remote command deadline exceeded")
                for key, _ in selector.select(min(remaining, 1)):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    totals[key.data] += len(chunk)
                    bound = limit if key.data == "stdout" else 1024 * 1024
                    if totals[key.data] > bound:
                        raise Failure("Remote command output exceeded its bound")
                    if key.data == "stdout":
                        output.write(chunk)
                    elif stderr_output is not None:
                        stderr_output.write(chunk)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Failure("Remote command deadline exceeded")
        if process.wait(timeout=remaining):
            raise Failure(f"{Path(args[0]).name} failed; inspect protected host diagnostics")
    finally:
        # Kill descendants too: an inherited pipe must not keep this controller blocked.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        process.stdout.close()
        process.stderr.close()


def run(args: list[str], timeout: int = 900, diagnostics: Path | None = None) -> str:
    output = io.BytesIO()
    if diagnostics is None:
        stream_command(args, output, 1024 * 1024, timeout)
    else:
        with diagnostics.open('xb') as errors:
            diagnostics.chmod(0o600)
            stream_command(args, output, 1024 * 1024, timeout, stderr_output=errors)
    return output.getvalue().decode("utf-8", errors="replace")


class Host:
    def __init__(self, address: str, host_key_alias: str | None = None):
        self.address = str(ipaddress.IPv4Address(address))
        self.options = ["-i", str(state_directory() / "operator_ed25519"),
            "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=5",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "UserKnownHostsFile=" + str(state_directory() / "known_hosts")]
        if host_key_alias is not None:
            self.options.extend(['-o', 'HostKeyAlias=' + host_key_alias])

    def command(self, *args: str, timeout: int = 900) -> str:
        return run(["ssh", *self.options, "root@" + self.address, shlex.join(args)], timeout)

    def ready(self) -> None:
        deadline = time.monotonic() + 300
        while True:
            try:
                self.command("true", timeout=10)
                self.command("cloud-init", "status", "--wait", timeout=300)
                return
            except (Failure, subprocess.TimeoutExpired):
                if time.monotonic() >= deadline:
                    raise Failure("SSH/bootstrap deadline exceeded") from None
                time.sleep(3)

    def upload(self, source: Path, destination: str) -> None:
        run(["scp", *self.options, str(source), f"root@{self.address}:{destination}"])

    def download(self, source: str, destination: Path, limit: int = 65536) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".download-", delete=False) as output:
                temporary = Path(output.name)
                stream_command(["ssh", *self.options, "root@" + self.address,
                                shlex.join(["cat", "--", source])], output, limit, 900)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def configure(args: argparse.Namespace) -> dict:
    foundation = json.loads((state_directory() / "foundation.json").read_text())
    control = Host(foundation["servers"]["control"]["ipv4"])
    runtime = Host(foundation["servers"]["runtime"]["ipv4"])
    for host, role in ((control, "control"), (runtime, "runtime")):
        host.ready()
        destination = "/opt/small-cloud/" + role
        host.command("mkdir", "-p", destination)
        host.upload(HERE / 'harden.sh', '/opt/small-cloud/harden.sh')
        for source in (HERE / role).iterdir():
            if source.suffix in (".sh", ".py"):
                host.upload(source, destination + "/" + source.name)
    control.command("bash", "/opt/small-cloud/control/bootstrap.sh")
    runtime.command("env", "RUNSC_URL=" + args.runsc_url, "RUNSC_SHA256=" + args.runsc_sha256,
                    "bash", "/opt/small-cloud/runtime/install.sh")
    runtime.command("install", "-d", "-m", "0755", "/etc/small-cloud")
    ca = state_directory() / "database-ca.crt"
    control.download("/etc/small-cloud/database-ca.crt", ca)
    runtime.upload(ca, "/etc/small-cloud/database-ca.crt")
    runtime.command("chmod", "0644", "/etc/small-cloud/database-ca.crt")
    config = state_directory() / "runtime.json"
    config.write_text(json.dumps({"control_private_ip": "10.42.0.2", "database_private_ip": "10.42.0.2",
        "runtime_private_ip": "10.42.0.3", "management_public_ips": [control.address, runtime.address]}))
    runtime.upload(config, "/etc/small-cloud/runtime.json")
    runtime.command("python3", "/opt/small-cloud/runtime/sandbox.py", "--config",
                    "/etc/small-cloud/runtime.json", "apply-policy")
    control.command("install", "-d", "-m", "0700", "/root/.config/small-cloud/secrets",
                    "/root/.local/state/small-cloud/infra")
    control.upload(state_directory() / "foundation.json", "/etc/small-cloud/controller.json")
    control.command("chmod", "0600", "/etc/small-cloud/controller.json")
    # Only the trusted control host receives provider authority, never a builder/runtime.
    control.upload(SECRET_DIR / "hetzner-token", "/root/.config/small-cloud/secrets/hetzner-token")
    control.upload(state_directory() / "operator_ed25519", "/root/.local/state/small-cloud/infra/operator_ed25519")
    control.upload(state_directory() / "operator_ed25519.pub", "/root/.local/state/small-cloud/infra/operator_ed25519.pub")
    control.command("chmod", "0600", "/root/.config/small-cloud/secrets/hetzner-token",
                    "/root/.local/state/small-cloud/infra/operator_ed25519")
    control.command("install", "-d", "-m", "0755", "/opt/small-cloud/infra/builder")
    for name in ("cloud.py", "builders.py", "remote.py", "releases.py", "harden.sh"):
        control.upload(HERE / name, "/opt/small-cloud/infra/" + name)
    for name in ("bootstrap.sh", "run.sh", "worker.py", "evidence.py"):
        control.upload(HERE / "builder" / name, "/opt/small-cloud/infra/builder/" + name)
    for name in ("small-cloud-reconcile.service", "small-cloud-reconcile.timer"):
        control.upload(HERE / name, "/etc/systemd/system/" + name)
    control.command("touch", "/etc/small-cloud/controller")
    control.command("systemctl", "daemon-reload")
    control.command("systemctl", "enable", "--now", "small-cloud-reconcile.timer")
    control.upload(HERE / 'artifacts.py', '/opt/small-cloud/infra/artifacts.py')
    for name in ('small-cloud-artifacts.service', 'small-cloud-artifacts.timer'):
        control.upload(HERE / 'artifacts' / name, '/etc/systemd/system/' + name)
    for name in ('small-cloud-releases.service', 'small-cloud-releases.timer'):
        control.upload(HERE / 'artifacts' / name, '/etc/systemd/system/' + name)
    for name in ('small-cloud-runtime-images.service', 'small-cloud-runtime-images.timer'):
        runtime.upload(HERE / 'runtime' / name, '/etc/systemd/system/' + name)
    for host, services in ((control, ['postgresql@16-main.service', 'caddy.service', 'docker-registry.service']),
                           (runtime, ['docker.service'])):
        host.command('install', '-d', '-m', '0755', '/opt/small-cloud/infra',
                     '/etc/systemd/system/small-cloud-monitor.service.d')
        host.upload(HERE / 'monitor.py', '/opt/small-cloud/infra/monitor.py')
        for name in ('small-cloud-monitor.service', 'small-cloud-monitor.timer'):
            host.upload(HERE / 'monitor' / name, '/etc/systemd/system/' + name)
        jobs = ['small-cloud-reconcile', 'small-cloud-artifacts', 'small-cloud-releases'] if host is control else ['small-cloud-runtime-images']
        health_config = json.dumps({'disks': ['/'], 'services': services + [job + '.timer' for job in jobs],
            'oneshot_services': [job + '.service' for job in jobs],
            'tls_hostname': 'small-cloud.monkeysees.one',
            'peers': [{'name': 'runtime', 'host': '10.42.0.3', 'port': 22}] if host is control else
                     [{'name': 'control', 'host': '10.42.0.2', 'port': 5432}]})
        host.command('python3', '-c',
                     'import json,os,pathlib,sys; os.umask(0o077); p=pathlib.Path("/etc/small-cloud/monitor.json"); '
                     'defaults=json.loads(sys.argv[1]); d=json.loads(p.read_text()) if p.exists() else defaults; '
                     'd["peers"]=defaults["peers"]; '
                     'd["services"]=sorted(set(d.get("services",[])+defaults["services"])); '
                     'd["oneshot_services"]=sorted(set(d.get("oneshot_services",[])+defaults["oneshot_services"])); '
                     'p.write_text(json.dumps(d))', health_config)
        host.command('python3', '-c',
                     'import pathlib; pathlib.Path("/etc/systemd/system/small-cloud-monitor.service.d/10-collect-only.conf").write_text('
                     '"[Service]\\nExecStart=\\nExecStart=/usr/bin/python3 /opt/small-cloud/infra/monitor.py '
                     '--config /etc/small-cloud/monitor.json --spend /var/lib/small-cloud/spending.json\\n")')
        host.command('systemctl', 'daemon-reload')
        host.command('systemctl', 'enable', '--now', 'small-cloud-monitor.timer')
    control.command('systemctl', 'enable', '--now', 'small-cloud-artifacts.timer')
    control.command('systemctl', 'enable', '--now', 'small-cloud-releases.timer')
    runtime.command('systemctl', 'enable', '--now', 'small-cloud-runtime-images.timer')
    return {"configured": True, "workload_admission": "closed", "live_acceptance": "not run"}


def verified_hosts() -> list[Host]:
    installed = json.loads(private_file(state_directory() / 'foundation.json'))['servers']
    current = API('hetzner').items('servers', label_selector=SELECTOR)
    hosts = []
    for role in ('control', 'runtime'):
        expected = installed[role]
        matches = [server for server in current if server['id'] == expected['id']]
        if len(matches) != 1:
            raise Failure('Foundation inventory drift; configure current hosts first')
        server = matches[0]
        if (any(server.get('labels', {}).get(key) != value
                for key, value in {**OWNER, 'role': role}.items())
                or server['public_net']['ipv4']['ip'] != expected['ipv4']
                or server['server_type']['name'] != expected['type']
                or server['location']['name'] not in ('nbg1', 'fsn1')):
            raise Failure('Foundation identity mismatch; refusing credential transfer')
        hosts.append(Host(expected['ipv4'], f"small-cloud-{server['id']}"))
    return hosts


def enable_alerts(args: argparse.Namespace) -> dict:
    """Install sending authority only after matching live hosts to local inventory."""
    smtp = json.loads(private_file(args.smtp_config))['smtp']
    if (smtp.get('security') not in ('starttls', 'tls')
            or not isinstance(smtp.get('port'), int) or not 1 <= smtp['port'] <= 65535
            or any(not isinstance(smtp.get(key), str) or not smtp[key]
                   for key in ('host', 'sender', 'username', 'password'))):
        raise Failure('Invalid private SMTP configuration')
    hosts = verified_hosts()
    # Transfer over SSH, never through command arguments or persistent local staging.
    with tempfile.TemporaryDirectory(dir=state_directory(), prefix='.smtp-') as directory:
        source = Path(directory) / 'smtp.json'
        with open(source, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as output:
            json.dump({'smtp': smtp}, output)
        for host in hosts:
            host.command('test', '-f', '/etc/small-cloud/monitor.json')
            destination = host.command('mktemp', '/run/small-cloud-smtp.XXXXXXXX').strip()
            if not destination.startswith('/run/small-cloud-smtp.') or '/' in destination[5:]:
                raise Failure('Unexpected remote temporary path')
            try:
                host.upload(source, destination)
                host.command('python3', '-c',
                    'import json,os,pathlib,stat,sys,tempfile\n'
                    'p=pathlib.Path("/etc/small-cloud/monitor.json"); i=p.lstat()\n'
                    'assert stat.S_ISREG(i.st_mode) and i.st_uid==0 and stat.S_IMODE(i.st_mode)==0o600\n'
                    'd=json.loads(p.read_text()); d["smtp"]=json.loads(pathlib.Path(sys.argv[1]).read_text())["smtp"]\n'
                    'fd,name=tempfile.mkstemp(dir=p.parent,prefix=".monitor-")\n'
                    'try:\n'
                    ' with os.fdopen(fd,"w") as f:\n'
                    '  json.dump(d,f); f.flush(); os.fsync(f.fileno())\n'
                    ' os.replace(name,p)\n'
                    'finally:\n'
                    ' pathlib.Path(name).unlink(missing_ok=True)\n', destination)
                host.command('rm', '-f', '/etc/systemd/system/small-cloud-monitor.service.d/10-collect-only.conf')
                host.command('systemctl', 'daemon-reload')
                host.command('systemctl', 'enable', '--now', 'small-cloud-monitor.timer')
            finally:
                host.command('rm', '-f', '--', destination)
    return {'alerts_enabled': True, 'hosts': ['control', 'runtime'],
            'spending': 'API estimate collector configured separately', 'delivery_check': 'not sent'}


def management_addresses() -> list[str]:
    config = Path("/etc/small-cloud/controller.json")
    info = config.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
        raise Failure("Unsafe controller inventory configuration")
    installed = json.loads(config.read_text())["servers"]
    current = API("hetzner").items("servers", label_selector=SELECTOR)
    addresses = set()
    for role in ("control", "runtime"):
        matches = [server for server in current if server["labels"].get("role") == role]
        if len(matches) != 1 or matches[0]["id"] != installed[role]["id"]:
            raise Failure("Controller inventory drift; reconfigure before building")
        server = matches[0]
        if any(server["labels"].get(key) != value for key, value in OWNER.items()):
            raise Failure("Controller inventory ownership mismatch")
        addresses.add(str(ipaddress.IPv4Address(installed[role]["ipv4"])))
        addresses.add(str(ipaddress.IPv4Address(server["public_net"]["ipv4"]["ip"])))
    return sorted(addresses)


def enable_spending(args: argparse.Namespace) -> dict:
    control, runtime = verified_hosts()
    config = json.loads(args.config.read_text())
    if set(config) - {'opening_estimate'}:
        raise Failure('Unexpected spending configuration field')
    for host in (control, runtime):
        host.upload(HERE / 'monitor.py', '/opt/small-cloud/infra/monitor.py')
        host.upload(HERE / 'monitor/small-cloud-monitor.service', '/etc/systemd/system/small-cloud-monitor.service')
    for name in ('spending.py', 'builders.py', 'cloud.py'):
        control.upload(HERE / name, '/opt/small-cloud/infra/' + name)
    control.command('install', '-d', '-m', '0700', '/var/lib/small-cloud')
    control.command('python3', '-c',
                    'import os,pathlib,sys; os.umask(0o077); '
                    'pathlib.Path("/etc/small-cloud/spending-estimator.json").write_text(sys.argv[1])',
                    json.dumps(config))
    for name in ('small-cloud-spending.service', 'small-cloud-spending.timer'):
        control.upload(HERE / 'monitor' / name, '/etc/systemd/system/' + name)
    control.upload(HERE / 'monitor/05-spending.conf', '/etc/systemd/system/small-cloud-monitor.service.d/05-spending.conf')
    control.command('python3', '-c',
        'import json,pathlib; p=pathlib.Path("/etc/small-cloud/monitor.json"); d=json.loads(p.read_text()); '
        'd["services"]=sorted(set(d.get("services",[])+["small-cloud-spending.timer"])); '
        'd["oneshot_services"]=sorted(set(d.get("oneshot_services",[])+["small-cloud-spending.service"])); '
        'p.write_text(json.dumps(d))')
    for host in (control, runtime):
        host.command('systemctl', 'daemon-reload')
    control.command('systemctl', 'start', 'small-cloud-spending.service', timeout=200)
    control.command('systemctl', 'enable', '--now', 'small-cloud-spending.timer')
    return {'estimate_collection': 'enabled every five minutes on control',
            'spending_alerts': 'control host only; uses existing SMTP authority', 'basis': 'estimate, not invoice'}


def build(args: argparse.Namespace) -> dict:
    if os.geteuid() != 0 or not Path("/etc/small-cloud/controller").is_file():
        raise Failure("Run builds only on the configured German control host; artifact staging must remain in the EU")
    source = args.context.resolve(strict=True)
    staging = Path('/srv/small-cloud/source')
    if not source.is_relative_to(staging):
        raise Failure('Source context must be inside the controlled EU source directory')
    if not source.is_file() or source.stat().st_size > 116 * 1024 * 1024:
        raise Failure("Source must be a bounded uncompressed context tar, at most 116 MiB")
    require_space(staging)
    management = management_addresses()
    destination = args.output.resolve()
    if destination.parent != staging:
        raise Failure('Build output must be a direct child of the controlled source directory')
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    (destination / '.small-cloud-build.json').write_text(json.dumps({'created_at': time.time(), 'job': args.job}))
    copied_source = destination / 'source.tar'
    shutil.copyfile(source, copied_source)
    # All cloud mutation goes through the single-controller admission lock.
    created = None
    try:
        created = json.loads(run([sys.executable, str(HERE / "builders.py"), "create",
            "--admin-cidr", args.admin_cidr, "--job", args.job],
            diagnostics=destination / 'admission.log'))
        (destination / 'builder.json').write_text(json.dumps(created) + '\n')
        # A deleted builder's address can be recycled; identity follows the new VM ID.
        host = Host(created["ipv4"], host_key_alias=f"builder-{created['id']}")
        host.ready()
        host.command("mkdir", "-p", "/opt/small-cloud-builder")
        host.upload(HERE / 'harden.sh', '/opt/small-cloud-builder/harden.sh')
        for name in ("bootstrap.sh", "run.sh", "worker.py", "evidence.py"):
            host.upload(HERE / "builder" / name, "/opt/small-cloud-builder/" + name)
        host.command("bash", "/opt/small-cloud-builder/bootstrap.sh", timeout=600)
        host.upload(copied_source, "/var/lib/small-cloud-build/context.tar")
        management = sorted(set(management) | set(management_addresses()))
        try:
            host.command("bash", "/opt/small-cloud-builder/run.sh", "/var/lib/small-cloud-build/context.tar",
                         *management, timeout=660)
        finally:
            try:
                observation = host.command('python3', '/opt/small-cloud-builder/evidence.py', timeout=15)
                (destination / 'resources.json').write_text(observation)
            except Failure:
                pass
            # Private output never reaches the console, including failed Dockerfile logs.
            for name in ("build.log", "daemon.log", "result.json"):
                try:
                    host.download("/var/lib/small-cloud-build/output/" + name, destination / name,
                                  10 * 1024 * 1024 if name.endswith('.log') else 65536)
                except Failure:
                    pass
        host.download("/var/lib/small-cloud-build/output/image.tar", destination / "image.tar", 500 * 1024 * 1024)
        return {"job": args.job, "output": str(destination), "builder": created}
    finally:
        # Also runs on ordinary failure, timeout and Ctrl-C. SIGKILL is covered by reconciliation.
        copied_source.unlink(missing_ok=True)
        if created is not None:
            deletion = run([sys.executable, str(HERE / "builders.py"), "delete", str(created["id"])])
            (destination / "teardown.json").write_text(deletion)


def main() -> int:
    os.umask(0o077)
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    config = commands.add_parser("configure")
    config.add_argument("--runsc-url", required=True)
    config.add_argument("--runsc-sha256", required=True)
    alerts = commands.add_parser('enable-alerts', help='Install protected SMTP settings on verified foundation hosts')
    alerts.add_argument('--smtp-config', type=Path, default=SECRET_DIR / 'monitor-smtp.json')
    spending = commands.add_parser('enable-spending', help='Install API-based spending estimation on the verified control host')
    spending.add_argument('--config', type=Path, required=True, help='JSON with optional documented opening_estimate')
    execute = commands.add_parser("build")
    execute.add_argument("--context", type=Path, required=True)
    execute.add_argument("--output", type=Path, required=True)
    execute.add_argument("--admin-cidr", required=True)
    execute.add_argument("--job", required=True)
    args = parser.parse_args()
    try:
        operation = {'configure': configure, 'build': build, 'enable-alerts': enable_alerts,
                     'enable-spending': enable_spending}[args.command]
        print(json.dumps(operation(args), indent=2))
        return 0
    except KeyboardInterrupt:
        print('Interrupted; inspect teardown evidence or independent reconciliation.', file=sys.stderr)
        return 130
    except (Failure, OSError, ValueError, subprocess.SubprocessError):
        print("ERROR: remote operation failed; inspect protected state, host health and builder reconciliation", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
