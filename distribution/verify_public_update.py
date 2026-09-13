"""Verify real public HTTPS replacement from an installed, undistributed fixture."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', type=Path)
    parser.add_argument('production', type=Path)
    args = parser.parse_args()
    expected = args.production.read_bytes()
    with tempfile.TemporaryDirectory() as temporary:
        home = Path(temporary).resolve()
        executable = home / 'installed bin' / 'small-cloud'
        executable.parent.mkdir()
        shutil.copy2(args.fixture, executable)
        assert executable.read_bytes() != expected, 'Acceptance needs distinct source and destination artifacts.'
        env = {**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'config'),
               'XDG_STATE_HOME': str(home / 'state'), 'PATH': '/nonexistent',
               'SMALL_CLOUD_TEST_ORIGIN': 'https://small-cloud.monkeysees.one'}
        for key in ('PYTHONPATH', 'PYTHONHOME', 'SMALL_CLOUD_TEST_EXECUTABLE'):
            env.pop(key, None)
        preserved = [home / '.profile', home / '.bashrc', home / '.zshrc',
                     home / '.config/fish/config.fish', home / 'state/small-cloud/acceptance-marker']
        for path in preserved:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('preserve this acceptance marker\n')
        before = {str(path.relative_to(home)): path.read_bytes() for path in home.rglob('*')
                  if path.is_file() and path != executable}

        def invoke(*arguments):
            result = subprocess.run([str(executable), *arguments], env=env, cwd=home,
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180)
            assert result.returncode == 0, (arguments, result.stdout, result.stderr)
            return result.stdout

        installed_version = invoke('--version').strip().removeprefix('small-cloud ')
        updated = json.loads(invoke('update', '--json', '--no-input'))
        assert updated['ok'] and updated['request_id'] is None, updated
        assert updated['data']['outcome'] == 'updated', updated
        assert updated['data']['installed_version'] == installed_version, updated
        assert executable.read_bytes() == expected, 'Public update differs from the pinned public installation.'
        resulting_version = invoke('--version').strip().removeprefix('small-cloud ')
        assert updated['data']['resulting_version'] == resulting_version, updated
        metadata = executable.stat()
        current = json.loads(invoke('update', '--json', '--no-input'))
        assert current['ok'] and current['data']['outcome'] == 'already_current', current
        assert current['data']['installed_version'] == current['data']['resulting_version'] == resulting_version
        assert executable.stat().st_ino == metadata.st_ino
        assert executable.stat().st_mtime_ns == metadata.st_mtime_ns
        assert 'Already current' in invoke('update', '--no-input')
        assert 'Explicitly update' in invoke('update', '--help')
        after = {str(path.relative_to(home)): path.read_bytes() for path in home.rglob('*')
                 if path.is_file() and path != executable}
        assert before == after, 'Update changed shell files or credential/configuration state.'
        print(json.dumps({'platform': platform.system(), 'architecture': platform.machine(),
                          'installed_version': installed_version, 'resulting_version': resulting_version,
                          'sha256': hashlib.sha256(expected).hexdigest(),
                          'public_https_replacement': 'passed', 'public_already_current': 'passed',
                          'no_python_on_path': True, 'shell_and_state_preserved': True,
                          'source': 'installed undistributed fixture; replacement is the public production artifact'}))


if __name__ == '__main__':
    main()
