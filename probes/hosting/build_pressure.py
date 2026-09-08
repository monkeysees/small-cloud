#!/usr/bin/env python3
"""Bounded build pressure fixture; execute only in a disposable Dockerfile RUN."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import socket

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('resource', choices=['cpu', 'memory', 'pids', 'disk'])
parser.add_argument('--peer-host', help='controlled other-builder SSH listener')
args = parser.parse_args()
signal.alarm(90)
if args.peer_host:
    try:
        with socket.create_connection((args.peer_host, 22), timeout=3):
            peer = {'other_builder_connected': True}
    except TimeoutError:
        peer = {'other_builder_connected': False, 'timeout': True}
    print(json.dumps(peer), flush=True)
if args.resource == 'cpu':
    children = [subprocess.Popen([sys.executable, '-c', 'while True: pass']) for _ in range(4)]
    start = time.monotonic()
    try:
        time.sleep(20)
    finally:
        for child in children:
            child.terminate()
        for child in children:
            child.wait(timeout=5)
    print(json.dumps({'resource': 'cpu', 'four_busy_children_seconds': time.monotonic() - start}), flush=True)
elif args.resource == 'memory':
    blocks = []
    for _ in range(64):
        blocks.append(bytearray(64 * 1024 * 1024))
    print(json.dumps({'resource': 'memory', 'unexpectedly_allocated_bytes': 4 * 1024**3}), flush=True)
elif args.resource == 'pids':
    event = threading.Event()
    threads = []
    refused = False
    try:
        for _ in range(700):
            thread = threading.Thread(target=event.wait)
            thread.start()
            threads.append(thread)
    except RuntimeError:
        refused = True
    finally:
        event.set()
        for thread in threads:
            thread.join(timeout=2)
    print(json.dumps({'resource': 'pids', 'threads_created': len(threads), 'refused': refused}), flush=True)
else:
    path = Path('/tmp/issue17-pressure')
    total = 0
    error = None
    try:
        with path.open('wb', buffering=0) as output:
            for _ in range(11 * 1024):
                total += output.write(b'x' * (1024 * 1024))
    except OSError as failure:
        error = failure.errno
    finally:
        volume = os.statvfs('/tmp')
        report = {'resource': 'disk', 'written_bytes': total, 'errno': error,
                  'filesystem_bytes': volume.f_blocks * volume.f_frsize,
                  'available_bytes': volume.f_bavail * volume.f_frsize}
        path.unlink(missing_ok=True)
    print(json.dumps(report), flush=True)
