"""Staging janitor public CLI retention and ownership boundary."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = Path(__file__).parents[1] / 'artifacts.py'


class ArtifactsCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)

    def job(self, age):
        job = self.root / 'job'
        job.mkdir(mode=0o700)
        (job / '.small-cloud-build.json').write_text(json.dumps({'created_at': time.time() - age}))
        for name in ('image.tar', 'source.tar', 'admission.log', 'builder.json', 'build.log', 'daemon.log', 'result.json', 'teardown.json'):
            (job / name).write_text('fixture')
        for path in job.iterdir():
            path.chmod(0o600)
        return job

    def invoke(self):
        return subprocess.run([sys.executable, str(SCRIPT), '--root', str(self.root)],
                              text=True, capture_output=True, timeout=10)

    def test_day_old_artifacts_removed_and_logs_preserved(self):
        job = self.job(2 * 86400)
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((job / 'image.tar').exists())
        self.assertFalse((job / 'source.tar').exists())
        self.assertTrue((job / 'build.log').exists())
        self.assertTrue((job / 'admission.log').exists())
        self.assertTrue((job / 'builder.json').exists())
        self.assertTrue((job / 'daemon.log').exists())
        self.assertTrue((job / '.small-cloud-build.json').exists())

    def test_uploaded_source_enters_managed_retention_without_overwriting_a_job(self):
        # Mock the host capacity boundary while exercising the real CLI and stdin.
        launcher = ('import runpy,shutil,types; '
                    'shutil.disk_usage=lambda _: types.SimpleNamespace(free=20*1024**3); '
                    'runpy.run_path(__import__("sys").argv.pop(1),run_name="__main__")')
        command = [sys.executable, '-c', launcher, str(SCRIPT), '--root', str(self.root), '--stage', 'upload-a']
        result = subprocess.run(command, input=b'fixture source archive', capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        source = Path(json.loads(result.stdout)['source'])
        self.assertEqual(source.read_bytes(), b'fixture source archive')
        self.assertEqual(source.stat().st_mode & 0o777, 0o600)
        duplicate = subprocess.run(command, input=b'replacement', capture_output=True, timeout=10)
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertEqual(source.read_bytes(), b'fixture source archive')
        marker = source.parent / '.small-cloud-build.json'
        marker.write_text(json.dumps({'created_at': time.time() - 86400}))
        self.assertEqual(self.invoke().returncode, 0)
        self.assertFalse(source.exists())

    def test_week_old_known_files_removed_but_unrelated_data_preserved(self):
        job = self.job(8 * 86400)
        (job / 'caller-original.tar').write_text('keep')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([path.name for path in job.iterdir()], ['caller-original.tar'])
        self.assertEqual((job / 'caller-original.tar').read_text(), 'keep')

    def test_fresh_job_and_unmarked_directory_untouched(self):
        job = self.job(60)
        unrelated = self.root / 'unmarked'
        unrelated.mkdir(mode=0o700)
        (unrelated / 'image.tar').write_text('keep')
        self.assertEqual(self.invoke().returncode, 0)
        self.assertTrue((job / 'image.tar').exists())
        self.assertTrue((unrelated / 'image.tar').exists())

    def test_symlink_in_marked_directory_refuses_whole_job(self):
        job = self.job(8 * 86400)
        target = self.root / 'original'
        target.write_text('keep')
        (job / 'image.tar').unlink()
        (job / 'image.tar').symlink_to(target)
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((job / 'build.log').exists())
        self.assertEqual(target.read_text(), 'keep')

    def test_hardlink_refused_without_removing_other_files(self):
        job = self.job(8 * 86400)
        os.link(job / 'image.tar', self.root / 'original-image.tar')
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertTrue((job / 'build.log').exists())
        self.assertTrue((self.root / 'original-image.tar').exists())

    def test_oversized_marker_refused_without_partial_cleanup(self):
        job = self.job(8 * 86400)
        (job / '.small-cloud-build.json').write_text(' ' * 4097)
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertTrue((job / 'image.tar').exists())

    def test_unprotected_root_refused(self):
        self.job(8 * 86400)
        self.root.chmod(0o755)
        self.assertNotEqual(self.invoke().returncode, 0)

    def test_more_than_256_expired_jobs_do_not_block_retention(self):
        for number in range(300):
            job = self.job(8 * 86400)
            job.rename(self.root / f'job-{number}')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['removed_files'], 300 * 9)
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
