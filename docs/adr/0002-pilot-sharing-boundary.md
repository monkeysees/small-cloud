# Separate company sign-in from app access

The pilot uses company sign-in for identity, while each app's creator chooses creator-only or workspace-wide access. Signing in does not grant access to creator-only apps. Individual invitations and group-based sharing are deferred to keep the initial permission model small while preserving a private publishing scope.

Within a workspace-wide app, every workspace member may read and modify all app data. Per-record ownership and roles are outside the pilot scope.

The platform enforces access before traffic reaches an app and supplies a stable user ID, name, and email. Containers must have no publicly accessible route bypassing enforcement. Use the company's existing identity provider and explicit workspace membership; an email domain alone does not grant access.
