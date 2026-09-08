#!/usr/bin/env python3
"""Disposable builder procurement and independent expiry reconciliation."""
from __future__ import annotations

import argparse
import fcntl
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import time
import tempfile
import uuid

from cloud import API, BUILD_LOCATIONS, Failure, OWNER, SELECTOR, ensure, quote, ssh_key, state_directory


def sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_journal(path: Path, payload: dict) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".deletion-", delete=False) as output:
            temporary = Path(output.name)
            json.dump(payload, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def finish_journal(path: Path) -> None:
    pending = json.loads(path.read_text())
    if 'cost_snapshot' in pending:
        write_journal(path.parent / f"builder-cost-{pending['server']}.json",
                      {**pending, 'deleted_at': datetime.now(timezone.utc).isoformat()})
    path.unlink()
    sync_directory(path.parent)


def cleanup_addresses(api: API, addresses: list[int]) -> None:
    """Remove recorded unassigned addresses; caller must establish resource ownership."""
    for address in api.items('primary_ips'):
        if address['id'] in addresses:
            if address.get('assignee_id') is not None:
                raise Failure('Cleanup IP reassigned; manual inspection required')
            api.call('DELETE', f"primary_ips/{address['id']}")
    if any(address['id'] in addresses for address in api.items('primary_ips')):
        raise Failure('Address deletion not confirmed')


def create(api: API, admin_cidr: str, job: str) -> dict:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", job):
        raise Failure("Job must be 1–40 lowercase letters, digits or hyphens")
    cidr = str(ipaddress.ip_network(admin_cidr, strict=True))
    # Validate the session before any provider mutation.
    expires = int(time.time()) + 1800
    controller = json.loads(Path('/etc/small-cloud/controller.json').read_text())
    validation_labels = {}
    if controller.get('validation') == 'true':
        validation_expiry = int(controller['validation-expires'])
        if validation_expiry - time.time() < 900:
            raise Failure('Validation session ends too soon to admit another build')
        expires = min(expires, validation_expiry)
        validation_labels = {'validation': 'true', 'validation-expires': str(validation_expiry)}
    name = "small-cloud-build-" + job
    existing = [s for s in api.items("servers") if s["name"] == name]
    if existing:
        # A resumed request must inspect the existing VM, never execute a second build.
        raise Failure("Build ID already exists; reconcile its outcome before using a new ID")
    builders = api.items("servers", label_selector=SELECTOR + ",role=builder")
    if len(builders) >= 5:
        raise Failure("BUILD_BUSY: five builder VMs already allocated")
    pricing = quote(api)
    choices = [row for kind in ("cx23", "cpx22") for location in BUILD_LOCATIONS for row in pricing["servers"]
               if row["type"] == kind and row["location"] == location and row["available"]]
    if not choices:
        raise Failure("CAPACITY_UNAVAILABLE: no approved builder in the EU")
    key = ssh_key(api)
    firewall = ensure(api, "firewalls", "small-cloud-builder", {"rules": [
        {"direction": "in", "protocol": "tcp", "port": "22", "source_ips": [cidr]}]})
    if firewall["rules"] != [{"direction": "in", "protocol": "tcp", "port": "22", "source_ips": [cidr], "destination_ips": [], "description": ""}]:
        api.wait(api.call("POST", f"firewalls/{firewall['id']}/actions/set_rules", {"rules": [
            {"direction": "in", "protocol": "tcp", "port": "22", "source_ips": [cidr]}]}))
    attempt = uuid.uuid4().hex
    for row in choices:
        try:
            result = api.call("POST", "servers", {"name": name, "server_type": row["type"],
                "location": row["location"], "image": "ubuntu-24.04", "ssh_keys": [key["id"]],
                "labels": {**OWNER, "role": "builder", "job": job, "expires": str(expires), "attempt": attempt, **validation_labels},
                "firewalls": [{"firewall": firewall["id"]}], "public_net": {"enable_ipv4": True, "enable_ipv6": False},
                "user_data": "#cloud-config\nssh_pwauth: false\ndisable_root: false\n"})
            break
        except Failure as error:
            if error.code != "resource_unavailable":
                raise
            # Only a definite capacity rejection permits a new create attempt.
            if any(s["name"] == name for s in api.items("servers")):
                raise Failure("Ambiguous capacity outcome; existing job requires reconciliation") from None
    else:
        raise Failure("CAPACITY_UNAVAILABLE: approved EU builder attempts exhausted")
    api.wait(result)
    server = api.call("GET", f"servers/{result['server']['id']}")["server"]
    return {"id": server["id"], "job": job, "ipv4": server["public_net"]["ipv4"]["ip"],
            "type": row["type"], "location": row["location"], "expires": expires,
            "hourly_net": row["hourly_net"], "currency": pricing["currency"]}


def remove(api: API, server: dict) -> dict:
    labels = server.get("labels", {})
    if any(labels.get(k) != v for k, v in {**OWNER, "role": "builder"}.items()):
        raise Failure("Refusing to delete a resource that is not an owned builder")
    addresses = [value["id"] for value in server["public_net"].values() if isinstance(value, dict) and value.get("id")]
    journal = state_directory() / f"deleting-builder-{server['id']}.json"
    # Durable resource IDs survive a controller crash after successful VM deletion.
    snapshot = {key: server[key] for key in ('id', 'created', 'server_type', 'location')}
    snapshot['server_type'] = {'name': server['server_type']['name']}
    snapshot['location'] = {'name': server['location']['name']}
    snapshot.update(outgoing_traffic=server.get('outgoing_traffic'), included_traffic=server.get('included_traffic'))
    ipv4 = server['public_net'].get('ipv4')
    write_journal(journal, {"server": server["id"], "addresses": addresses,
                           'cost_addresses': [ipv4['id']] if ipv4 else [], 'cost_snapshot': snapshot})
    api.wait(api.call("DELETE", f"servers/{server['id']}"))
    remaining = {s["id"] for s in api.items("servers")}
    if server["id"] in remaining:
        raise Failure("Builder deletion not confirmed")
    cleanup_addresses(api, addresses)
    finish_journal(journal)
    created = datetime.fromisoformat(server["created"].replace("Z", "+00:00"))
    seconds = (datetime.now(timezone.utc) - created).total_seconds()
    return {"id": server["id"], "deleted": True, "addresses_removed": True,
            "estimated_billed_hours": max(1, int((seconds + 3599) // 3600)), "invoice_verified": False}


def reconcile(api: API, now: int) -> dict:
    removed = []
    failures = []
    for server in api.items("servers", label_selector=SELECTOR + ",role=builder"):
        expiry = server.get("labels", {}).get("expires", "")
        if not expiry.isdigit():
            failures.append({"id": server["id"], "error": "Missing valid expiry; operator inspection required"})
        elif int(expiry) <= now:
            try:
                removed.append(remove(api, server))
            except (Failure, OSError, ValueError, KeyError, TypeError) as error:
                failures.append({"id": server["id"], "error": str(error) if isinstance(error, Failure)
                                 else 'Builder cleanup failed; inspect inventory and protected state'})
    live = {s["id"] for s in api.items("servers")}
    for journal in state_directory().glob("deleting-builder-*.json"):
        try:
            pending = json.loads(journal.read_text())
            if pending["server"] in live:
                continue
            cleanup_addresses(api, pending['addresses'])
            finish_journal(journal)
        except (Failure, OSError, ValueError, KeyError, TypeError) as error:
            failures.append({"journal": journal.name, "error": str(error) if isinstance(error, Failure)
                             else 'Builder address cleanup failed; inspect protected journal'})
    return {"removed": removed, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("create")
    new.add_argument("--admin-cidr", required=True)
    new.add_argument("--job", required=True)
    delete = commands.add_parser("delete", help="Delete an owned disposable builder and its addresses")
    delete.add_argument("id", type=int)
    commands.add_parser("reconcile", help="Delete only expired owned builders; run independently every minute")
    args = parser.parse_args()
    try:
        if os.geteuid() != 0 or not Path("/etc/small-cloud/controller").is_file():
            raise Failure("Builder mutations must run on the configured control host")
        api = API("hetzner")
        # All operator admission/deletion must run on this one controller.
        with (state_directory() / "builders.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if args.command == "create":
                result = create(api, args.admin_cidr, args.job)
            elif args.command == "delete":
                result = remove(api, api.call("GET", f"servers/{args.id}")["server"])
            else:
                result = reconcile(api, int(time.time()))
        print(json.dumps(result, indent=2))
        return 1 if result.get("failures") else 0
    except (Failure, OSError, ValueError) as error:
        code = f" [{error.code}]" if isinstance(error, Failure) and error.code else ""
        print(f"ERROR: {error}{code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
