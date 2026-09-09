"""Exercise the trusted source extraction boundary with real tar archives."""
import importlib.util
import io
import json
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('build_worker', Path(__file__).resolve().parents[1] / 'builder/worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class SourceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.build = self.root / 'build'
        self.build.mkdir()
        self.archive = self.root / 'context.tar'
        self.root_patch = patch.object(worker, 'ROOT', self.build)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def write_archive(self, members):
        with tarfile.open(self.archive, 'w') as archive:
            for name, content, mode, kind in members:
                entry = tarfile.TarInfo(name)
                entry.mode = mode
                entry.type = kind
                if kind == tarfile.SYMTYPE:
                    entry.linkname = '../../outside'
                elif kind == tarfile.REGTYPE:
                    entry.size = len(content)
                archive.addfile(entry, io.BytesIO(content) if kind == tarfile.REGTYPE else None)

    def prepare(self):
        worker.prepare(self.archive, ['203.0.113.10'])

    def test_ordinary_source_read_and_execute_bits_survive_without_special_bits(self):
        self.write_archive([
            ('Dockerfile', b'FROM scratch\nCOPY app /app\n', 0o644, tarfile.REGTYPE),
            ('app', b'#!/bin/sh\nexit 0\n', 0o6755, tarfile.REGTYPE),
        ])
        self.prepare()
        self.assertEqual((self.build / 'context/app').read_bytes(), b'#!/bin/sh\nexit 0\n')
        self.assertEqual(stat.S_IMODE((self.build / 'context/Dockerfile').stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE((self.build / 'context/app').stat().st_mode), 0o755)

    def test_parent_traversal_is_refused_without_writing_outside_context(self):
        self.write_archive([('../outside', b'bad', 0o644, tarfile.REGTYPE)])
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.build / 'outside').exists())

    def test_archive_link_cannot_redirect_extraction(self):
        self.write_archive([('escape', b'', 0o777, tarfile.SYMTYPE)])
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.build / 'context/escape').is_symlink())

    def test_platform_configuration_and_dotenv_are_refused(self):
        for name in ('.env', '.env.production', '.config/small-cloud/token', '.local/state/small-cloud/key'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                build = Path(temporary)
                self.write_archive([(name, b'fixture', 0o600, tarfile.REGTYPE)])
                with patch.object(worker, 'ROOT', build), self.assertRaises(ValueError):
                    self.prepare()
                self.assertFalse((build / 'context' / name).exists())

    def test_duplicate_normalized_path_does_not_overwrite_first_file(self):
        self.write_archive([
            ('Dockerfile', b'first', 0o644, tarfile.REGTYPE),
            ('./Dockerfile', b'second', 0o644, tarfile.REGTYPE),
        ])
        with self.assertRaises((ValueError, FileExistsError)):
            self.prepare()
        self.assertEqual((self.build / 'context/Dockerfile').read_bytes(), b'first')


class TerminationEvidenceTests(unittest.TestCase):
    def test_cleanup_before_execution_confirms_zero_charge(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'output').mkdir()
            with patch.object(worker, 'ROOT', root), patch.object(worker.subprocess, 'check_output', return_value=''):
                worker.terminate()
            self.assertEqual(json.loads((root / 'output/accounting.json').read_text()),
                             {'terminated': True, 'duration_seconds': 0})

    def test_termination_receipt_includes_execution_and_is_not_retimed_on_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'output'
            output.mkdir()
            (output / 'execution.json').write_text('{"monotonic": 100}')
            cgroup = root / 'cgroups/small-cloud-build.slice'
            cgroup.mkdir(parents=True)
            (cgroup / 'cgroup.events').write_text('populated 0\n')
            def path(value):
                return root / 'cgroups' if value == '/sys/fs/cgroup' else Path(value)
            with patch.object(worker, 'ROOT', root), patch.object(worker, 'Path', side_effect=path), \
                    patch.object(worker.subprocess, 'check_output', return_value='/small-cloud-build.slice'), \
                    patch.object(worker.time, 'monotonic', return_value=112.01):
                worker.terminate()
            self.assertEqual((cgroup / 'cgroup.kill').read_text(), '1\n')
            receipt = json.loads((output / 'accounting.json').read_text())
            self.assertTrue(receipt['terminated'])
            self.assertAlmostEqual(receipt['duration_seconds'], 12.01)
            with patch.object(worker, 'ROOT', root):
                worker.terminate()
            self.assertEqual(json.loads((output / 'accounting.json').read_text()), receipt)

    def test_unconfirmed_group_cannot_issue_a_termination_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'output').mkdir()
            (root / 'output/execution.json').write_text('{"monotonic": 100}')
            cgroup = root / 'cgroups/small-cloud-build.slice'
            cgroup.mkdir(parents=True)
            (cgroup / 'cgroup.events').write_text('populated 1\n')
            def path(value):
                return root / 'cgroups' if value == '/sys/fs/cgroup' else Path(value)
            with patch.object(worker, 'ROOT', root), patch.object(worker, 'Path', side_effect=path), \
                    patch.object(worker.subprocess, 'check_output', return_value='/small-cloud-build.slice'), \
                    patch.object(worker.time, 'monotonic', side_effect=[700, 706]):
                with self.assertRaises(RuntimeError):
                    worker.terminate()
            self.assertFalse((root / 'output/accounting.json').exists())


if __name__ == '__main__':
    unittest.main()
