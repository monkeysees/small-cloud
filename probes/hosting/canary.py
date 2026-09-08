#!/usr/bin/env python3
"""Temporary controlled HTTP nonce sink and UDP authoritative DNS fixture; no platform credentials."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
from pathlib import Path
import re
import socket
import socketserver
import struct
import threading
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--public-ip', required=True)
parser.add_argument('--zone', required=True, help='delegated synthetic rebinding zone')
parser.add_argument('--directory', type=Path, required=True, help='private operator directory containing dns.json')
parser.add_argument('--dns-port', type=int, default=53)
parser.add_argument('--http-port', type=int, default=8081)
args = parser.parse_args()
public = str(ipaddress.IPv4Address(args.public_ip))
if not re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+', args.zone) or len(args.zone) > 200:
    parser.error('invalid delegated zone')


class DNS(socketserver.BaseRequestHandler):
    def handle(self):
        data, connection = self.request
        try:
            if len(data) < 12 or struct.unpack('!H', data[4:6])[0] != 1:
                return
            offset = 12
            labels = []
            while data[offset]:
                size = data[offset]
                if size > 63:
                    return
                offset += 1
                labels.append(data[offset:offset + size].decode('ascii'))
                offset += size
            offset += 1
            kind, klass = struct.unpack('!HH', data[offset:offset + 4])
            end = offset + 4
            name = '.'.join(labels).lower()
            answer = b''
            if name.endswith('.' + args.zone) and klass == 1 and kind == 1:
                with (args.directory / 'dns.json').open() as stream:
                    mapping = json.loads(stream.read(4096))
                address = str(ipaddress.IPv4Address(mapping.get(name, public)))
                answer = b'\xc0\x0c' + struct.pack('!HHIH', 1, 1, 0, 4) + socket.inet_aton(address)
            packet = data[:2] + struct.pack('!HHHHH', 0x8400, 1, int(bool(answer)), 0, 0) + data[12:end] + answer
            connection.sendto(packet, self.client_address)
        except (ValueError, IndexError, KeyError, OSError, struct.error):
            return


class HTTP(BaseHTTPRequestHandler):
    def do_GET(self):
        if len(self.path) > 512:
            self.send_error(400)
            return
        # Only synthetic acceptance nonces are retained; internet scanner requests are ignored.
        if self.path.startswith(('/issue17-', '/redirect/issue17-')):
            path = args.directory / 'nonces.jsonl'
            entry = json.dumps({'path': self.path, 'time': time.time()}) + '\n'
            if (path.stat().st_size if path.exists() else 0) + len(entry.encode()) <= 1024 * 1024:
                with path.open('a') as log:
                    log.write(entry)
        self.send_response(302 if self.path.startswith('/redirect/') else 200)
        if self.path.startswith('/redirect/'):
            self.send_header('Location', 'http://10.42.0.2:80/')
        self.end_headers()
        self.wfile.write(b'controlled public canary\n')

    def log_message(self, *arguments):
        pass


class DNSListener(socketserver.UDPServer):
    max_packet_size = 512


dns = DNSListener((public, args.dns_port), DNS)
threading.Thread(target=dns.serve_forever, daemon=True).start()
http = HTTPServer(('127.0.0.1', args.http_port), HTTP)
print(json.dumps({'dns_port': dns.server_address[1], 'http_port': http.server_port}), flush=True)
http.serve_forever()
