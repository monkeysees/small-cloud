"""Stored-release retention through the operator CLI and registry process boundary."""
from contextlib import redirect_stdout, nullcontext
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / 'releases.py'
sys.path.insert(0, str(SCRIPT.parent))


class ReleasesCLI(unittest.TestCase):
    def test_current_image_survives_cleanup_and_retired_manifest_is_removed(self):
        spec = importlib.util.spec_from_file_location('releases_cli', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'image.tar'
            archive.write_bytes(b'fixture archive handled by skopeo')
            archive.chmod(0o600)
            calls = []
            requests = []
            def request(req, **kwargs):
                requests.append(req.method)
                return nullcontext(SimpleNamespace(headers={'Docker-Content-Digest': 'sha256:' + 'a' * 64}))
            def process(argv, **kwargs):
                calls.append(list(argv))
                if 'copy' in argv:
                    Path(argv[argv.index('--digestfile') + 1]).write_text('sha256:' + 'a' * 64)
                return subprocess.CompletedProcess(argv, 0, '')
            def invoke(*args):
                with patch.object(sys, 'argv', ['releases', '--root', str(root / 'releases'), *args]), redirect_stdout(io.StringIO()) as output:
                    code = module.main()
                self.assertEqual(code, 0, output.getvalue())
                return json.loads(output.getvalue())
            with patch.object(module.os, 'geteuid', return_value=0), patch.object(module.subprocess, 'run', side_effect=process), \
                    patch.object(module.urllib.request, 'urlopen', side_effect=request), \
                    patch.object(shutil, 'disk_usage', return_value=SimpleNamespace(free=20 * 1024**3)):
                with patch.object(shutil, 'disk_usage', return_value=SimpleNamespace(free=1024**3)):
                    with self.assertRaisesRegex(ValueError, 'storage pressure'):
                        invoke('publish', 'tool-a', 'release-a', str(archive))
                self.assertEqual(invoke('list')['releases'], [])
                invoke('publish', 'tool-a', 'release-a', str(archive))
                with patch.object(module.time, 'time', return_value=time.time() + 90000):
                    self.assertEqual(invoke('prune')['removed'], 0)
                invoke('retire', 'tool-a', 'release-a')
                self.assertEqual(invoke('prune')['removed'], 0)
                def failed_gc(argv, **kwargs):
                    if 'garbage-collect' in argv:
                        raise subprocess.CalledProcessError(1, argv)
                    return process(argv, **kwargs)
                with patch.object(module.time, 'time', return_value=time.time() + 90000), \
                        patch.object(module.subprocess, 'run', side_effect=failed_gc):
                    with self.assertRaises(subprocess.CalledProcessError):
                        invoke('prune')
                self.assertEqual(calls[-1], ['systemctl', 'start', 'docker-registry.service'])
                self.assertEqual(len(invoke('list')['releases']), 1)
                with patch.object(module.time, 'time', return_value=time.time() + 90000):
                    self.assertEqual(invoke('prune')['removed'], 1)
                self.assertEqual(requests, ['HEAD', 'DELETE', 'HEAD', 'DELETE'])
