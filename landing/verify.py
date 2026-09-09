"""Check the deployed public landing page and its neighboring route boundaries."""
import hashlib
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ORIGIN = 'https://small-cloud.monkeysees.one'
HERE = Path(__file__).resolve().parent


def request(path, method='GET'):
    try:
        response = urllib.request.urlopen(urllib.request.Request(ORIGIN + path, method=method), timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


def main():
    checks = []
    for path, filename, content_type in [('/', 'index.html', 'text/html'), ('/landing.css', 'landing.css', 'text/css')]:
        status, headers, body = request(path)
        assert status == 200, (path, status)
        assert content_type in headers['Content-Type'], (path, headers['Content-Type'])
        assert body == (HERE / filename).read_bytes(), f'{path}: hosted content differs from checkout'
        assert not headers.get('Set-Cookie'), f'{path}: unexpected session cookie'
        head_status, _, head_body = request(path, 'HEAD')
        assert head_status == 200 and not head_body
        checks.append({'path': path, 'status': status, 'head_status': head_status, 'sha256': hashlib.sha256(body).hexdigest()})
    html = (HERE / 'index.html').read_text()
    for notice in ('Small Cloud is in testing. New users are added manually.', 'There is no self-service signup.', 'Each app has its own persistent database.', 'During testing, there is no backup or recovery guarantee'):
        assert notice in html, notice
    for path in ('/api/auth/status', '/api/directory'):
        status, _, body = request(path)
        assert status == 401, (path, status)
        assert 'error' in json.loads(body), f'{path}: expected API error'
        checks.append({'path': path, 'status': status})
    status, _, installer = request('/cli/install.sh')
    assert status == 200 and installer.startswith(b'#!/bin/sh'), 'CLI installer unavailable'
    checks.append({'path': '/cli/install.sh', 'status': status})
    status, _, _ = request('/auth/verify')
    assert status == 400, ('Approval without code must retain its validation error', status)
    checks.append({'path': '/auth/verify', 'status': status})
    for path in ('/not-a-real-page-46', '/index.html', '/README.md', '/internal/tls'):
        status, _, _ = request(path)
        assert status == 404, (path, status)
        checks.append({'path': path, 'status': status})
    with urllib.request.urlopen(ORIGIN.replace('https:', 'http:') + '/', timeout=20) as response:
        assert response.url == ORIGIN + '/' and response.status == 200
    checks.append({'check': 'HTTP redirects to public HTTPS', 'passed': True})
    print(json.dumps({'checked_at': datetime.now(timezone.utc).isoformat(), 'origin': ORIGIN, 'checks': checks}, indent=2))


if __name__ == '__main__':
    main()
