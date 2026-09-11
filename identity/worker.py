"""Privileged control-host deployment worker; web requests never hold cloud authority."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import selectors
import signal
import socket
from pathlib import Path
import shlex
import sqlite3
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

from .common import Failure
from .upload import validate_archive
from . import allowance, diagnostics, lifecycle


class State:
    def __init__(self, path):
        self.path = Path(path)
        info = self.path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('Unsafe publishing database')
        self.owner = info.st_uid

    @contextmanager
    def connect(self):
        # The single-threaded worker writes journals as the identity service user.
        previous = os.geteuid()
        try:
            if previous != self.owner:
                os.seteuid(self.owner)
            db = sqlite3.connect(self.path, timeout=30, isolation_level='IMMEDIATE')
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA secure_delete=ON')
            try:
                with db:
                    yield db
            finally:
                db.close()
        finally:
            if os.geteuid() != previous:
                os.seteuid(previous)


def command(arguments, timeout=900, data=None, logs=None):
    try:
        if logs is None:
            result = subprocess.run(arguments, input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    timeout=timeout, check=False)
        else:
            with subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL) as process:
                assert process.stdout is not None
                tail = b''
                deadline = time.monotonic() + timeout
                try:
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout, selectors.EVENT_READ)
                        while selector.get_map():
                            if time.monotonic() >= deadline:
                                raise subprocess.TimeoutExpired(arguments, timeout)
                            for event, _ in selector.select(1):
                                chunk = os.read(event.fd, 65536)
                                if not chunk:
                                    selector.unregister(event.fileobj)
                                    break
                                logs.feed(chunk)
                                tail = (tail + chunk)[-65536:]
                    result = subprocess.CompletedProcess(arguments, process.wait(timeout=max(1, deadline - time.monotonic())), tail)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
        if result.returncode:
            if result.returncode == 7:
                try:
                    unstarted = json.loads(result.stdout).get('error', {}).get('code') == 'BUILD_NOT_STARTED'
                except (ValueError, AttributeError):
                    unstarted = False
                if unstarted:
                    raise Failure('BUILD_FAILED', 'Remote build could not start.', 500, execution_not_started=True)
            if result.returncode == 5:
                try:
                    capacity = json.loads(result.stdout).get('error', {}).get('code') == 'ACTIVE_CAPACITY'
                except (ValueError, AttributeError):
                    capacity = False
                if capacity:
                    raise Failure('ACTIVE_CAPACITY', 'All five active app slots are occupied.', 409, limit=5)
            raise ValueError('Operator command failed')
        if len(result.stdout) > 1024 * 1024:
            raise ValueError('Operator command output exceeds bound')
        return result.stdout
    except (subprocess.SubprocessError, OSError, ValueError):
        raise Failure('INTERNAL', 'Deployment infrastructure requires operator inspection.', 500) from None


class Infrastructure:
    """Calls only installed operator entry points and pinned runtime SSH."""
    def __init__(self, config):
        self.config = config
        self.root = Path(config.get('infra_directory', '/opt/small-cloud/infra'))
        self.runtime = str(ipaddress.IPv4Address(config.get('runtime_address', '10.42.0.3')))
        self.admin_cidr = str(ipaddress.IPv4Network(config['admin_cidr'], strict=True))
        infra_state = Path(config.get('infra_state_directory', '/root/.local/state/small-cloud/infra'))
        self.options = ['-i', str(infra_state / 'operator_ed25519'), '-o', 'BatchMode=yes',
                        '-o', 'IdentitiesOnly=yes', '-o', 'ConnectTimeout=5',
                        '-o', 'StrictHostKeyChecking=yes', '-o', 'ServerAliveInterval=15',
                        '-o', 'ServerAliveCountMax=2', '-o', 'UserKnownHostsFile=' + str(infra_state / 'known_hosts')]
        if config.get('runtime_host_key_alias'):
            self.options += ['-o', 'HostKeyAlias=' + config['runtime_host_key_alias']]
        self.staging = Path('/srv/small-cloud/source')
        self.unstarted_job = None

    def ssh(self, *arguments, data=None, timeout=900):
        return command(['ssh', *self.options, 'root@' + self.runtime, shlex.join(arguments)], timeout, data)

    def sandbox(self, *arguments):
        if arguments and arguments[0] in ('start', 'resume'):
            from .services import dependencies_ready
            dependencies_ready(self.config)
        return self.ssh('python3', '/opt/small-cloud/runtime/sandbox.py', '--config',
                        '/etc/small-cloud/runtime.json', *arguments)

    def build(self, operation, logs):
        job = operation['id']
        self.unstarted_job = job
        archive = bytes(operation['source'])
        validate_archive(archive)
        command([sys.executable, str(self.root / 'artifacts.py'), '--stage', job], data=archive)
        source = self.staging / ('upload-' + job) / 'source.tar'
        output = self.staging / job
        try:
            self.unstarted_job = None
            command([sys.executable, str(self.root / 'remote.py'), 'build', '--context', str(source),
                     '--output', str(output), '--job', job, '--admin-cidr', self.admin_cidr,
                     '--stream-build-log'], timeout=1800, logs=logs)
        except Failure as error:
            if error.details.get('execution_not_started') is True:
                self.unstarted_job = job
            raise Failure('BUILD_FAILED', 'Dockerfile build failed; inspect build logs.', 500) from None
        finally:
            source.unlink(missing_ok=True)
        result = json.loads((output / 'result.json').read_text())
        image = output / 'image.tar'
        with image.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        if (not result.get('ok') or checksum != result.get('image_archive_sha256')
                or image.stat().st_size != result.get('image_bytes')):
            raise Failure('BUILD_FAILED', 'Build artifact verification failed.', 500)
        command([sys.executable, str(self.root / 'releases.py'), 'publish', operation['app_id'], job, str(image)])
        return {'archive': str(image), 'sha256': checksum}

    def build_accounting(self, operation):
        if self.unstarted_job == operation['id']:
            return {'terminated': True, 'duration_seconds': 0}
        try:
            output = self.staging / operation['id']
            evidence = json.loads((output / 'accounting.json').read_text())
            if (evidence.get('execution_attempted') is False and evidence.get('terminated') is True
                    and evidence.get('duration_seconds') == 0):
                return evidence
            teardown = json.loads((output / 'teardown.json').read_text())
            if teardown.get('deleted') is True and isinstance(evidence, dict):
                return evidence
        except (OSError, ValueError, AttributeError):
            pass
        return {'terminated': False, 'duration_seconds': None}

    def start(self, operation, artifact, app, register):
        image = Path(artifact['archive'])
        with tarfile.open(image, mode='r:') as archive:
            manifest_file = archive.extractfile('manifest.json')
            if manifest_file is None:
                raise ValueError('Missing image manifest')
            manifest = json.loads(manifest_file.read(65537))
            if len(manifest) != 1 or manifest[0].get('RepoTags') != ['sc-artifact:build']:
                raise ValueError('Build must export exactly the platform artifact tag')
        destination = '/run/small-cloud-image-' + operation['id'] + '.tar'
        environment = '/run/small-cloud-env-' + operation['id']
        stage = 'image-transfer'
        try:
            command(['scp', *self.options, str(image), 'root@' + self.runtime + ':' + destination])
            stage = 'image-transfer-verification'
            checksum = self.ssh('sha256sum', destination).decode().split()[0]
            if checksum != artifact['sha256']:
                raise ValueError('Runtime archive checksum mismatch')
            stage = 'image-import'
            self.ssh('docker', 'load', '--input', destination)
            stage = 'image-inspection'
            # Import can normalize old image configurations; pin Docker's resulting ID.
            inspected = json.loads(self.ssh('docker', 'image', 'inspect', 'sc-artifact:build'))[0]
            image_id = inspected['Id']
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
                raise ValueError('Runtime did not return an immutable image ID')
            if inspected['Architecture'] != 'amd64' or inspected['Os'] != 'linux':
                raise ValueError('Image must target Linux amd64')
            stage = 'image-retention'
            self.sandbox('retain-image', operation['app_id'], operation['id'], image_id)
            stage = 'database-provision'
            provisioned = json.loads(command(['python3', '/opt/small-cloud/control/tool_database.py', operation['app_id']]))
            stage = 'database-credential-handoff'
            credentials = json.loads(command(['age', '--decrypt', '-i', '/srv/small-cloud/secrets/identity.age',
                                             provisioned['encrypted_credentials']]))
            register([credentials['database_url'], credentials['password']])
            stage = 'runtime-environment-handoff'
            self.ssh('python3', '-c',
                'import os,sys; fd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); '
                'os.write(fd,sys.stdin.buffer.read(5242881)); os.close(fd)', environment,
                data=json.dumps({**app.get('runtime_environment', {}), 'DATABASE_URL': credentials['database_url']}).encode())
            arguments = ['start', operation['app_id'], image_id, '--env-json', environment,
                         '--deployment', operation['id']]
            if app['container']:
                arguments.append('--candidate')
            stage = 'runtime-start'
            started = json.loads(self.sandbox(*arguments))
            return {'host': self.runtime, 'port': started['private_port'], 'container': started['container']}
        except Failure as error:
            raise Failure(error.code, error.message, error.status, **{**error.details, 'stage': stage}) from None
        except (OSError, ValueError, KeyError, IndexError):
            raise Failure('STARTUP_FAILED', 'Runtime handoff failed; inspect the deployment stage.', 500,
                          stage=stage) from None
        finally:
            try:
                self.ssh('rm', '-f', '--', destination, environment)
            except Failure:
                raise Failure('INTERNAL', 'Runtime staging cleanup requires operator inspection.', 500,
                              stage='runtime-staging-cleanup', reconciliation_required=True) from None

    def ready(self, target):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                with opener.open('http://' + target['host'] + ':' + str(target['port']) + '/_small-cloud/ready', timeout=1) as response:
                    if response.status == 200:
                        return
            except urllib.error.HTTPError:
                pass
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
            time.sleep(2)
        raise Failure('STARTUP_FAILED', 'App did not answer HTTP readiness with HTTP 200 within 120 seconds.', 500)

    def wake(self, app, register):
        if (not re.fullmatch(r'a-[0-9a-f]{24}', app['id'])
                or not re.fullmatch(r'd-[0-9a-f]{24}', app['active_deployment_id'])):
            raise Failure('STARTUP_FAILED', 'Invalid retained release requires operator inspection.', 503)
        environment = '/run/small-cloud-wake-' + app['id']
        filename = 'tool_' + hashlib.sha256(app['id'].encode()).hexdigest()[:24] + '.json.age'
        credentials = json.loads(command(['age', '--decrypt', '-i', '/srv/small-cloud/secrets/identity.age',
                                         '/srv/small-cloud/secrets/' + filename]))
        register([credentials['database_url'], credentials['password']])
        try:
            self.ssh('python3', '-c',
                'import os,sys; fd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); '
                'os.write(fd,sys.stdin.buffer.read(5242881)); os.close(fd)', environment,
                data=json.dumps({**app.get('runtime_environment', {}), 'DATABASE_URL': credentials['database_url']}).encode())
            started = json.loads(self.sandbox('resume', app['id'], app['active_deployment_id'], '--env-json', environment))
            return {'host': self.runtime, 'port': started['private_port'], 'container': started['container']}
        finally:
            self.ssh('rm', '-f', '--', environment)

    def stop(self, app):
        if not re.fullmatch(r'a-[0-9a-f]{24}', app['id']):
            raise Failure('INTERNAL', 'Invalid app identity requires operator inspection.', 500)
        self.sandbox('stop', app['id'])
        self.ssh('rm', '-f', '--', '/run/small-cloud-wake-' + app['id'])

    def promote(self, operation, app, target):
        if app['container']:
            self.sandbox('promote', operation['app_id'])
        return 'sc-' + operation['app_id'] + '-active'

    def cleanup(self, operation, app, succeeded=False):
        if not succeeded:
            name = 'sc-' + operation['app_id'] + ('-candidate' if app['container'] else '-active')
            if self.ssh('docker', 'ps', '-aq', '--filter', 'name=^/' + name + '$').strip():
                self.ssh('docker', 'rm', '-f', name)
            self.sandbox('forget-release', operation['app_id'], operation['id'])
            command([sys.executable, str(self.root / 'releases.py'), 'retire', operation['app_id'], operation['id']])
        elif app['active_deployment_id']:
            self.sandbox('forget-release', operation['app_id'], app['active_deployment_id'])
            command([sys.executable, str(self.root / 'releases.py'), 'retire', operation['app_id'], app['active_deployment_id']])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class Worker:
    def __init__(self, state, infrastructure, key=None, clock=time.time):
        self.state, self.infrastructure = state, infrastructure
        self.clock = clock
        self.registry = diagnostics.Registry(state, key or state.path.parent / 'redaction.key')

    def recover(self):
        self.registry.migrate()
        with self.state.connect() as db:
            # Never replay a build after process loss; independent builder reconciliation
            # owns termination, and the creator lock stays held for operator review.
            db.execute("UPDATE deployments SET error=?,source=NULL WHERE kind='deploy' AND state IN ('building','starting','cleaning')",
                       (json.dumps({'code': 'INTERNAL', 'message': 'Worker interrupted; operator reconciliation required.',
                                    'retryable': False, 'details': {'reconciliation_required': True}}),))
            db.execute('UPDATE deployments SET source=NULL WHERE finished IS NOT NULL')
        self.registry.maintain()

    def once(self):
        with self.state.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM deployments WHERE state='accepted' AND kind='deploy' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return False
            operation = dict(row)
            app = dict(db.execute('SELECT * FROM apps WHERE id=?', (row['app_id'],)).fetchone())
            db.execute("UPDATE deployments SET state='building' WHERE id=?", (row['id'],))
        target = None
        switched = False
        starting = False
        logs = diagnostics.Writer(self.state, self.registry, operation['id'], 'build')
        try:
            if (not re.fullmatch(r'd-[0-9a-f]{24}', operation['id'])
                    or not re.fullmatch(r'a-[0-9a-f]{24}', operation['app_id'])):
                raise Failure('INTERNAL', 'Invalid deployment identity requires operator reconciliation.', 500,
                              reconciliation_required=True)
            try:
                artifact = self.infrastructure.build(operation, logs)
            except Exception:
                self.settle_build(operation)
                raise
            self.settle_build(operation)
            with self.state.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                try:
                    lifecycle.reserve(db, app)
                except Failure as error:
                    raise Failure(error.code, error.message, 409, **error.details) from None
                db.execute("UPDATE deployments SET state='starting',source=NULL WHERE id=?", (operation['id'],))
            starting = True
            from .app_secrets import Vault
            app['runtime_environment'] = Vault(self.state).environment(app['id'])
            target = self.infrastructure.start(operation, artifact, app,
                        lambda values: self.registry.register(operation['id'], values))
            with self.state.connect() as db:
                db.execute('UPDATE deployments SET candidate_host=?,candidate_port=?,candidate_container=?,previous_container=? WHERE id=?',
                           (target['host'], target['port'], target['container'], app['container'], operation['id']))
            self.infrastructure.ready(target)
            with self.state.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                allowed = db.execute('SELECT 1 FROM apps a JOIN memberships u ON u.user_id=a.owner '
                                     'AND u.workspace_id=a.workspace_id '
                                     'WHERE a.id=? AND a.disabled=0 AND u.member=1 AND u.creator=1',
                                     (app['id'],)).fetchone()
                if not allowed:
                    raise Failure('APP_DISABLED', 'App authority changed before deployment completed.', 403)
                db.execute('UPDATE apps SET active_deployment_id=?,target_host=?,target_port=?,container=? WHERE id=?',
                           (operation['id'], target['host'], target['port'], target['container'], app['id']))
                db.execute("UPDATE apps SET runtime_state='running',runtime_error=NULL,last_http=? WHERE id=?",
                           (self.clock(), app['id']))
                db.execute("UPDATE deployments SET state='cleaning',cleanup_pending=1 WHERE id=?", (operation['id'],))
            switched = True
            container = self.infrastructure.promote(operation, app, target)
            with self.state.connect() as db:
                db.execute('UPDATE apps SET container=? WHERE id=?', (container, app['id']))
            self.infrastructure.cleanup(operation, app, succeeded=True)
            with self.state.connect() as db:
                db.execute("UPDATE deployments SET state='succeeded',finished=?,cleanup_pending=0 WHERE id=?",
                           (time.time(), operation['id']))
        except (Failure, OSError, ValueError, KeyError, TypeError, tarfile.TarError) as error:
            if switched:
                failure = Failure('INTERNAL', 'New release is serving; operator must reconcile cleanup.', 500,
                                  reconciliation_required=True)
            else:
                failure = error if isinstance(error, Failure) else Failure('STARTUP_FAILED' if starting else 'BUILD_FAILED',
                                                                          'Deployment failed; inspect build logs.', 500)
                try:
                    if not failure.details.get('reconciliation_required'):
                        self.infrastructure.cleanup(operation, app)
                except (Failure, OSError, ValueError):
                    failure = Failure('INTERNAL', 'Deployment cleanup requires operator reconciliation.', 500,
                                      reconciliation_required=True)
            with self.state.connect() as db:
                db.execute('UPDATE deployments SET state=?,finished=?,source=NULL,error=?,cleanup_pending=? WHERE id=?',
                           (('cleaning' if starting else 'building') if failure.details.get('reconciliation_required') else 'failed',
                            None if failure.details.get('reconciliation_required') else time.time(),
                            json.dumps({'code': failure.code, 'message': failure.message, 'retryable': False,
                                        'details': failure.details}), int(bool(failure.details.get('reconciliation_required'))), operation['id']))
        finally:
            logs.feed(b'', final=True)
            with self.state.connect() as db:
                db.execute('UPDATE deployments SET source=NULL WHERE id=?', (operation['id'],))
        return True

    def settle_build(self, operation):
        try:
            evidence = self.infrastructure.build_accounting(operation)
        except (OSError, ValueError):
            evidence = {}
        with self.state.connect() as db:
            allowance.settle(db, operation['id'], evidence)


def platform_redaction(registry, config):
    values = []
    paths = config.get('redaction_files', ['/root/.config/small-cloud/secrets/hetzner-token'])
    identity_config = Path(config.get('identity_config', '/etc/small-cloud/identity/server.json'))
    for path in [*(Path(value) for value in paths), identity_config]:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid not in (0, registry.state.owner) or info.st_size > 262144):
            raise ValueError('Unsafe confidential platform configuration')
        content = path.read_text()
        values.append(json.loads(content)['google_client_secret'] if path == identity_config else content.strip())
    registry.save('*', 'platform', values)


def seed_redaction(registry, config):
    platform_redaction(registry, config)
    with registry.state.connect() as db:
        apps = db.execute('SELECT a.id,COALESCE(a.active_deployment_id, '
                          '(SELECT id FROM deployments WHERE app_id=a.id ORDER BY created DESC LIMIT 1)) AS deployment '
                          'FROM apps a').fetchall()
    for app in apps:
        filename = 'tool_' + hashlib.sha256(app['id'].encode()).hexdigest()[:24] + '.json.age'
        path = Path('/srv/small-cloud/secrets') / filename
        if path.exists() and app['deployment']:
            credentials = json.loads(command(['age', '--decrypt', '-i', '/srv/small-cloud/secrets/identity.age', str(path)]))
            registry.register(app['deployment'], [credentials['database_url'], credentials['password']])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--lifecycle', action='store_true', help='run idle stop/start independently of builds')
    args = parser.parse_args()
    os.umask(0o077)
    info = args.config.lstat()
    if os.geteuid() != 0 or not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
        parser.error('Worker requires root and a root-owned mode-0600 configuration')
    config = json.loads(args.config.read_text())
    stopping = False
    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with open('/run/small-cloud-' + ('lifecycle' if args.lifecycle else 'publishing') + '.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        publisher = Worker(State(config['database']), Infrastructure(config),
                           config.get('redaction_key', '/srv/small-cloud/secrets/diagnostics.key'))
        worker = lifecycle.LifecycleWorker(publisher.state, publisher.infrastructure, registry=publisher.registry) if args.lifecycle else publisher
        from .services import dependencies_ready, wait_ready
        wait_ready(lambda: dependencies_ready(config), 45)
        seed_redaction(publisher.registry, config)
        worker.recover()
        if os.environ.get('NOTIFY_SOCKET'):
            address = os.environ['NOTIFY_SOCKET']
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notification:
                notification.connect('\0' + address[1:] if address.startswith('@') else address)
                notification.sendall(b'READY=1')
        last_check = 0
        while not stopping:
            if time.monotonic() - last_check >= 5:
                wait_ready(lambda: dependencies_ready(config), 45)
                last_check = time.monotonic()
            if stopping:
                break
            worked = worker.once()
            if args.once:
                break
            if not worked:
                time.sleep(1)


if __name__ == '__main__':
    main()
