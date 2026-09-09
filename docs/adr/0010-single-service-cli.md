# Bind the CLI to one hosted service

Small Cloud will have one installation, so the distributed CLI targets that service without an endpoint override in flags, environment variables, or configuration. This removes endpoint setup from onboarding and deliberately replaces the configurable-endpoint requirement in [the CLI contracts](../contracts.md); multiple workspaces within the installation remain supported by the design in [ADR 0009](0009-multiple-workspaces.md).

The user confirmed this product boundary on 2026-09-09 during the [CLI design interview](../cli-design.md). Implementation is pending; this decision does not prescribe how internal tests connect to isolated test services.
