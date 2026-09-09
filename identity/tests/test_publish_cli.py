"""Publishing acceptance at the creator CLI seam."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class UploadAcceptance(unittest.TestCase):
    def test_dry_run_applies_ignore_and_unconditional_secret_exclusions(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / 'app'
            source.mkdir()
            (source / 'Dockerfile').write_text('FROM scratch\n')
            (source / 'main.txt').write_text('hello')
            (source / '.env').write_text('CONFIDENTIAL=value')
            (source / 'ignored.txt').write_text('not uploaded')
            (source / '.dockerignore').write_text('*.txt\n!main.txt\n!.env\n')
            result = subprocess.run([sys.executable, '-m', 'identity.cli', 'app', 'deploy', str(source),
                '--name', 'example', '--description', '', '--dry-run', '--json'],
                env={**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'config'),
                     'XDG_STATE_HOME': str(home / 'state')}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(result.stdout)['data']
            self.assertEqual(data['included'], ['.dockerignore', 'Dockerfile', 'main.txt'])
            self.assertEqual(data['excluded'], ['.env', 'ignored.txt'])
            self.assertIsNone(json.loads(result.stdout)['request_id'])

    def test_ignore_star_does_not_cross_directory_separator(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / 'app'
            (source / 'nested').mkdir(parents=True)
            (source / 'Dockerfile').write_text('FROM scratch\n')
            (source / 'nested' / 'keep.txt').write_text('keep')
            (source / '.dockerignore').write_text('*.txt\n')
            result = subprocess.run([sys.executable, '-m', 'identity.cli', 'app', 'deploy', str(source),
                '--name', 'example', '--description', '', '--dry-run', '--json'],
                env={**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'config'),
                     'XDG_STATE_HOME': str(home / 'state')}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('nested/keep.txt', json.loads(result.stdout)['data']['included'])

    def test_dry_run_rejects_platform_config_hidden_by_ignore(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / 'app'
            (source / '.config' / 'small-cloud').mkdir(parents=True)
            (source / 'Dockerfile').write_text('FROM scratch\n')
            (source / '.dockerignore').write_text('.config\n')
            (source / '.config' / 'small-cloud' / 'credentials').write_text('secret')
            result = subprocess.run([sys.executable, '-m', 'identity.cli', 'app', 'deploy', str(source),
                '--name', 'example', '--description', '', '--dry-run', '--json'],
                env={**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'config'),
                     'XDG_STATE_HOME': str(home / 'state')}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)['error']['code'], 'UPLOAD_REJECTED')

    def test_docker_patterns_negation_classes_and_recursive_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / 'app'
            source.mkdir()
            entries = ['Dockerfile', 'cache/drop', 'cache/keep.txt', 'deep/cache/drop',
                       'a.log', 'deep/a.log', 'item1', 'itemA', 'literal*', '#literal']
            for name in entries:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('content')
            (source / '.dockerignore').write_text(
                '\ufeff# comment\n**/cache\n!cache/keep.txt\n**/*.log\nitem[0-9]\nliteral\\*\n\\#literal\n')
            result = subprocess.run([sys.executable, '-m', 'identity.cli', 'app', 'deploy', str(source),
                '--name', 'example', '--description', '', '--dry-run', '--json'],
                env={**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'config'),
                     'XDG_STATE_HOME': str(home / 'state')}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)['data']['included'],
                             ['.dockerignore', 'Dockerfile', 'cache/keep.txt', 'itemA'])

    def test_dry_run_rejects_symlinks_hardlinks_special_files_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / 'app'
            source.mkdir()
            (source / 'Dockerfile').write_text('FROM scratch\n')
            secret = home / 'credential'
            secret.write_text('secret')
            candidate = source / 'candidate'
            for kind in ('symlink', 'hardlink', 'fifo', 'oversize'):
                with self.subTest(kind=kind):
                    if kind == 'symlink':
                        candidate.symlink_to(secret)
                    elif kind == 'hardlink':
                        os.link(secret, candidate)
                    elif kind == 'fifo':
                        os.mkfifo(candidate)
                    else:
                        with candidate.open('wb') as stream:
                            stream.truncate(100 * 1024 * 1024 + 1)
                    result = subprocess.run([sys.executable, '-m', 'identity.cli', 'app', 'deploy', str(source),
                        '--name', 'example', '--description', '', '--dry-run', '--json'],
                        env={**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'config'),
                             'XDG_STATE_HOME': str(home / 'state')}, capture_output=True, text=True,
                        timeout=10)
                    candidate.unlink()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(json.loads(result.stdout)['error']['code'], 'UPLOAD_REJECTED')

    def test_embedded_doublestar_obeys_docker_directory_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / 'app'
            source.mkdir()
            for name in ('Dockerfile', 'ab', 'axb'):
                (source / name).write_text('content')
            (source / '.dockerignore').write_text('a**b\n')
            result = subprocess.run([sys.executable, '-m', 'identity.cli', 'app', 'deploy', str(source),
                '--name', 'example', '--description', '', '--dry-run', '--json'],
                env={**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'config'),
                     'XDG_STATE_HOME': str(home / 'state')}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)['data']['included'],
                             ['.dockerignore', 'Dockerfile', 'axb'])

    def test_dry_run_rejects_config_overlap_and_excess_file_count(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / 'app'
            source.mkdir()
            (source / 'Dockerfile').write_text('FROM scratch\n')
            environment = {**os.environ, 'HOME': str(home),
                           'XDG_CONFIG_HOME': str(source / 'configuration'),
                           'XDG_STATE_HOME': str(home / 'state')}
            command = [sys.executable, '-m', 'identity.cli', 'app', 'deploy', str(source),
                       '--name', 'example', '--description', '', '--dry-run', '--json']
            overlap = subprocess.run(command, env=environment, capture_output=True, text=True)
            self.assertNotEqual(overlap.returncode, 0)
            self.assertEqual(json.loads(overlap.stdout)['error']['code'], 'UPLOAD_REJECTED')
            environment['XDG_CONFIG_HOME'] = str(home / 'config')
            for index in range(10000):
                (source / f'file-{index}').touch()
            oversize = subprocess.run(command, env=environment, capture_output=True, text=True)
            self.assertNotEqual(oversize.returncode, 0)
            self.assertEqual(json.loads(oversize.stdout)['error']['code'], 'UPLOAD_REJECTED')
