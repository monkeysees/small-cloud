"""Operator readiness checks against real HTTP and Unix-socket endpoints."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Readiness(unittest.TestCase):
    def test_identity_requires_successful_health_response(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(503)
                self.end_headers()
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / 'identity.json'
                config.write_text(json.dumps({'origin': 'https://cloud.example.test'}))
                config.chmod(0o600)
                result = subprocess.run([sys.executable, '-m', 'identity.services', 'identity',
                    '--identity-config', str(config), '--port', str(server.server_port),
                    '--timeout', '0.2'], capture_output=True, text=True, timeout=3)
                self.assertEqual(result.returncode, 1)
                self.assertIn('identity', result.stderr)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_socket_file_or_accepting_peer_is_not_collector_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'diagnostics.sock')
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(path)
                listener.listen()
                result = subprocess.run([sys.executable, '-m', 'identity.services', 'probe',
                                         '--socket', path, '--timeout', '0.2'],
                                        capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 1)
            self.assertIn('diagnostics', result.stderr)

    def test_collector_acknowledges_probe_without_creating_app_logs(self):
        from identity.collector import Collector
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'diagnostics.sock')
            collector = Collector(path, None, None)
            stop = threading.Event()
            def serve():
                while not stop.is_set():
                    collector.poll(0.01)
            thread = threading.Thread(target=serve)
            thread.start()
            try:
                result = subprocess.run([sys.executable, '-m', 'identity.services', 'probe',
                                         '--socket', path, '--timeout', '1'],
                                        capture_output=True, text=True, timeout=3)
                self.assertEqual(result.returncode, 0, result.stderr)
            finally:
                stop.set()
                thread.join()
                collector.close()
