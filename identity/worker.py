"""Privileged control-host deployment worker; web requests never hold cloud authority."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import ipaddress
import json
import os
import re
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


def command(arguments, timeout=900, data=None):
    try:
        result = subprocess.run(arguments, input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=timeout, check=False)
        if result.returncode:
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

    def ssh(self, *arguments, data=None, timeout=900):
        return command(['ssh', *self.options, 'root@' + self.runtime, shlex.join(arguments)], timeout, data)

    def sandbox(self, *arguments):
        return self.ssh('python3', '/opt/small-cloud/runtime/sandbox.py', '--config',
                        '/etc/small-cloud/runtime.json', *arguments)

    def build(self, operation):
        job = operation['id']
        archive = bytes(operation['source'])
        validate_archive(archive)
        command([sys.executable, str(self.root / 'artifacts.py'), '--stage', job], data=archive)
        source = self.staging / ('upload-' + job) / 'source.tar'
        output = self.staging / job
        try:
            command([sys.executable, str(self.root / 'remote.py'), 'build', '--context', str(source),
                     '--output', str(output), '--job', job, '--admin-cidr', self.admin_cidr], timeout=1800)
        except Failure:
            teardown = output / 'teardown.json'
            if not teardown.is_file() or not json.loads(teardown.read_text()).get('deleted'):
                raise Failure('INTERNAL', 'Build termination requires operator reconciliation.', 500,
                              reconciliation_required=True) from None
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

    def build_log(self, operation):
        if not re.fullmatch(r'd-[0-9a-f]{24}', operation['id']):
            return '', 0
        path = self.staging / operation['id'] / 'build.log'
        if not path.is_file():
            return '', 0
        # Leave envelope/escaping headroom inside the 1 MiB HTTP snapshot contract.
        with path.open('rb') as stream:
            content = stream.read(128 * 1024)
        dropped = max(0, path.stat().st_size - len(content))
        return content.decode('utf-8', errors='replace'), dropped

    def start(self, operation, artifact, app):
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
            stage = 'runtime-environment-handoff'
            self.ssh('python3', '-c',
                'import os,sys; fd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); '
                'os.write(fd,sys.stdin.buffer.read(65536)); os.close(fd)', environment,
                data=('DATABASE_URL=' + credentials['database_url'] + '\n').encode())
            arguments = ['start', operation['app_id'], image_id, '--env-file', environment]
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
    def __init__(self, state, infrastructure):
        self.state, self.infrastructure = state, infrastructure

    def recover(self):
        with self.state.connect() as db:
            # Never replay a build after process loss; independent builder reconciliation
            # owns termination, and the creator lock stays held for operator review.
            db.execute("UPDATE deployments SET error=?,source=NULL WHERE state IN ('building','starting','cleaning')",
                       (json.dumps({'code': 'INTERNAL', 'message': 'Worker interrupted; operator reconciliation required.',
                                    'retryable': False, 'details': {'reconciliation_required': True}}),))
            db.execute('UPDATE deployments SET source=NULL WHERE finished IS NOT NULL')
            db.execute("UPDATE deployments SET build_log='' WHERE created<?", (time.time() - 604800,))

    def once(self):
        with self.state.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM deployments WHERE state='accepted' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return False
            operation = dict(row)
            app = dict(db.execute('SELECT * FROM apps WHERE id=?', (row['app_id'],)).fetchone())
            db.execute("UPDATE deployments SET state='building' WHERE id=?", (row['id'],))
        target = None
        switched = False
        starting = False
        try:
            if (not re.fullmatch(r'd-[0-9a-f]{24}', operation['id'])
                    or not re.fullmatch(r'a-[0-9a-f]{24}', operation['app_id'])):
                raise Failure('INTERNAL', 'Invalid deployment identity requires operator reconciliation.', 500,
                              reconciliation_required=True)
            artifact = self.infrastructure.build(operation)
            with self.state.connect() as db:
                db.execute("UPDATE deployments SET state='starting',source=NULL WHERE id=?", (operation['id'],))
            starting = True
            target = self.infrastructure.start(operation, artifact, app)
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
                           ('cleaning' if failure.details.get('reconciliation_required') else 'failed',
                            None if failure.details.get('reconciliation_required') else time.time(),
                            json.dumps({'code': failure.code, 'message': failure.message, 'retryable': False,
                                        'details': failure.details}), int(bool(failure.details.get('reconciliation_required'))), operation['id']))
        finally:
            try:
                log, dropped = self.infrastructure.build_log(operation)
            except (OSError, ValueError):
                log, dropped = 'Build log could not be collected; operator inspection required.', 0
            with self.state.connect() as db:
                db.execute('UPDATE deployments SET source=NULL,build_log=?,dropped_bytes=? WHERE id=?',
                           (log, dropped, operation['id']))
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    info = args.config.lstat()
    if os.geteuid() != 0 or not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
        parser.error('Worker requires root and a root-owned mode-0600 configuration')
    config = json.loads(args.config.read_text())
    worker = Worker(State(config['database']), Infrastructure(config))
    with open('/run/small-cloud-publishing.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        worker.recover()
        while True:
            worked = worker.once()
            if args.once:
                break
            if not worked:
                time.sleep(1)


if __name__ == '__main__':
    main()
