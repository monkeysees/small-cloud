# CLI usability and discoverability

Status: consolidated design confirmed by the user on 2026-09-09. Implementation is a separate task.

An unfamiliar AI agent must be able to learn how to use Small Cloud from the installed executable, starting with `small-cloud --help`. Essential guidance must be available through the CLI; external documentation and agent skills may supplement it.

Distribute standalone binaries for Linux and macOS on ARM64 and x86-64, with a one-command installer. Installation must not require manual Python environment setup. Native Windows support is deferred. Packaging technology is still to be decided.

First deployment, redeployment, and failure diagnosis are the primary acceptance journeys. Secret management, sharing, and workspace administration must also be easy through the CLI.

Command names, flags, defaults, and output may change where this improves usability. There are currently no real users, so preserving the existing interface is not a constraint.

The current implementation has a versioned JSON response contract, request IDs, noninteractive execution, and operation polling. Its help omits workflow guidance available in repository documentation, and normal success output is indented JSON. The current installation instructions require a Python virtual environment. These are starting-point observations, not decisions to retain those interfaces.

Workspace selection and administration must account for [ADR 0009](adr/0009-multiple-workspaces.md), whose multi-workspace design is approved but not fully implemented.

Keep backend implementation of the pending workspace features in the existing workspace work, applying this CLI design to their commands as they arrive. The command catalog describes only available capabilities. Full workspace acceptance depends on that work; the whole initiative is not complete until those workflows pass.

Expose three connected discovery layers: concise command help with examples; bundled task guides covering app requirements, deployment, updates, and recovery; and a machine-readable command catalog describing arguments, outputs, and effects. Root help must point to all three, available offline without authentication.

The distributed CLI targets the single hosted service and exposes no endpoint override through flags, environment variables, or configuration. This replaces the configurable-endpoint product contract; see [ADR 0010](adr/0010-single-service-cli.md). Login explains required human browser approval. A setup/status command reports the service endpoint, identity, workspace, and missing setup steps.

Deployment waits for readiness by default, with an explicit option to return immediately. Humans receive progress and the final URL; agents receive an unambiguous terminal result. Timeout or interruption identifies the continuing operation and supplies the exact command to inspect it. Secret changes, data resets, and deletion use the same waiting and timeout semantics. This replaces the asynchronous-mutation defaults in the current contracts. Destructive actions retain exact-target confirmation through a human prompt or an explicit argument in automation.

Readable human output is the default; agents explicitly request `--json`. Root help, every command's help, and agent getting-started guidance prominently expose this option and show complete invocation examples. JSON mode and execution without a TTY never prompt for terminal input; missing inputs produce actionable errors. Explicit browser login remains a human approval step.

Organize commands by resource: `app deploy`, `app list`, `app status`, `app logs`, `app secrets`, plus `workspace`, `auth`, and `operation`. Bare `small-cloud` shows a short starting guide. Each group describes its tasks and points to relevant bundled guides.

An explicit project-linking command saves nonsecret app and workspace identifiers in a small project file. Commands explain the resolved target; explicit flags override the saved target. Without a project link, agents must specify the workspace, consistent with ADR 0009's explicit automation targeting. Overriding the linked workspace requires an explicit app target; a saved workspace-bound app must never silently move to another workspace. Missing or inaccessible saved targets fail with relinking instructions. The file has a versioned format, contains no credentials, and is suitable for committing. This replaces the current prohibition on repository configuration.

On deployment failure, show the failed phase, a bounded excerpt of relevant diagnostics, and exact next commands, with equivalent structured JSON information. When the outcome is uncertain, inspect the existing operation before suggesting another deployment. Code changes and new mutations remain the caller's responsibility.

Generate command help and the machine-readable catalog from shared command definitions, including required permissions, inputs, results, and side effects. Version the catalog and allow querying one command or group. Author task guides separately and test their examples.

Provide bundled runtime guidance and an `app check` command that validates what can be checked locally before upload. Explain HTTP port requirements, database configuration, and build exclusions. Local validation does not establish server feasibility. Starter-file generation is deferred; agents can choose their stack using the runtime contract.

Provide an explicit update command and installable completion for Bash, Zsh, and Fish. Installation does not prompt for login or silently modify shell startup files. Ordinary commands do not automatically update the executable.

Acceptance includes fresh agent sessions given only the executable and a task, covering first deployment, redeployment, diagnosis, secrets, sharing, and workspace administration against an isolated test service. Agents must discover the instructions themselves. Pair these trials with automated CLI contract checks and a human walkthrough of installation, login, and deployment. The isolated test service is an internal test seam, not an endpoint override in the distributed product.

Support headless browser approval with separate login start and finish commands. Start returns a verification URL, user code, and local login-attempt identifier; finish waits for approval and saves the credential. The flow supports JSON without requiring pasted credentials. Retain a combined login command for humans. Unattended service-account authentication is outside this work. The local attempt identifier is not the existing protocol's confidential poll secret; implementation must preserve that distinction.

Include `app logs --follow` with readable streaming output for humans and documented newline-delimited JSON for agents. Streaming is an explicit exception to the ordinary single-result JSON contract. Reconnection reports any gaps; Ctrl-C stops observation without affecting the app.

Before implementation is declared complete, reconcile the existing CLI contracts and user guides with these decisions, including endpoint configuration, project configuration, command organization, asynchronous defaults, login behavior, and streaming output. Update the changelog for delivered behavior. Packaging technology, exact command/flag spellings beyond those recorded here, and the project-file schema remain implementation design details subject to these requirements.
