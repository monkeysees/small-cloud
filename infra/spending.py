#!/usr/bin/env python3
"""Estimate Hetzner project spend from observed resources; never claim invoiced costs."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

from cloud import API, Failure, state_directory

FX_URL = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml'


def instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timestamp needs timezone')
    return result


def number(value):
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError('Invalid nonnegative amount')
    return result


def write_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def exchange_rate(now):
    with urllib.request.urlopen(FX_URL, timeout=20) as response:
        root = ET.fromstring(response.read(65536))
    dated = next(node for node in root.iter() if 'time' in node.attrib)
    date = instant(dated.attrib['time'] + 'T00:00:00Z')
    if not timedelta(0) <= now - date <= timedelta(days=7):
        raise ValueError('Stale FX rate')
    rate = number(next(node.attrib['rate'] for node in dated if node.attrib.get('currency') == 'USD'))
    if not rate:
        raise ValueError('Zero FX rate')
    return rate, date.isoformat()


def resource(row, kind, price):
    return {'id': f"{kind}:{row['id']}", 'created': row['created'],
            'hourly': price['price_hourly']['net'], 'monthly': price['price_monthly']['net'],
            'traffic_bytes': row.get('outgoing_traffic') or 0,
            'included_bytes': row.get('included_traffic') or 0,
            'traffic_per_tb': price.get('price_per_tb_traffic', {}).get('net', '0')}


def observations(api, archive):
    pricing = api.call('GET', 'pricing')['pricing']
    if pricing['currency'] != 'EUR':
        raise ValueError('Estimator requires EUR account prices')
    types = {row['name']: row for row in api.items('server_types')}
    servers = api.items('servers')
    addresses = api.items('primary_ips')
    rows = []
    warnings = []
    def server_price(row):
        return next(p for p in types[row['server_type']['name']]['prices']
                    if p['location'] == row['location']['name'])
    def ip_price(location):
        return next(p for item in pricing['primary_ips'] if item['type'] == 'ipv4'
                    for p in item['prices'] if p['location'] == location)
    for row in servers:
        rows.append(resource(row, 'server', server_price(row)))
        if row.get('backup_window') is not None:
            warnings.append('Server backups are enabled; their charges are not included')
        if row.get('outgoing_traffic') is None:
            warnings.append('A server traffic counter is unavailable')
    for row in addresses:
        if row['type'] == 'ipv4':
            rows.append(resource(row, 'ipv4', ip_price(row['location']['name'])))
    # Deletion archives cover builders that live entirely between polling runs.
    for path in archive.glob('builder-cost-*.json'):
        event = json.loads(path.read_text())
        row = event['cost_snapshot']
        if row.get('outgoing_traffic') is None:
            warnings.append('A deleted builder traffic counter was unavailable; its traffic may be missing')
        item = resource(row, 'server', server_price(row))
        item['ended'] = event['deleted_at']
        rows.append(item)
        for address in event['cost_addresses']:
            item = resource({'id': address, 'created': row['created']}, 'ipv4', ip_price(row['location']['name']))
            item['ended'] = event['deleted_at']
            rows.append(item)
    # Explicitly report unsupported billable resources rather than silently count zero.
    for kind in ('volumes', 'floating_ips', 'load_balancers'):
        if api.items(kind):
            warnings.append(f'{kind} present; their charges are not included')
    if api.items('images', type='snapshot'):
        warnings.append('Snapshots present; their charges are not included')
    return rows, number(pricing['vat_rate']), sorted(set(warnings))


def estimate(rows, previous, now, rate, fx_date, vat, warnings, opening):
    month = now.strftime('%Y-%m')
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    ledger = previous if previous.get('month') == month else {'month': month, 'resources': {}}
    last = ledger.get('as_of')
    if last and now - instant(last) > timedelta(minutes=15):
        ledger['collection_gap'] = True
    if ledger.get('collection_gap'):
        warnings.append('Collection gap over 15 minutes; unobserved resource changes may be missing')
    seen = set()
    for row in rows:
        if row.get('ended') and instant(row['ended']) <= start:
            continue
        if instant(row['created']) > now:
            raise ValueError('Resource creation lies in the future')
        seen.add(row['id'])
        old = ledger['resources'].get(row['id'], {})
        if old and (old['hourly'] != row['hourly'] or old['monthly'] != row['monthly']):
            ledger['price_change'] = True
        ledger['resources'][row['id']] = row
    if ledger.get('price_change'):
        warnings.append('Resource price changed; current prices are applied to its observed month')
    for key, row in ledger['resources'].items():
        if key not in seen and not row.get('ended'):
            row['ended'] = now.isoformat()
    accrued = number(opening.get('amount_eur', 0)) if opening.get('month') == month else Decimal(0)
    if accrued and not opening.get('source'):
        raise ValueError('Opening estimate requires a source')
    forecast = accrued
    def cost(row, until):
        origin = max(start, instant(row['created']))
        finish = min(until, instant(row['ended'])) if row.get('ended') else until
        hours = number(max(0, (finish - origin).total_seconds()) / 3600).to_integral_value(rounding=ROUND_CEILING)
        compute = min(hours * number(row['hourly']), number(row['monthly']))
        excess = max(0, row['traffic_bytes'] - row['included_bytes'])
        # Provider rounds traffic in 100 MB blocks; rate-card TB uses 1024^4 bytes.
        traffic = (number(excess) / Decimal(100 * 1024**2)).to_integral_value(rounding=ROUND_CEILING)
        return compute + traffic * Decimal(100 * 1024**2) / Decimal(1024**4) * number(row['traffic_per_tb'])
    for row in ledger['resources'].values():
        accrued += cost(row, now)
        forecast += cost(row, end)
    multiplier = (1 + vat / 100) * rate
    ledger['as_of'] = now.isoformat()
    evidence = {'estimated_usd': round(float(accrued * multiplier), 2),
                'forecast_usd': round(float(forecast * multiplier), 2),
                'estimated_eur_net': round(float(accrued), 4), 'forecast_eur_net': round(float(forecast), 4),
                'basis': 'api-resource-estimate', 'as_of': now.isoformat(),
                'source': 'Hetzner project inventory, current price API, creation times, traffic counters and builder deletion archives',
                'fx_source': f'ECB EUR/USD reference rate {rate}; {FX_URL}', 'fx_as_of': fx_date,
                'vat_percent': str(vat), 'month': month, 'resource_count': len(ledger['resources']),
                'opening_estimate': opening if opening.get('month') == month else None,
                'warnings': sorted(set(warnings)),
                'assumptions': ['Estimate, not an invoice; current account prices and quoted VAT are used',
                    'Forecast retains currently live resources until month end; future new builds and future traffic excluded',
                    'Resources deleted outside this controller between polls may be missed; deletion detection can overestimate lifetime',
                    'Project-only scope; other projects, support, domains and external services excluded']}
    return ledger, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/var/lib/small-cloud/spending.json'))
    parser.add_argument('--config', type=Path, default=Path('/etc/small-cloud/spending-estimator.json'))
    args = parser.parse_args()
    os.umask(0o077)
    directory = state_directory()
    with (directory / 'spending.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        now = datetime.now(timezone.utc)
        path = directory / 'spending-ledger.json'
        previous = json.loads(path.read_text()) if path.exists() else {}
        config = json.loads(args.config.read_text())
        rows, vat, warnings = observations(API('hetzner'), directory)
        rate, fx_date = exchange_rate(now)
        ledger, evidence = estimate(rows, previous, now, rate, fx_date, vat, warnings, config.get('opening_estimate', {}))
        write_json(path, ledger)
        write_json(args.output, evidence)
        # Successful collection permits removal of deletion archives older than last month.
        cutoff = now.replace(day=1) - timedelta(days=32)
        for archive in directory.glob('builder-cost-*.json'):
            if instant(json.loads(archive.read_text())['deleted_at']) < cutoff:
                archive.unlink()
        print(json.dumps(evidence))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Failure, OSError, ValueError, KeyError, TypeError, StopIteration, ArithmeticError, ET.ParseError):
        print('Spending collection failed; prior evidence will become stale. Check provider access and protected state.', file=sys.stderr)
        sys.exit(1)
