#!/usr/bin/env python3
"""One-shot, restart-safe procurement of the authorized German CX foundation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import smtplib
import sys

import cloud
from monitor import send_alert

KINDS = {'control': 'cx33', 'runtime': 'cx43'}
# A rejected create is retryable only when the provider explicitly proves rejection.
RETRYABLE = {'resource_unavailable', 'resource_limit_exceeded', 'rate_limit_exceeded'}
COLLECTIONS = {'servers', 'networks', 'firewalls', 'ssh_keys'}


def save(path: Path, state: dict) -> None:
    temporary = path.with_suffix('.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(state, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class JournalAPI(cloud.API):
    def __init__(self, api, state, path):
        self.api, self.state, self.path = api, state, path

    def items(self, resource, **query):
        return self.api.items(resource, **query)

    def wait(self, result):
        return self.api.wait(result)

    def reconcile(self):
        pending = self.state.get('pending')
        if not pending:
            return
        matches = [row for row in self.items(pending['resource']) if row['name'] == pending['name']]
        if len(matches) != 1 or any(matches[0].get('labels', {}).get(k) != v for k, v in pending['labels'].items()):
            raise cloud.Failure('Ambiguous create outcome: manual inventory reconciliation required; automatic creation stopped')
        del self.state['pending']
        save(self.path, self.state)

    def call(self, method, path, body=None):
        if method != 'POST' or path not in COLLECTIONS:
            return self.api.call(method, path, body)
        if body is None:
            raise cloud.Failure('Create request requires a body')
        if self.state.get('pending'):
            raise cloud.Failure('Unresolved create journal; automatic creation stopped')
        self.state['pending'] = {'resource': path, 'name': body['name'], 'labels': body['labels']}
        save(self.path, self.state)
        try:
            result = self.api.call(method, path, body)
        except cloud.Failure as error:
            if error.code in RETRYABLE:
                del self.state['pending']
                save(self.path, self.state)
            raise
        del self.state['pending']
        save(self.path, self.state)
        return result


def selection(api, state):
    existing = {}
    for row in api.items('servers'):
        role = next((role for role in KINDS if row['name'] == 'small-cloud-' + role), None)
        if role is None:
            if all(row.get('labels', {}).get(k) == v for k, v in cloud.OWNER.items()) and row.get('labels', {}).get('role') in KINDS:
                raise cloud.Failure('Unexpected foundation server name; inspect inventory')
            continue
        if role in existing or any(row.get('labels', {}).get(k) != v for k, v in {**cloud.OWNER, 'role': role}.items()):
            raise cloud.Failure('Unowned or duplicate foundation server; inspect inventory')
        if row['server_type']['name'] != KINDS[role] or row['location']['name'] not in cloud.LOCATIONS or row.get('labels', {}).get('validation'):
            raise cloud.Failure('Existing foundation differs from authorized permanent CX pair')
        existing[role] = row
    locations = {row['location']['name'] for row in existing.values()}
    if existing and state.get('location'):
        locations.add(state['location'])
    if len(locations) > 1:
        raise cloud.Failure('Foundation location drift; inspect inventory')
    quoted = cloud.quote(api)
    if quoted['currency'] != 'EUR':
        raise cloud.Failure('Price currency differs from authorized EUR ceiling')
    candidates = sorted(locations) if locations else cloud.LOCATIONS
    affordable = False
    for location in candidates:
        rows = {row['type']: row for row in quoted['servers'] if row['location'] == location and row['type'] in KINDS.values()}
        compute = sum((Decimal(rows[kind]['monthly_net']) for kind in KINDS.values()), Decimal(0))
        hourly = sum((Decimal(rows[kind]['hourly_net']) for kind in KINDS.values()), Decimal(0))
        ipv4 = next(price for item in quoted['primary_ips'] if item['type'] == 'ipv4' for price in item['prices'] if price['location'] == location)
        ip_cost = Decimal(ipv4['price_monthly']['net']) * 2
        ip_hourly = Decimal(ipv4['price_hourly']['net']) * 2
        prices = ((compute, '24.48'), (hourly, '0.0392'), (ip_cost, '1.00'), (ip_hourly, '0.0016'))
        if any(not price.is_finite() or not 0 <= price <= Decimal(ceiling) for price, ceiling in prices):
            continue
        affordable = True
        if all(role in existing or rows[kind]['available'] for role, kind in KINDS.items()):
            return {'status': 'ready', 'location': location, 'compute_monthly_net_eur': str(compute), 'ipv4_monthly_net_eur': str(ip_cost)}
    return {'status': 'waiting' if affordable else 'blocked', 'reason': 'German CX capacity unavailable' if affordable else 'Current price exceeds authorized ceiling', 'existing_roles': sorted(existing)}


def cycle(api, state, path, admin_cidr, check=False):
    cidr = str(ipaddress.ip_network(admin_cidr, strict=True))
    if ipaddress.ip_network(cidr).prefixlen == 0:
        raise cloud.Failure('SSH administrator CIDR must not allow the entire Internet')
    if state.get('admin_cidr', cidr) != cidr:
        raise cloud.Failure('Administrator CIDR changed; inspect watcher configuration')
    if state.get('status') == 'complete':
        return state
    journal = JournalAPI(api, state, path)
    if not check:
        journal.reconcile()
    elif state.get('pending'):
        return {'status': 'blocked', 'reason': 'Unresolved create journal'}
    selected = selection(api, state)
    if check:
        return selected
    state.update(selected)
    state['admin_cidr'] = cidr
    save(path, state)
    if selected['status'] == 'ready':
        result = cloud.foundation(journal, cidr, location=selected['location'])
        state.update(status='complete', foundation=result, completed_at=datetime.now(timezone.utc).isoformat())
        state.pop('reason', None)
        save(path, state)
    return state


def notify(state, path, smtp_path):
    fingerprint = [state.get('status'), state.get('reason', '')]
    if state.get('notified') == fingerprint or state.get('status') not in ('complete', 'blocked'):
        return
    smtp = json.loads(cloud.private_file(smtp_path))['smtp']
    send_alert(smtp, {'host': 'cx-availability-watcher', 'time': datetime.now(timezone.utc).isoformat(),
                     'alerts': ['CX foundation procured; application activation remains pending.' if state['status'] == 'complete' else state.get('reason', 'Procurement blocked')],
                     'status': state['status'], 'foundation': state.get('foundation')})
    state['notified'] = fingerprint
    save(path, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admin-cidr', required=True)
    parser.add_argument('--smtp-config', type=Path, default=cloud.SECRET_DIR / 'monitor-smtp.json')
    parser.add_argument('--check', action='store_true', help='Read-only inventory, capacity and price check; no procurement or email')
    args = parser.parse_args()
    try:
        directory = cloud.state_directory()
        path = directory / 'cx-watch.json'
        descriptor = os.open(directory / 'cx-watch.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print(json.dumps({'status': 'already-running'}))
                return 0
            state = json.loads(cloud.private_file(path)) if path.exists() else {}
            try:
                result = cycle(cloud.API('hetzner'), state, path, args.admin_cidr, args.check)
            except (cloud.Failure, ValueError, KeyError, StopIteration, InvalidOperation) as error:
                if args.check:
                    raise
                reason = str(error) if isinstance(error, cloud.Failure) else 'Watcher configuration or provider data invalid; inspect configuration and inventory'
                state.update(status='blocked', reason=reason)
                save(path, state)
                result = state
            if not args.check:
                try:
                    notify(state, path, args.smtp_config)
                except (OSError, ValueError, KeyError, cloud.Failure, smtplib.SMTPException):
                    print(json.dumps({'notification': 'failed; will retry next run'}))
            print(json.dumps({key: value for key, value in result.items() if key not in ('notified', 'pending')}))
            return 0
    except (cloud.Failure, OSError, ValueError, KeyError, StopIteration, InvalidOperation):
        print(json.dumps({'status': 'blocked', 'reason': 'Watcher configuration or provider data invalid; inspect private configuration and inventory'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
