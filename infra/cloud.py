#!/usr/bin/env python3
"""Operator-only Hetzner foundation CLI. No provider credentials leave this process."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
from pathlib import Path
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

OWNER = {"managed-by": "small-cloud", "issue": "17"}
SELECTOR = "managed-by=small-cloud,issue=17"
LOCATIONS = ("nbg1", "fsn1")
BUILD_LOCATIONS = (*LOCATIONS, "hel1")
SECRET_DIR = Path.home() / ".config/small-cloud/secrets"
STATE_DIR = Path.home() / ".local/state/small-cloud/infra"


class Failure(Exception):
    """Safe operator diagnostic; never contains provider response bodies."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


def private_file(path: Path) -> str:
    for item, mode in ((path.parent, 0o700), (path, 0o600)):
        info = item.lstat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != mode or item.is_symlink():
            raise Failure(f"Unsafe credential permissions: {item}; expected {mode:04o}")
    return path.read_text().strip()


class API:
    def __init__(self, provider: str):
        self.provider = provider
        self.base = {"hetzner": "https://api.hetzner.cloud/v1/", "cloudflare": "https://api.cloudflare.com/client/v4/"}[provider]
        self.token = private_file(SECRET_DIR / f"{provider}-token")

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(self.base + path, method=method,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
            data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read(8 * 1024 * 1024)
                result = json.loads(data) if data else {}
        except urllib.error.HTTPError as error:
            # Responses can contain user data; publish only the HTTP status.
            code = ""
            try:
                candidate = json.loads(error.read(65536)).get("error", {}).get("code", "")
                if isinstance(candidate, str) and re.fullmatch(r"[a-z_]{1,64}", candidate):
                    code = candidate
            except (ValueError, AttributeError):
                pass
            raise Failure(f"{self.provider} {method} {path.split('?')[0]}: HTTP {error.code}", code) from None
        except (OSError, ValueError):
            raise Failure(f"{self.provider} {method} {path.split('?')[0]}: outcome unknown; inspect inventory before retry") from None
        if result.get("success") is False:
            raise Failure(f"{self.provider}: request rejected")
        return result

    def items(self, resource: str, **query: str) -> list[dict]:
        rows = []
        page = 1
        while True:
            result = self.call("GET", resource + "?" + urllib.parse.urlencode({**query, "page": page, "per_page": 100}))
            rows.extend(result[resource])
            page = result.get("meta", {}).get("pagination", {}).get("next_page")
            if page is None:
                return rows

    def wait(self, result: dict) -> None:
        actions = ([result["action"]] if result.get("action") else []) + result.get("next_actions", []) + result.get("actions", [])
        for action in actions:
            deadline = time.monotonic() + 300
            while action["status"] == "running":
                if time.monotonic() >= deadline:
                    raise Failure("Provider action deadline exceeded; inspect inventory before retry")
                time.sleep(2)
                action = self.call("GET", f"actions/{action['id']}")["action"]
            if action["status"] != "success":
                raise Failure(f"Provider action {action['id']} failed; inspect inventory")


def inventory(api: API) -> dict:
    result = {}
    for resource in ("servers", "networks", "volumes", "firewalls", "ssh_keys", "primary_ips"):
        result[resource] = [{key: value for key, value in row.items() if key in
            ("id", "name", "labels", "status", "created", "ip", "auto_delete", "assignee_id")}
            for row in api.items(resource)]
    return result


def quote(api: API) -> dict:
    types = {s["name"]: s for s in api.items("server_types")}
    pricing = api.call("GET", "pricing")["pricing"]
    rows = []
    for name in ("cx33", "cx43", "cx23", "cpx22", "cpx32", "cpx42"):
        server = types[name]
        for location in BUILD_LOCATIONS:
            price = next(p for p in server["prices"] if p["location"] == location)
            available = any(item["name"] == location and item["available"] for item in server["locations"])
            rows.append({"type": name, "location": location, "available": available,
                "cores": server["cores"], "memory_gib": server["memory"], "disk_gb": server["disk"],
                "hourly_net": price["price_hourly"]["net"], "monthly_net": price["price_monthly"]["net"]})
    return {"currency": pricing["currency"], "vat_rate": pricing["vat_rate"], "servers": rows,
            "primary_ips": pricing["primary_ips"], "volume": pricing["volume"]}


def ensure(api: API, resource: str, name: str, desired: dict) -> dict:
    matches = [r for r in api.items(resource) if r["name"] == name]
    if matches:
        row = matches[0]
        expected_labels = {**OWNER, **desired.get("labels", {})}
        if len(matches) != 1 or any(row.get("labels", {}).get(k) != v for k, v in expected_labels.items()):
            raise Failure(f"Refusing to adopt unowned or ambiguous {resource}/{name}")
        if resource == "servers":
            intended = {item["firewall"] for item in desired["firewalls"]}
            attached = {item["id"] for item in row["public_net"]["firewalls"]}
            if attached - intended:
                raise Failure(f"Unexpected firewall attachment on {name}; inspect before reapplication")
        return row
    # Never automatically retry a POST: a lost response may hide a successful create.
    result = api.call("POST", resource, {"name": name, "labels": OWNER, **desired})
    api.wait(result)
    return result[{"ssh_keys": "ssh_key", "networks": "network", "firewalls": "firewall", "servers": "server"}[resource]]


def state_directory() -> Path:
    STATE_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = STATE_DIR.lstat()
    if STATE_DIR.is_symlink() or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise Failure(f"Unsafe state directory: {STATE_DIR}")
    return STATE_DIR


def ssh_key(api: API) -> dict:
    key = state_directory() / "operator_ed25519"
    if not key.exists():
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "small-cloud-operator", "-f", str(key)], check=True)
    private_file(key)
    public = key.with_suffix(".pub").read_text().strip()
    row = ensure(api, "ssh_keys", "small-cloud-operator", {"public_key": public})
    if row["public_key"].split()[:2] != public.split()[:2]:
        raise Failure("Registered operator SSH key differs from local dedicated key")
    return row


def foundation(api: API, admin_cidr: str, validation: bool = False, location: str | None = None) -> dict:
    cidr = str(ipaddress.ip_network(admin_cidr, strict=True))
    kinds = ("cpx32", "cpx42") if validation else ("cx33", "cx43")
    quoted = quote(api)
    pinned_location = location
    location = location or next((loc for loc in LOCATIONS if all(any(r["type"] == kind and r["location"] == loc and r["available"] for r in quoted["servers"]) for kind in kinds)), None)
    existing = api.items("servers", label_selector=SELECTOR)
    if existing:
        locations = {s["location"]["name"] for s in existing if s.get("labels", {}).get("role") in ("control", "runtime")}
        if len(locations) == 1:
            location = locations.pop()
    if pinned_location is not None and location != pinned_location:
        raise Failure("Existing foundation location differs from pinned location")
    if location not in LOCATIONS:
        raise Failure("CAPACITY_UNAVAILABLE: selected host pair unavailable in Germany; no resources created, no permanent SKU substitution")
    extra_labels = {}
    if validation:
        expiry = state_directory() / "validation-expiry"
        if not expiry.exists():
            raise Failure("Schedule the validation cleanup timer before provisioning")
        expires = int(expiry.read_text())
        if not time.time() < expires <= time.time() + 7200:
            raise Failure("Validation expiry must be within two hours")
        extra_labels = {"validation": "true", "validation-expires": str(expires)}
    key = ssh_key(api)
    network = ensure(api, "networks", "small-cloud-private", {"ip_range": "10.42.0.0/16", "subnets": [{"type": "cloud", "ip_range": "10.42.0.0/24", "network_zone": "eu-central"}]})
    if network["ip_range"] != "10.42.0.0/16" or not any(s["ip_range"] == "10.42.0.0/24" and s["network_zone"] == "eu-central" for s in network["subnets"]):
        raise Failure("Private network drift; inspect before reapplication")
    output = {"project": "small-cloud (operator identified)", "location": location, "servers": {}, **extra_labels}
    for role, kind, address in (("control", kinds[0], "10.42.0.2"), ("runtime", kinds[1], "10.42.0.3")):
        rules = [{"direction": "in", "protocol": "tcp", "port": "22", "source_ips": [cidr]}]
        if role == "control":
            rules += [{"direction": "in", "protocol": "tcp", "port": port, "source_ips": ["0.0.0.0/0", "::/0"]} for port in ("80", "443")]
        firewall = ensure(api, "firewalls", f"small-cloud-{role}", {"rules": rules})
        api.wait(api.call("POST", f"firewalls/{firewall['id']}/actions/set_rules", {"rules": rules}))
        server = ensure(api, "servers", f"small-cloud-{role}", {"server_type": kind, "location": location,
            "image": "ubuntu-24.04", "ssh_keys": [key["id"]], "firewalls": [{"firewall": firewall["id"]}],
            "public_net": {"enable_ipv4": True, "enable_ipv6": False},
            "labels": {**OWNER, "role": role, **extra_labels},
            "user_data": "#cloud-config\nssh_pwauth: false\ndisable_root: false\n"})
        server = api.call("GET", f"servers/{server['id']}")["server"]
        if server["server_type"]["name"] != kind or server["location"]["name"] != location:
            raise Failure(f"Server drift: {role}; refusing implicit replacement")
        attached = server["private_net"]
        if not attached:
            api.wait(api.call("POST", f"servers/{server['id']}/actions/attach_to_network", {"network": network["id"], "ip": address}))
        elif len(attached) != 1 or attached[0]["network"] != network["id"] or attached[0]["ip"] != address:
            raise Failure(f"Server network drift: {role}")
        if firewall['id'] not in {item['id'] for item in server['public_net']['firewalls']}:
            api.wait(api.call("POST", f"firewalls/{firewall['id']}/actions/apply_to_resources", {"apply_to": [{"type": "server", "server": {"id": server["id"]}}]}))
        server = api.call("GET", f"servers/{server['id']}")["server"]
        attached_firewalls = server["public_net"]["firewalls"]
        if ({item["id"] for item in attached_firewalls} != {firewall["id"]}
                or any(item["status"] != "applied" for item in attached_firewalls)
                or server["labels"].get("role") != role):
            raise Failure(f"Server firewall or role drift after reconciliation: {role}")
        output["servers"][role] = {"id": server["id"], "ipv4": server["public_net"]["ipv4"]["ip"], "private_ipv4": address, "type": kind}
    path = state_directory() / "foundation.json"
    with open(path, "w", opener=lambda p, f: os.open(p, f | os.O_NOFOLLOW, 0o600)) as file:
        json.dump(output, file, indent=2)
    return output


def dns(api: API, address: str) -> dict:
    address = str(ipaddress.IPv4Address(address))
    zones = api.call("GET", "zones?name=monkeysees.one")["result"]
    if len(zones) != 1 or zones[0]["status"] != "active":
        raise Failure("Expected one active monkeysees.one zone")
    zone = zones[0]
    if not {"#dns_records:edit", "#zone:read"}.issubset(zone.get("permissions", [])):
        raise Failure("Cloudflare zone requires DNS Edit and Zone Read")
    path = f"zones/{zone['id']}/dns_records"
    name = "small-cloud.monkeysees.one"
    records = api.call("GET", path + "?name=" + name)["result"]
    marker = "small-cloud issue-17 managed record"
    desired = {"type": "A", "name": name, "content": address, "ttl": 300, "proxied": False, "comment": marker}
    if records:
        if len(records) != 1 or records[0].get("comment") != marker or records[0]["type"] != "A":
            raise Failure("Existing platform DNS record is not owned by this provisioner")
        api.call("PUT", path + "/" + records[0]["id"], desired)
    else:
        api.call("POST", path, desired)
    return {"name": name, "type": "A", "proxied": False, "ipv4": address}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory", help="Read-only resource metadata; no token output")
    sub.add_parser("quote", help="Read-only current EU availability and account prices")
    apply = sub.add_parser("apply", help="Create/reconcile the approved CX33/CX43 foundation")
    apply.add_argument("--admin-cidr", required=True, help="Operator public IP/CIDR allowed SSH access")
    apply.add_argument("--validation", action="store_true", help="Operator-authorized temporary CPX pair with scheduled expiry")
    record = sub.add_parser("dns", help="Create/reconcile only the explicit platform A record")
    record.add_argument("--control-ipv4", required=True)
    args = parser.parse_args()
    try:
        api = API("cloudflare" if args.command == "dns" else "hetzner")
        result = {"inventory": lambda: inventory(api), "quote": lambda: quote(api),
                  "apply": lambda: foundation(api, args.admin_cidr, args.validation), "dns": lambda: dns(api, args.control_ipv4)}[args.command]()
        print(json.dumps(result, indent=2))
        return 0
    except (Failure, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
