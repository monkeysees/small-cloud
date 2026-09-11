"""App preparation through the CLI, with no Docker or reachable cloud service."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest


class AppCheckAcceptance(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.source = self.home / 'app'
        self.source.mkdir()
        self.listener = socket.socket()
        self.addCleanup(self.listener.close)
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.listener.settimeout(0.05)
        self.environment = {**os.environ, 'HOME': str(self.home),
            'XDG_CONFIG_HOME': str(self.home / 'config'), 'XDG_STATE_HOME': str(self.home / 'state'),
            'PATH': '/nonexistent',
            'SMALL_CLOUD_TEST_ORIGIN': f'https://127.0.0.1:{self.listener.getsockname()[1]}'}

    def cli(self, *args):
        executable = os.environ.get('SMALL_CLOUD_TEST_BINARY')
        command = [executable] if executable else [sys.executable, '-m', 'identity.tests.cli']
        result = subprocess.run([*command, *args],
            env=self.environment, capture_output=True, text=True, timeout=10)
        # Even a TLS connection would be observable; checking must never contact the service.
        with self.assertRaises(socket.timeout):
            connection, _ = self.listener.accept()
            connection.close()
        self.assertFalse((self.home / 'state').exists())
        self.assertFalse((self.home / 'config').exists())
        return result

    def test_valid_source_reports_local_scope_exclusions_and_limits(self):
        (self.source / 'Dockerfile').write_text('FROM scratch\n')
        (self.source / 'main.txt').write_text('hello')
        (self.source / '.env').write_text('CONFIDENTIAL=do-not-print')
        (self.source / 'ignored.txt').write_text('not uploaded')
        (self.source / '.dockerignore').write_text('*.txt\n!main.txt\n!.env\n')
        before = {path.name: path.read_bytes() for path in self.source.iterdir()}
        result = self.cli('app', 'check', str(self.source), '--json', '--no-input',
                          '--request-id', 'not-a-mutation', '--workspace', 'unavailable')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        envelope = json.loads(result.stdout)
        self.assertIsNone(envelope['request_id'])
        data = envelope['data']
        self.assertEqual(data['included'], ['.dockerignore', 'Dockerfile', 'main.txt'])
        self.assertEqual(data['excluded'], ['.env', 'ignored.txt'])
        self.assertEqual(data['total_bytes'], 40)
        self.assertEqual(data['limits'], {'max_bytes': 104857600, 'max_files': 10000})
        self.assertIn('Dockerfile', ' '.join(data['verified_locally']))
        self.assertIn('readiness', ' '.join(data['requires_remote']))
        self.assertIn('feasibility', data['summary'])
        self.assertNotIn('do-not-print', result.stdout + result.stderr)
        human = self.cli('app', 'check', str(self.source))
        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertIn('Local source check passed', human.stdout)
        self.assertIn('Requires remote', human.stdout)
        self.assertNotIn('do-not-print', human.stdout + human.stderr)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.source.iterdir()})

    def test_invalid_source_returns_actionable_errors_without_remote_work(self):
        result = self.cli('app', 'check', str(self.source), '--json')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        envelope = json.loads(result.stdout)
        self.assertIsNone(envelope['request_id'])
        self.assertEqual(envelope['error']['code'], 'UPLOAD_REJECTED')
        self.assertIn('Dockerfile', envelope['error']['message'])
        self.assertEqual(envelope['error']['details']['next_command'], 'small-cloud guide runtime')
        self.assertEqual(envelope['error']['details']['limits']['max_files'], 10000)
        human = self.cli('app', 'check', str(self.source))
        self.assertEqual(human.returncode, 2)
        self.assertEqual(human.stdout, '')
        self.assertIn('Dockerfile', human.stderr)
        self.assertIn('small-cloud guide runtime', human.stderr)

    def test_runtime_guide_is_discoverable_offline_and_examples_can_be_checked(self):
        import shlex
        catalog = self.cli('catalog', 'app', 'check', '--json')
        definition = json.loads(catalog.stdout)['data']['commands'][0]
        self.assertEqual(definition['guide'], 'runtime')
        help_result = self.cli('app', 'check', '--help')
        self.assertIn('small-cloud guide runtime', help_result.stdout)
        listing = self.cli('guide', '--json')
        self.assertIn('runtime', [item['topic'] for item in json.loads(listing.stdout)['data']['guides']])
        result = self.cli('guide', 'runtime', '--json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        content = json.loads(result.stdout)['data']['content']
        for requirement in ('Dockerfile', '0.0.0.0', 'PORT', 'GET /_small-cloud/ready', '200', '120 seconds',
                            'DATABASE_URL', 'TLS', 'runtime secrets', 'disposable', '.dockerignore',
                            '100 MiB', '10,000', 'feasibility', 'no local Docker'):
            self.assertIn(requirement, content)
        # A remote build remains necessary, even for a syntactically invalid Dockerfile.
        (self.source / 'Dockerfile').write_text('NOT A DOCKERFILE INSTRUCTION\n')
        examples = []
        for line in content.splitlines():
            if line.startswith('small-cloud app check '):
                examples.append(line)
                args = shlex.split(line)[1:]
                args[2] = str(self.source)
                checked = self.cli(*args)
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                self.assertIn('not verified', checked.stdout)
        self.assertEqual(len(examples), 2)

    def test_check_preserves_upload_rejections_and_never_reads_credentials_into_output(self):
        secret = self.home / 'credential'
        secret.write_text('confidential-canary-never-display')
        for kind in ('symlink', 'hardlink', 'fifo', 'oversize', 'file-count', 'platform-storage',
                     'credential-overlap', 'invalid-ignore', 'missing-folder', 'not-directory'):
            with self.subTest(kind=kind):
                source = self.source / kind
                source.mkdir()
                (source / 'Dockerfile').write_text('FROM scratch\n')
                candidate = source / 'candidate'
                if kind == 'symlink':
                    candidate.symlink_to(secret)
                elif kind == 'hardlink':
                    os.link(secret, candidate)
                elif kind == 'fifo':
                    os.mkfifo(candidate)
                elif kind == 'oversize':
                    with candidate.open('wb') as stream:
                        stream.truncate(104857601)
                elif kind == 'file-count':
                    for index in range(10000):
                        (source / f'file-{index}').touch()
                elif kind == 'platform-storage':
                    (source / '.config' / 'small-cloud').mkdir(parents=True)
                    (source / '.config' / 'small-cloud' / 'credentials').write_text(secret.read_text())
                    (source / '.dockerignore').write_text('.config\n')
                elif kind == 'credential-overlap':
                    self.environment['XDG_STATE_HOME'] = str(source / 'state')
                elif kind == 'invalid-ignore':
                    (source / '.dockerignore').write_text('[')
                elif kind == 'missing-folder':
                    source = source / 'missing'
                elif kind == 'not-directory':
                    source = source / 'Dockerfile'
                checked = self.cli('app', 'check', str(source), '--json')
                self.assertEqual(checked.returncode, 2, checked.stdout + checked.stderr)
                data = json.loads(checked.stdout)
                self.assertIsNone(data['request_id'])
                self.assertIsNone(data['data'])
                self.assertEqual(data['error']['code'], 'UPLOAD_REJECTED')
                self.assertIn('next_command', data['error']['details'])
                self.assertNotIn(secret.read_text(), checked.stdout + checked.stderr)
                self.environment['XDG_STATE_HOME'] = str(self.home / 'state')

    def test_mandatory_exclusions_and_terminal_safe_paths_match_deploy_dry_run(self):
        (self.source / 'Dockerfile').write_text('FROM scratch\n')
        for name in ('.git', '.small-cloud', 'nested'):
            (self.source / name).mkdir()
        for name in ('.git/config', '.small-cloud/credentials', 'nested/.env.production'):
            (self.source / name).write_text('confidential-canary-never-display')
        (self.source / '.dockerignore').write_text('*\n!**\n')
        (self.source / 'escape\x1b[31m').write_text('ordinary source content')
        checked = self.cli('app', 'check', str(self.source), '--json')
        dry_run = self.cli('app', 'deploy', str(self.source), '--name', 'example', '--dry-run', '--json')
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertEqual(dry_run.returncode, 0, dry_run.stdout + dry_run.stderr)
        report = json.loads(checked.stdout)['data']
        self.assertEqual(report['excluded'], ['.git', '.small-cloud', 'nested/.env.production'])
        for key in ('included', 'excluded', 'total_bytes'):
            self.assertEqual(report[key], json.loads(dry_run.stdout)['data'][key])
        human = self.cli('app', 'check', str(self.source))
        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertNotIn('\x1b', human.stdout)
        self.assertIn('escape\\u001b[31m', human.stdout)
        self.assertNotIn('confidential-canary-never-display', human.stdout + checked.stdout)
