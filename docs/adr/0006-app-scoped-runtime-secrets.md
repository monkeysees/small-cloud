# Trust app code with app-scoped runtime secrets

Creators can configure encrypted secrets delivered as runtime environment variables, without build-time access or saved-value readback. This keeps configuration independent of application language and framework while excluding private builds requiring credentials. Changes restart the app; CLI input uses hidden prompts or stdin.

An authorized app user can trigger any credential-backed action exposed by its code. Sharing therefore includes a notice, and creators must supply appropriately scoped credentials; per-user third-party authorization is deferred. The platform isolates apps and protects stored configuration, but cannot prevent app code from disclosing credentials it receives. Restricted logs and known-value redaction reduce exposure without promising confidentiality from the app itself.
