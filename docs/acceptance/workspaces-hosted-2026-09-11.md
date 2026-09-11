# Hosted workspace acceptance — 2026-09-11

Hosted follow-up for [#20](https://github.com/monkeysees/small-cloud/issues/20), extending the [198-test local acceptance](workspaces-2026-09-10.md). Commit `4431953` was deployed from a checksum-verified wheel to the existing control host. [Redacted evidence](../evidence/workspaces-hosted-2026-09-11.json) records the upgrade, checks, certificates, builder accounting and cleanup.

## Completed by the agent

The upgrade preserved all three existing apps and app databases. Before/after control-table fingerprints and app-data dump fingerprints matched. Repeating the original bootstrap succeeded. The existing CLI credential retained its identity and default, and the homepage and installer stayed available.

The live CLI created a temporary second workspace with the existing Google-bound operator as designated owner. Matching creation retries returned the same workspace; changed inputs failed. Ownership alone did not grant publishing. Listing, saved selection, explicit overrides and separate creator grants passed. Non-platform creation was denied. Additional disposable identities were admitted through the API, then supplied with operator-seeded, expiring credentials for authorization testing. This setup is explicitly not fresh Google sign-in evidence.

Two apps named `workspace-acceptance-20` were built on fresh German CX23 builders and served from the existing runtime host. They had distinct immutable app IDs and HTTPS URLs. Each retained its own PostgreSQL row; attempts to use the other database, its role or the maintenance database were denied while the correct database remained reachable. Both URLs passed normal certificate verification.

Creator-only content denied the other test identities. Workspace-wide content admitted an overlapping member and denied a member admitted only elsewhere. The API directory and cookie-authenticated HTML directory showed only the selected workspace's permitted app. Administration did not admit the operator to another creator's existing private content. Unauthenticated requests, workspace/URL mismatches, foreign operation IDs, conflicting app/operation identifiers and changed-workspace deployment/sharing retries were denied. Workspace roles remained independent.

Restarting the identity service preserved both app URLs, rows and sharing. The two workspace usage responses reported the same installation-wide remaining build allowance. The public directory correctly initiated Google sign-in with protected flow-cookie flags; actual Google approval and rendered browser behavior remain manual below.

## Operational findings and cleanup

The publishing, lifecycle and diagnostics workers were stopped before acceptance. Starting publishing alone allowed a build but Docker refused runtime startup because its syslog driver could not connect to `/run/small-cloud-diagnostics.sock`. Starting the existing diagnostics collector before retrying resolved this; no runtime code changed. Run the collector before launching apps. The failed build's accounting and cleanup were retained.

Let's Encrypt's secondary validation reported DNS lookup failures. Caddy's configured fallback completed issuance; both app certificates verified normally under `ZeroSSL ECC DV SSL CA 2`. TLS verification was never bypassed and DNS was not modified.

All three builders were deleted: one failed runtime-start attempt and two successful deployments, totaling **58 charged build seconds**. The temporary workspace, identities, credentials, browser sessions, apps, PostgreSQL databases/roles, source staging and runtime allocations were removed. Artifact references were retired for the existing retention jobs; the installation's build charges were preserved. The three original apps and databases remained unchanged. Final counts were one workspace, three identities, three apps, one running container and no pending deployments.

The upgraded identity service and Caddy remain deployed. Publishing, lifecycle and diagnostics were restored to their original stopped states. The protected pre-upgrade snapshot remains under `/run/small-cloud-20-acceptance` on the control host; it is temporary rollback material, not a backup guarantee. No standalone release was published.

## Manual checks — closed by user acceptance

Final acceptance: on 2026-09-11 the user instructed that acceptance testing be considered complete and requested ticket finalization after deleting only `test-one`. That empty workspace and its exclusive test admission were removed; Initial workspace and Lifecheq were preserved, including their identities and memberships. [Final cleanup evidence](../evidence/workspaces-final-2026-09-11.json) records the result. This closes the manual follow-up for #20 by user acceptance; it does not claim an additional agent-observed Google/browser trace. The original instructions below remain as the repeatable procedure.

Release follow-up: [v0.3.1](cli-workspaces-2026-09-11.md) now provides the workspace commands in the published CLI and grants new owners creator privileges automatically. For the manual steps below, use the published CLI and expect `member`, `creator` and `administrator` roles; the earlier instructions describe the policy and release availability at the time of this hosted run.

No callable Chrome tool, `mcporter` or `openclaw` executable was available in this session. These checks require a real Google account and the user's browser. The operator's retained credential and the disposable authorization fixtures do not establish them.

### 1. Fresh designated-owner Google sign-in and first default

Choose a Google email that has not previously been admitted. Create a workspace that you intend to keep: workspace deletion is not yet implemented. On this workstation, use the updated source CLI (the published executable does not yet contain the new workspace commands):

```bash
cd /home/john/workspace/work/small-cloud
/tmp/small-cloud-19-venv/bin/python -m identity.cli workspace create "Your workspace name" --owner NEW_OWNER_GOOGLE_EMAIL --json
```

Replace the name and email. Save the returned workspace ID and the printed request ID. If the result is uncertain, retry the identical command with `--request-id ORIGINAL_UUID`.

The invited owner should use their own machine or OS account so their login does not replace the operator's saved credential. The published CLI already supports these authentication commands:

```bash
small-cloud auth login
small-cloud auth status --json
```

Choose the exact invited Google account and approve only the code shown by that CLI. Confirm `workspace.id` and `default_workspace` equal the newly created ID without a workspace-selection prompt. The roles must be `member` and `administrator`, without `creator`; `platform_administrator` must be false. Do not send credentials or Google tokens back to the agent.

### 2. Real browser directory and gateway

In a private browser window or separate profile, open [the directory](https://small-cloud.monkeysees.one/directory) and sign in as that invited owner. Confirm the correct workspace heading and an empty app directory. Opening `https://small-cloud.monkeysees.one/directory?workspace=ws-initial` as that owner must deny access.

In the operator's browser profile, open the directory and confirm the initial workspace's permitted apps render with usable links. Open one of the operator's existing creator-only apps and confirm it renders. Copy that app URL to the invited owner's private profile, sign in there as the invited owner when asked, and confirm access is denied. The temporary acceptance app URLs in the evidence were removed and should not be used for this check.

Report the new workspace ID and pass/fail for owner login, automatic default, role separation, directory rendering and cross-workspace app denial. No screenshot of private app data is needed. These observations can then be appended to this report.

## Checks awaiting later implementation

Complete-service acceptance remains [#28](https://github.com/monkeysees/small-cloud/issues/28): ownership delegation/transfer/recovery, removal/readmission/restoration, suspension, owner-only deletion, configurable allowances and competing workspace capacity checks depend on its predecessor tickets. They cannot be completed by a manual workaround against the current #20 implementation. Existing local quota tests and earlier foundation evidence are not represented as fresh verification of those future workflows.
