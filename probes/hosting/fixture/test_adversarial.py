"""The probe CLI must report the address that its socket actually tests."""
from contextlib import redirect_stdout, nullcontext
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
import adversarial


class RebindingCLI(unittest.TestCase):
    def test_rebinding_report_matches_the_actual_socket_destination(self):
        connected = []
        class Socket:
            def settimeout(self, value): pass
            def connect(self, address):
                connected.append(address[0])
                if address[0] == '10.42.0.2': raise TimeoutError()
            def close(self): pass
        public = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 80))
        private = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.42.0.2', 80))
        records = iter([[public], [private], [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('::1',443))]])
        opener = SimpleNamespace(open=lambda *args, **kwargs: nullcontext(SimpleNamespace(status=200)))
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            config.write_text(json.dumps({'targets': [], 'nonce': 'fixture', 'public_origin': 'https://fixture.invalid',
                'private_proxy': 'http://10.42.0.2:18000', 'rebind_domain': 'fixture.invalid',
                'public_ipv4': '8.8.8.8', 'private_ipv4': '10.42.0.2'}))
            with patch.object(sys, 'argv', ['adversarial', '--config', str(config), '--phase', 'build']), \
                    patch.object(socket, 'getaddrinfo', side_effect=lambda *a, **kw: next(records)), \
                    patch.object(socket, 'gethostbyname', return_value='10.42.0.2'), \
                    patch.object(socket, 'socket', return_value=Socket()), \
                    patch.object(adversarial.urllib.request, 'build_opener', return_value=opener), \
                    patch.object(adversarial.time, 'sleep'), redirect_stdout(io.StringIO()) as output:
                adversarial.main()
            report = json.loads(output.getvalue())
            self.assertTrue(report['rebind_pass'])
            self.assertEqual([row['resolved'] for row in report['rebind']], connected[:2])


if __name__ == '__main__': unittest.main()
