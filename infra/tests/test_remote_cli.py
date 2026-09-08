"""Operator transport seam: real processes with a local SSH executable fixture."""
import io
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cloud
import remote


SSH_FIXTURE = '''#!/usr/bin/env python3
import os,shlex,sys
command=shlex.split(sys.argv[-1])
if command[:2] != ['cat', '--']:
    raise SystemExit(2)
scenario=command[2]
if scenario == 'exact':
    os.write(1,b'\\x00fixture\\xff')
elif scenario == 'overflow':
    for _ in range(64): os.write(1,b'x'*4096)
elif scenario == 'stderr':
    for _ in range(512): os.write(2,b's'*4096)
elif scenario == 'failed':
    os.write(1,b'partial')
    os.write(2,b'fixture-confidential-diagnostic')
    raise SystemExit(1)
else:
    raise SystemExit(2)
'''


class RemoteTransportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / 'state'
        self.state.mkdir(mode=0o700)
        executable = self.root / 'ssh'
        executable.write_text(SSH_FIXTURE)
        executable.chmod(0o700)
        self.state_patch = patch.object(cloud, 'STATE_DIR', self.state)
        self.path_patch = patch.dict(os.environ, {'PATH': str(self.root) + os.pathsep + os.environ.get('PATH', '')})
        self.state_patch.start()
        self.path_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.addCleanup(self.path_patch.stop)
        self.host = remote.Host('192.0.2.1')
        self.destination = self.root / 'artifact'

    def test_download_preserves_binary_bytes_at_exact_limit_privately(self):
        expected = b'\x00fixture\xff'
        self.host.download('exact', self.destination, len(expected))
        self.assertEqual(self.destination.read_bytes(), expected)
        self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o600)
        self.assertEqual(list(self.root.glob('.download-*')), [])

    def test_oversized_download_aborts_without_replacing_existing_file(self):
        self.destination.write_bytes(b'previous verified artifact')
        with self.assertRaisesRegex(cloud.Failure, 'bound'):
            self.host.download('overflow', self.destination, 8192)
        self.assertEqual(self.destination.read_bytes(), b'previous verified artifact')
        self.assertEqual(list(self.root.glob('.download-*')), [])

    def test_stderr_flood_aborts_download_without_persisting_partial_file(self):
        with self.assertRaisesRegex(cloud.Failure, 'bound'):
            self.host.download('stderr', self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.glob('.download-*')), [])

    def test_failed_download_does_not_publish_partial_or_confidential_diagnostics(self):
        with self.assertRaises(cloud.Failure) as failure:
            self.host.download('failed', self.destination)
        self.assertNotIn('fixture-confidential-diagnostic', str(failure.exception))
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.glob('.download-*')), [])

    def test_routine_command_output_is_bounded(self):
        with self.assertRaisesRegex(cloud.Failure, 'bound'):
            remote.run([sys.executable, '-c', 'import os; os.write(1,b"x"*(2*1024*1024))'])

    def test_failed_admission_retains_private_diagnostics_without_console_disclosure(self):
        diagnostic = self.root / 'admission.log'
        with self.assertRaises(cloud.Failure) as failure:
            remote.run([sys.executable, '-c',
                        'import sys; print("fixture-private-error",file=sys.stderr); sys.exit(1)'],
                       diagnostics=diagnostic)
        self.assertEqual(diagnostic.read_text(), 'fixture-private-error\n')
        self.assertEqual(stat.S_IMODE(diagnostic.stat().st_mode), 0o600)
        self.assertNotIn('fixture-private-error', str(failure.exception))

    def test_admission_diagnostics_remain_bounded_during_stderr_flood(self):
        diagnostic = self.root / 'admission.log'
        with self.assertRaisesRegex(cloud.Failure, 'bound'):
            remote.run([sys.executable, '-c', 'import os; os.write(2,b"x"*(2*1024*1024))'],
                       diagnostics=diagnostic)
        self.assertLessEqual(diagnostic.stat().st_size, 1024 * 1024)

    def test_deadline_covers_silent_process(self):
        started = time.monotonic()
        with self.assertRaisesRegex(cloud.Failure, 'deadline'):
            remote.stream_command([sys.executable, '-c', 'import time; time.sleep(30)'],
                                  io.BytesIO(), 1024, 0.1)
        self.assertLess(time.monotonic() - started, 3)

    def test_deadline_terminates_descendant_holding_output_pipe(self):
        marker = self.root / 'escaped-child'
        child = 'import pathlib,sys,time; time.sleep(0.6); pathlib.Path(sys.argv[1]).touch()'
        parent = 'import subprocess,sys; subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]])'
        with self.assertRaisesRegex(cloud.Failure, 'deadline'):
            remote.stream_command([sys.executable, '-c', parent, child, str(marker)],
                                  io.BytesIO(), 1024, 0.1)
        time.sleep(0.8)
        self.assertFalse(marker.exists(), 'A descendant escaped process-group termination')


if __name__ == '__main__':
    unittest.main()
