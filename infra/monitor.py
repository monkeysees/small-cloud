#!/usr/bin/env python3
"""Collect bounded operator health evidence and optionally send configured SMTP alerts."""
import argparse
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import json
import os
from pathlib import Path
import re
import shutil
import smtplib
import socket
import ssl
import stat
import subprocess
import sys

RECIPIENT = 'monkeyseesone@gmail.com'
MAX_REPORT_BYTES = 65536
MAX_HISTORY_BYTES = 10 * 1024 * 1024


def private_json(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as stream:
        metadata = os.fstat(stream.fileno())
        if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o600 or not stat.S_ISREG(metadata.st_mode):
            raise ValueError('configuration must be a root-owned regular file with mode 0600')
        return json.load(stream)


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamps must include timezone')
    return parsed


def spend_evidence(path, now):
    evidence = json.loads(path.read_text())
    estimated = evidence.get('basis') == 'api-resource-estimate'
    if not estimated and evidence['actual_basis'] not in ('provider-metered', 'invoice'):
        raise ValueError('actual spend requires provider-metered or invoice evidence, not a price estimate')
    if not evidence['source'] or not evidence['fx_source']:
        raise ValueError('spending and FX sources are required')
    maximum_age = timedelta(minutes=15) if estimated else timedelta(hours=48)
    if not timedelta(0) <= now - timestamp(evidence['as_of']) <= maximum_age:
        raise ValueError('spending evidence is stale')
    if not timedelta(0) <= now - timestamp(evidence['fx_as_of']) <= timedelta(days=7):
        raise ValueError('FX evidence must be at most seven days old')
    values = {}
    for key in ('estimated_usd' if estimated else 'actual_usd', 'forecast_usd'):
        value = evidence[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < 1e9:
            raise ValueError('spending totals must be finite nonnegative USD numbers')
        values[key] = value
    if estimated:
        for key in ('warnings', 'assumptions'):
            if not isinstance(evidence[key], list) or any(not isinstance(x, str) for x in evidence[key]):
                raise ValueError('Estimate explanations must be string lists')
        return {**{key: value for key, value in evidence.items() if key not in ('actual_usd', 'actual_basis')}, **values}
    return {**values, **{key: evidence[key] for key in
            ('actual_basis', 'as_of', 'source', 'fx_source', 'fx_as_of')}}


def collect(config, now):
    report = {'time': now.isoformat(), 'host': socket.gethostname(), 'disks': [], 'services': [], 'alerts': []}
    for path in config.get('disks', ['/']):
        usage = shutil.disk_usage(path)
        percent = round(100 * usage.used / usage.total, 1)
        report['disks'].append({'path': path, 'used_percent': percent, 'free_bytes': usage.free})
        if percent >= 80:
            report['alerts'].append(f'disk {path} is {percent}% full')
    for service in config.get('services', []):
        if not re.fullmatch(r'[A-Za-z0-9_.@-]{1,128}\.service', service):
            raise ValueError('service name must be a systemd .service unit')
        try:
            result = subprocess.run(['systemctl', 'is-active', '--quiet', service],
                                    timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            active = result.returncode == 0
        except subprocess.TimeoutExpired:
            active = False
        report['services'].append({'unit': service, 'active': active})
        if not active:
            report['alerts'].append(f'service {service} is not active')
    host = config.get('tls_hostname')
    if host:
        try:
            with socket.create_connection((host, 443), timeout=10) as connection:
                with ssl.create_default_context().wrap_socket(connection, server_hostname=host) as secure:
                    certificate = secure.getpeercert()
                    not_after = certificate.get('notAfter') if certificate else None
                    if not isinstance(not_after, str):
                        raise ValueError('verified peer certificate has no expiry date')
                    expiry = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), timezone.utc)
            days = (expiry - now).days
            report['tls'] = {'hostname': host, 'expires': expiry.isoformat(), 'days_remaining': days}
            if days < 14:
                report['alerts'].append(f'TLS certificate for {host} expires in {days} days')
        except (OSError, ValueError, KeyError):
            report['tls'] = {'hostname': host, 'verified': False}
            report['alerts'].append(f'TLS certificate/connectivity verification failed for {host}')
    return report


def retain(directory, now):
    files = sorted(directory.glob('report-*.json'), key=lambda item: item.name, reverse=True)
    total = 0
    for path in files:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError('unexpected nonregular monitoring history entry')
        total += metadata.st_size
        if now.timestamp() - metadata.st_mtime > 7 * 86400 or total > MAX_HISTORY_BYTES:
            path.unlink()


def send_alert(smtp, report):
    if smtp.get('security') not in ('starttls', 'tls'):
        raise ValueError('SMTP security must be starttls or tls')
    message = EmailMessage()
    message['From'] = smtp['sender']
    message['To'] = RECIPIENT
    message['Subject'] = f"Small Cloud operator alert: {report['host']}"
    message.set_content(json.dumps(report, indent=2))
    context = ssl.create_default_context()
    if smtp['security'] == 'tls':
        with smtplib.SMTP_SSL(smtp['host'], smtp['port'], timeout=20, context=context) as client:
            client.login(smtp['username'], smtp['password'])
            client.send_message(message)
    else:
        with smtplib.SMTP(smtp['host'], smtp['port'], timeout=20) as client:
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
            client.login(smtp['username'], smtp['password'])
            client.send_message(message)



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True, help='root-owned mode-0600 health/SMTP JSON')
    parser.add_argument('--spend', type=Path, help='redacted observed-cost estimates or verified totals with FX provenance')
    parser.add_argument('--output', type=Path, default=Path('/var/lib/small-cloud-monitor'))
    parser.add_argument('--send', action='store_true', help='send actual alerts using configured SMTP authority')
    parser.add_argument('--delivery-check', action='store_true', help='include an explicit delivery-check alert')
    args = parser.parse_args()
    os.umask(0o077)
    config = private_json(args.config)
    now = datetime.now(timezone.utc)
    report = collect(config, now)
    if args.spend:
        try:
            report['spending'] = spend_evidence(args.spend, now)
            estimated = report['spending'].get('basis') == 'api-resource-estimate'
            for kind in ('estimated_usd' if estimated else 'actual_usd', 'forecast_usd'):
                thresholds = [value for value in (50, 80, 100) if report['spending'][kind] >= value]
                if thresholds:
                    report['alerts'].append(f'{kind} reached USD {max(thresholds)} threshold')
            for warning in report['spending'].get('warnings', []):
                report['alerts'].append('Cost estimate coverage: ' + warning)
        except (OSError, ValueError, KeyError, TypeError):
            report['alerts'].append('Spending evidence missing, invalid or stale; cost monitoring unavailable')
    if args.delivery_check:
        report['alerts'].append('Operator-requested SMTP delivery check; receipt must be independently confirmed')
    report['delivery'] = 'not requested'
    if args.send and report['alerts']:
        try:
            send_alert(config['smtp'], report)
            report['delivery'] = 'SMTP accepted; recipient receipt unverified'
        except (OSError, ValueError, KeyError, smtplib.SMTPException):
            report['delivery'] = 'failed (details withheld to protect SMTP credentials)'
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = args.output.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ValueError('output directory must be root-owned with mode 0700')
    payload = json.dumps(report, indent=2)
    if len(payload.encode()) > MAX_REPORT_BYTES:
        raise ValueError('report exceeds bounded diagnostic size')
    destination = args.output / f"report-{now.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    with destination.open('x') as stream:
        stream.write(payload + '\n')
    retain(args.output, now)
    print(payload)
    return 1 if report['delivery'].startswith('failed') else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError):
        print('Monitoring failed: check protected configuration, evidence and output permissions.', file=sys.stderr)
        sys.exit(1)
