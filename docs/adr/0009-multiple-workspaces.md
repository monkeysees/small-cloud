# Support independently administered workspaces

Small Cloud is intended for anyone, including unrelated people and organizations sharing one installation. Replace ADR 0005's single-company workspace boundary with multiple workspaces that separate membership, apps, data, and secrets; one identity may hold independent roles in several workspaces. Platform administrators create workspaces and appoint their initial workspace administrators, while each workspace may have multiple administrators managing its own membership and creator privileges, so authority in one workspace grants nothing in another.

Initial onboarding is operator-assisted and open to unrelated users: platform administrators create workspaces on request. Public self-service creation is deferred so its resource-abuse and spending controls can be addressed separately.

Each app belongs to one fixed workspace, with a workspace-unique name. Workspace-wide sharing reaches only that workspace's members; cross-workspace sharing and app moves are deferred to keep authorization boundaries explicit.

Platform administrators set per-workspace resource limits, with installation-wide limits preventing infrastructure overcommitment. Workspace administrators can view usage but cannot increase their allowances. Configurable defaults are five creators, 30 deployed apps, five active apps, and 1,000 build minutes per month. Owners receive administrator and creator privileges automatically and count toward creator limits. Other administrators count only when separately granted creator privileges. Creating a workspace does not reserve or guarantee runtime capacity.

Each workspace has exactly one owner with all workspace-administrator powers, initially designated by the platform administrator. Workspace administrators can appoint and remove administrators and remove members, but cannot remove or demote the owner. They can disable apps and inspect diagnostics; their role does not grant access to creator-only content or secret values.

Removing a creator denies their access to that workspace immediately and disables their apps there, preserving data under the existing retention rules. Membership, roles, and apps in other workspaces remain unaffected.

The CLI supports an explicit `--workspace` override and a saved default. The first workspace is automatically made the default without prompting. Automation should specify its target workspace explicitly. Losing access to the default requires explicit selection of another workspace; the CLI must not silently redirect commands.

The owner can transfer ownership to an existing member who must accept; the previous owner remains an administrator. An owner must transfer ownership before leaving. Platform administrators can reassign ownership for recovery. This is a trusted operational exception: a replacement owner can delete the workspace or lift an owner-imposed suspension, so owner-only controls depend on appropriate use of recovery authority.

Only the workspace owner can delete the workspace, with explicit confirmation, deleting its apps and data; platform administrators have no independent deletion authority. Owners and platform administrators can independently suspend a workspace. Only the owner can lift an owner-imposed suspension, and only platform administrators can lift a platform-imposed suspension. Both restrictions must be cleared before operation resumes. Suspension blocks app access, publishing, and running apps while retaining data and limited management access needed to inspect status and resume; resuming restores eligibility to run.

Platform-administrator status does not grant private app content or secret-value access through the product. App access still requires workspace membership and permission under the app's sharing scope. Direct infrastructure access remains a separate operator trust boundary.

Retain Google sign-in and explicit admission by exact email. Admission and creator grants apply independently in each workspace; email-domain matching grants no access. A removed creator who is readmitted returns as a member, needs a fresh creator grant, and their old apps remain disabled until explicitly re-enabled.

Workspace administrators, including the owner, and platform administrators can re-enable a readmitted creator's apps after a fresh creator grant. Creators cannot reverse administrative disabling themselves. Restoration preserves the previous sharing scope and remains subject to workspace suspension and capacity limits.

Expose workspace creation, membership, roles, ownership transfer, suspension, and deletion through CLI commands backed by authenticated APIs. The browser continues to handle sign-in and the app directory; a workspace administration interface is deferred.

Migrate existing users and apps into one initial workspace, preserving app URLs, data, sharing scopes, and creator grants. The current operator becomes both its initial owner and a platform administrator.

The user confirmed this design on 2026-09-09, including the ownership-recovery trust boundary, and changed owner defaults to include creator privileges on 2026-09-11. The implementation and pilot specification still describe the existing single-workspace service; implementation is a separate task.

Track delivery through [specification #18](https://github.com/monkeysees/small-cloud/issues/18) and implementation tickets #19–#28 in the [GitHub Project](https://github.com/users/monkeysees/projects/1).
