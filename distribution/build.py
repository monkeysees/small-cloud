"""Build one native standalone CLI (and, optionally, a separate test executable)."""
import argparse
import hashlib
from pathlib import Path
import platform
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', action='store_true', help='Build an internal test launcher; never publish it.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    system = {'Linux': 'linux', 'Darwin': 'macos'}[platform.system()]
    arch = {'x86_64': 'x86_64', 'aarch64': 'arm64', 'arm64': 'arm64'}[platform.machine()]
    name = 'small-cloud-fixture' if args.fixture else f'small-cloud-{system}-{arch}'
    entry = root / ('identity/tests/cli.py' if args.fixture else 'distribution/entry.py')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
                    '--name', name, '--paths', str(root), '--distpath', str(root / 'build/release'),
                    '--workpath', str(root / 'build/freeze' / name),
                    '--specpath', str(root / 'build'), '--collect-all', 'keyring',
                    '--exclude-module', 'identity.tests', str(entry)], cwd=root, check=True)
    binary = root / 'build/release' / name
    binary.with_suffix('.sha256').write_text(f'{hashlib.sha256(binary.read_bytes()).hexdigest()}  {name}\n')


if __name__ == '__main__':
    main()
