# Cloud access for infrastructure #17

## Start here

Read `docs/agents/issue-tracker.md`, then the current issue #17 body, comments and Project fields. The operator has selected Hetzner and authorized infrastructure setup. Use `docs/hosting-research.md` for the approved builder policy and cost assumptions, `docs/contracts.md` for product contracts, and `docs/hosting-validation.md` plus `probes/hosting/README.md` for the acceptance gate. Earlier provider-selection holds are superseded; live isolation and deployment acceptance are still required.

## Operator settings

| Setting | Value |
| --- | --- |
| Hetzner project | `small-cloud` (operator-confirmed) |
| Hosting locations | Germany only: `nbg1` or `fsn1` |
| Platform domain | `small-cloud.monkeysees.one` |
| Cloudflare zone | `monkeysees.one` |
| Alert recipient | `monkeyseesone@gmail.com` (operator-confirmed; use instead of the checkout's placeholder Git email) |

## Credentials on this workstation

| Provider | Token file |
| --- | --- |
| Hetzner | `/home/john/.config/small-cloud/secrets/hetzner-token` |
| Cloudflare | `/home/john/.config/small-cloud/secrets/cloudflare-token` |

Each file contains only its token. These files are local and outside Git; another machine will need its own credential setup. Verify directory ownership/mode `0700` and file ownership/mode `0600` without printing contents. Read tokens directly inside the API client process and use bearer authorization headers. Keep values out of command arguments, shell tracing, tool output, logs, source and provisioning state. Report only redacted authentication outcomes and resource metadata needed for the task. If a file is missing or rejected, identify that exact credential rather than requesting both again.

Hetzner needs a project-bound Read & Write token. Cloudflare needs DNS Edit and Zone Read restricted to `monkeysees.one`. Use the provider APIs from this workspace; browser access is not a prerequisite for provisioning/DNS. Consult current official API documentation before implementing calls:

- Hetzner: `https://api.hetzner.cloud/v1/`; [reference](https://docs.hetzner.cloud/reference/cloud).
- Cloudflare: `https://api.cloudflare.com/client/v4/`; [reference](https://developers.cloudflare.com/api/).

## Verify before provisioning

1. Authenticate to Hetzner and inspect existing project resources before creating anything. Read server types, German locations and current prices. Apply the approved CX23 → CPX22 builder policy from the hosting notes; recheck availability at creation time.
2. Verify the Cloudflare token, look up `zones?name=monkeysees.one`, and inspect the returned zone permissions and relevant DNS records. Discover the zone ID from this lookup. Preserve unrelated records, including the existing proxied `*.monkeysees.one` wildcard; use explicit platform records as needed.
3. Generate/register a dedicated SSH key during bootstrap if none exists. Confirm provisioning permissions, account quotas, SSH connectivity, DNS/TLS and renewal through actual implementation checks. Keep platform API credentials outside untrusted builds and tool runtimes.
4. Configure alerts to the recipient above and verify delivery as part of #17. An email address alone supplies no SMTP/API sending authority; establish an actual delivery mechanism during implementation and report any required access precisely.

## Verified state — 2026-09-08

Both token files were readable with the expected permissions. Hetzner authenticated successfully; inspected server, network, volume, firewall and SSH-key collections were empty. The operator identified the token's project as `small-cloud`; authentication alone did not independently establish its display name. Cloudflare reported an active token, an active zone, DNS Edit and Zone Read; public nameservers matched Cloudflare. The chosen platform hostname had no explicit record and resolved through the existing wildcard.

These checks were read-only. Hetzner write permission, provisioning quotas, SSH, TLS and alert delivery remain untested. No infrastructure implementation existed when this handoff was recorded. Refresh this status as #17 produces evidence; successful account access does not establish build/runtime isolation or permission to admit creator workloads.
