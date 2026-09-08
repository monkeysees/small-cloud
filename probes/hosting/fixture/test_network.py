"""Probe CLI acceptance against real, local TCP listeners; no sandbox claim."""

import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest


PROBE = Path(__file__).resolve().parents[1] / 'network.py'


class ProbeCLI(unittest.TestCase):
    def invoke(self, port, expected):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'targets.json'
            config.write_text(json.dumps({'targets': [{
                'name': 'local-canary', 'host': '127.0.0.1', 'port': port,
                'build': expected, 'runtime': expected, 'control_verified': True,
            }]}))
            result = subprocess.run([
                sys.executable, str(PROBE), 'check', '--config', str(config), '--strict',
            ], capture_output=True, text=True, timeout=10)
            return result.returncode, json.loads(result.stdout)['checks'][0]

    def test_allowed_listener_is_reachable(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            status, check = self.invoke(listener.getsockname()[1], 'allow')
        self.assertEqual(status, 0)
        self.assertEqual(check['result'], 'pass')

    def test_forbidden_listener_fails_even_without_an_http_body(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            status, check = self.invoke(listener.getsockname()[1], 'deny')
        self.assertEqual(status, 1)
        self.assertEqual(check['result'], 'fail')

    def test_absent_service_never_passes_denial(self):
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            status, check = self.invoke(reserved.getsockname()[1], 'deny')
        self.assertEqual(status, 1)
        self.assertEqual(check['result'], 'inconclusive')
        self.assertEqual(check['observed'], 'refused')


if __name__ == '__main__':
    unittest.main()
