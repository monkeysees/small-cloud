# Small Software Cloud

A cloud for purpose-built software used by one person or a small group, including colleagues sharing bespoke apps.

## Language

**Small software**:
Purpose-built software intended for one person or a small handful of users.

**Prototype**:
Small software shared to demonstrate or explore an idea.

**App**:
Small software published by a creator for use by themselves or their workspace. Each app belongs to exactly one fixed workspace, within which its name is unique. The term does not imply a data durability guarantee.
_Avoid_: Tool

**Disposable data**:
Data that users can afford to lose, even when it survives ordinary restarts and redeployments.

**Workspace**:
A group within which small software can be shared, with its own membership, apps, data, and secrets. Workspaces may belong to unrelated people or organizations.

**Creator**:
The person who publishes an app and chooses its sharing scope.

**Sharing scope**:
The audience allowed to access an app: its creator alone or everyone in its workspace.

**Workspace administrator**:
A workspace member who admits members, grants creator privileges, and can disable apps within that workspace. A workspace can have multiple administrators.

**Platform administrator**:
The operator who creates workspaces and appoints their initial workspace administrators.

**Workspace owner**:
The single designated member with all workspace-administrator powers who cannot be removed or demoted by other workspace administrators. The platform administrator designates the initial owner.

**Workspace member**:
A person explicitly admitted to a workspace who can use its workspace-wide apps. One person can belong to multiple workspaces with independent roles; membership alone does not grant creator privileges.

**App secret**:
A creator-configured confidential value entrusted to an app, such as an external service credential. Authorized users can trigger the actions the app exposes using that value.

**Active app**:
A deployed app currently running and occupying one of the workspace's limited execution slots. A deployed app can remain available to start without being active.

**Build allowance**:
The workspace's monthly allocation of build execution time, shared by all creators.
