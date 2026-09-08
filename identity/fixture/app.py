"""Disposable publishing acceptance fixture; no credentials are rendered."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import socket
import ssl
import threading
import time
import urllib.parse

TARGETS = json.loads(Path(__file__).with_name('targets.json').read_text())['targets']


def network():
    results = {target['name']: {'expected': target['expected'], 'observed': 'timeout'} for target in TARGETS}
    lock = threading.Lock()

    def probe(target):
        observed = 'blocked'
        try:
            with socket.create_connection((target['host'], target['port']), timeout=2) as connection:
                if target.get('tls'):
                    with ssl.create_default_context().wrap_socket(connection, server_hostname=target['host']):
                        observed = 'reachable'
                else:
                    observed = 'reachable'
        except (OSError, ValueError):
            pass
        with lock:
            results[target['name']]['observed'] = observed

    workers = [threading.Thread(target=probe, args=(target,), daemon=True) for target in TARGETS]
    deadline = time.monotonic() + 2.5
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(max(0, deadline - time.monotonic()))
    with lock:
        return {'probes': {name: dict(result) for name, result in results.items()},
                'note': 'Blocked or timed-out targets require an independently verified reachable listener to prove isolation.'}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == '/_small-cloud/ready':
            result = {'ready': True}
        elif path in ('/', '/identity'):
            result = {'fixture': 'small-cloud-publishing', 'identity': {
                name: self.headers.get('X-Small-Cloud-User-' + name.title()) for name in ('id', 'name', 'email')}}
        elif path == '/network':
            result = network()
        else:
            self.send_error(404)
            return
        payload = json.dumps(result).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == '__main__':
    HTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8080'))), Handler).serve_forever()
