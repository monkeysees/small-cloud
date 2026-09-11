"""Exercise the installed native release and a separate frozen HTTPS fixture CLI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from identity.tests.test_identity_cli import IdentityAcceptance
from identity.tests.test_app_check_cli import AppCheckAcceptance


class FrozenIdentity(IdentityAcceptance):
    def start_platform(self):
        super().start_platform()
        self.env.pop('PYTHONPATH', None)
        self.env['PATH'] = '/nonexistent-small-cloud-acceptance-path'
        if os.environ.get('SMALL_CLOUD_TEST_NATIVE_KEYRING') == '1':
            self.env.pop('PYTHON_KEYRING_BACKEND', None)
            # Native credential services belong to the runner's real OS account.
            self.env['HOME'] = os.environ['HOME']

    def test_packaged_credential_roundtrip(self):
        self.operator('bootstrap', 'admin@example.test')
        self.start_platform()
        identity = self.login(cwd=self.home)
        saved = next((self.home / 'state/small-cloud').glob('*.json'))
        metadata = json.loads(saved.read_text())
        expected = 'keyring' if os.environ.get('SMALL_CLOUD_TEST_NATIVE_KEYRING') == '1' else 'file'
        self.assertEqual(metadata['storage'], expected)
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(self.cli('auth', 'status', cwd=self.home).stdout)['data'], identity)
        # Exact-origin metadata is checked before any credential can be transmitted.
        metadata['endpoint'] = 'https://other.example.test'
        saved.write_text(json.dumps(metadata))
        self.assertEqual(self.cli('auth', 'status', cwd=self.home).returncode, 3)
        metadata['endpoint'] = self.endpoint
        saved.write_text(json.dumps(metadata))
        self.assertEqual(self.cli('auth', 'logout', cwd=self.home).returncode, 0)
        self.assertFalse(saved.exists())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('fixture', type=Path)
    args = parser.parse_args()
    binary, fixture = args.binary.resolve(), args.fixture.resolve()
    with tempfile.TemporaryDirectory() as temporary:
        home = Path(temporary).resolve()
        destination = home / 'installed bin'
        downloads = home / 'downloads'
        downloads.mkdir()
        shutil.copy2(binary, downloads / binary.name)
        shutil.copy2(binary.with_suffix('.sha256'), downloads / (binary.name + '.sha256'))
        shim = home / 'shim'
        shim.mkdir()
        # The download boundary serves the just-built bytes; installer logic is unchanged.
        curl = shim / 'curl'
        curl.write_text('''#!/bin/sh
set -eu
url=
output=
while [ "$#" -gt 0 ]; do
    case "$1" in
        https://*) url=$1 ;;
        -o) shift; output=$1 ;;
    esac
    shift
done
cp "$SMALL_CLOUD_TEST_DOWNLOADS/${url##*/}" "$output"
''')
        curl.chmod(0o755)
        env = {**os.environ, 'HOME': str(home), 'XDG_STATE_HOME': str(home / 'state'),
               'XDG_CONFIG_HOME': str(home / 'config'), 'SMALL_CLOUD_INSTALL_DIR': str(destination),
               'SMALL_CLOUD_TEST_DOWNLOADS': str(downloads), 'PATH': str(shim) + ':/usr/bin:/bin:/usr/sbin:/sbin'}
        env.pop('PYTHONPATH', None)
        env.pop('PYTHONHOME', None)
        for name in ('.profile', '.bashrc', '.zshrc'):
            (home / name).write_text('# unchanged\n')
        installed = subprocess.run(['/bin/sh', str(ROOT / 'install.sh')], env=env,
                                   capture_output=True, text=True)
        assert installed.returncode == 0, (installed.stdout, installed.stderr)
        assert 'PATH' in installed.stdout
        executable = destination / 'small-cloud'
        assert executable.read_bytes() == binary.read_bytes()
        assert not (home / 'state').exists(), 'Installation must not start login or create credentials'
        for name in ('.profile', '.bashrc', '.zshrc'):
            assert (home / name).read_text() == '# unchanged\n'
        env['PATH'] = '/nonexistent-small-cloud-acceptance-path'
        env['SMALL_CLOUD_ENDPOINT'] = 'https://attacker.example.test'
        env['SMALL_CLOUD_TEST_ORIGIN'] = 'https://attacker.example.test'
        config = home / 'config/small-cloud'
        config.mkdir(parents=True)
        (config / 'config.json').write_text('{"endpoint":"https://attacker.example.test"}')
        source = home / 'app'
        source.mkdir()
        (source / 'Dockerfile').write_text('FROM scratch\n')
        (source / '.env').write_text('TOKEN=never-display-this-value\n')
        invalid_source = home / 'invalid-app'
        invalid_source.mkdir()
        checks = [((), 0), (('--help',), 0), (('--version',), 0),
                  (('catalog', '--json'), 0), (('guide', 'getting-started'), 0),
                  (('guide', 'runtime'), 0), (('catalog', 'app', 'check', '--json'), 0),
                  (('app', 'check', str(source)), 0), (('app', 'check', str(source), '--json'), 0),
                  (('app', 'check', str(invalid_source), '--json'), 2),
                  (('auth', 'status', '--json'), 3),
                  (('--endpoint', 'https://attacker.example.test', 'auth', 'status', '--json'), 2),
                  (('--endpoint=https://attacker.example.test', 'auth', 'status', '--json'), 2)]
        for arguments, expected in checks:
            result = subprocess.run([str(executable), *arguments], cwd=home, env=env,
                                    capture_output=True, text=True, timeout=30)
            assert result.returncode == expected, (arguments, result.stdout, result.stderr)
            if arguments[:2] == ('app', 'check'):
                assert 'never-display-this-value' not in result.stdout + result.stderr
                if '--json' in arguments:
                    report = json.loads(result.stdout)
                    assert report['request_id'] is None
                    if expected == 0:
                        assert report['data']['included'] == ['Dockerfile']
                        assert report['data']['excluded'] == ['.env']
                        assert 'not verified' in report['data']['summary']
                    else:
                        assert report['error']['code'] == 'UPLOAD_REJECTED'
                        assert report['error']['details']['next_command'] == 'small-cloud guide runtime'
                else:
                    assert 'Local source check passed' in result.stdout
                    assert 'Requires remote' in result.stdout
            if arguments == ('auth', 'status', '--json'):
                assert json.loads(result.stdout)['error']['code'] == 'AUTH_REQUIRED'
                origin_hash = hashlib.sha256(b'https://small-cloud.monkeysees.one').hexdigest()
                assert (home / 'state/small-cloud' / (origin_hash + '.lock')).exists()
        # Public HTTPS must work even where the build machine's OpenSSL CA paths do not exist.
        env['SSL_CERT_FILE'] = str(home / 'absent-ca.pem')
        env['SSL_CERT_DIR'] = str(home / 'absent-ca-directory')
        state = home / 'state/small-cloud'
        saved = state / (hashlib.sha256(b'https://small-cloud.monkeysees.one').hexdigest() + '.json')
        saved.write_text(json.dumps({'endpoint': 'https://small-cloud.monkeysees.one',
                                     'storage': 'file', 'credential': 'distribution-acceptance-invalid'}))
        saved.chmod(0o600)
        hosted = subprocess.run([str(executable), 'auth', 'status', '--json'], cwd=home, env=env,
                                capture_output=True, text=True, timeout=40)
        assert hosted.returncode == 3, (hosted.stdout, hosted.stderr)
        assert json.loads(hosted.stdout)['error']['code'] == 'AUTH_REQUIRED', hosted.stdout
        # A bad download must leave a usable installed executable in place.
        (downloads / binary.name).write_bytes(b'corrupt')
        env['PATH'] = str(shim) + ':/usr/bin:/bin:/usr/sbin:/sbin'
        refused = subprocess.run(['/bin/sh', str(ROOT / 'install.sh')], env=env, capture_output=True, text=True)
        assert refused.returncode != 0 and 'Checksum mismatch' in refused.stderr
        assert executable.read_bytes() == binary.read_bytes()
    os.environ['SMALL_CLOUD_TEST_BINARY'] = str(fixture)
    suite = unittest.TestSuite(FrozenIdentity(name) for name in (
        'test_packaged_credential_roundtrip',
        'test_split_login_saves_credential_only_after_browser_approval',
        'test_pending_split_login_can_resume_after_bounded_wait',
        'test_split_login_protects_pending_material_and_origin',
        'test_split_login_server_expiry_removes_pending_state'))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(AppCheckAcceptance))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print(json.dumps({'platform': platform.system(), 'architecture': platform.machine(),
                      'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                      'installed_checks': len(checks) + 1, 'installer_integrity': 'passed',
                      'public_https_without_system_ca_paths': 'passed',
                      'credential_storage': 'native' if os.environ.get('SMALL_CLOUD_TEST_NATIVE_KEYRING') == '1' else 'file',
                      'frozen_https_login_status_logout': 'passed',
                      'frozen_offline_app_preparation': 'passed',
                      'frozen_https_split_login_pending_expiry_protection': 'passed'}))


if __name__ == '__main__':
    main()
