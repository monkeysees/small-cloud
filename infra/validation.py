#!/usr/bin/env python3
"""Delete only expired temporary validation hosts; intended for an independent operator timer."""
import argparse
import json
import sys
import time
from cloud import API, Failure, OWNER, SELECTOR, state_directory
from builders import cleanup_addresses, finish_journal, write_journal


def cleanup(force=False):
    api = API('hetzner')
    servers = api.items('servers', label_selector=SELECTOR + ',validation=true')
    removed = []
    failures = []
    for server in sorted(servers, key=lambda row: row['labels'].get('role') != 'builder'):
        try:
            if any(server['labels'].get(key) != value for key, value in {**OWNER, 'validation': 'true'}.items()):
                raise Failure('Refusing to delete an unowned validation host')
            expiry = int(server['labels']['validation-expires'])
            if not force and expiry > time.time():
                continue
            addresses = [value['id'] for value in server['public_net'].values()
                         if isinstance(value, dict) and value.get('id')]
            journal = state_directory() / f"validation-delete-{server['id']}.json"
            write_journal(journal, {'addresses': addresses, 'server': server['id']})
            api.wait(api.call('DELETE', f"servers/{server['id']}"))
            removed.append(server['id'])
        except (Failure, OSError, ValueError, KeyError, TypeError) as error:
            failures.append({'id': server['id'], 'error': str(error) if isinstance(error, Failure)
                             else 'Validation host cleanup failed; inspect inventory and protected state'})
    live = {server['id'] for server in api.items('servers')}
    for identifier in set(removed) & live:
        failures.append({'id': identifier, 'error': 'Validation host deletion not confirmed'})
    removed = [identifier for identifier in removed if identifier not in live]
    for journal in state_directory().glob('validation-delete-*.json'):
        try:
            pending = json.loads(journal.read_text())
            if pending['server'] in live:
                continue
            cleanup_addresses(api, pending['addresses'])
            finish_journal(journal)
        except (Failure, OSError, ValueError, KeyError, TypeError) as error:
            failures.append({'journal': journal.name, 'error': str(error) if isinstance(error, Failure)
                             else 'Validation address cleanup failed; inspect protected journal'})
    return {'removed': removed, 'remaining_servers': len(live), 'failures': failures}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--now', action='store_true', help='End authorized temporary validation early')
    args = parser.parse_args()
    try:
        result = cleanup(args.now)
    except (Failure, OSError, ValueError, KeyError, TypeError):
        result = {'removed': [], 'remaining_servers': None,
                  'failures': [{'error': 'Validation cleanup inventory unavailable; inspect provider and protected state'}]}
    print(json.dumps(result))
    return 1 if result['failures'] else 0


if __name__ == '__main__':
    sys.exit(main())
