# Publish from an existing coding workflow

An agent-callable CLI publishes a local source folder and returns a URL, allowing creators to keep their existing coding workflow. Templates provide a starting point without restricting supported languages or frameworks. Each tool runs as one Linux container serving HTTP on a platform-provided port, with database access supplied separately. Multiple-container deployments, background workers, scheduled jobs, and privileged containers are deferred.

The platform builds uploaded source remotely from a Dockerfile and returns build logs through the CLI, avoiding a local Docker prerequisite for creators. Isolated build execution is therefore part of the pilot scope.
