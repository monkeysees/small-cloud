# Work tracker: GitHub Project

Coordinate work in [Small Cloud Pilot](https://github.com/users/monkeysees/projects/1), owned by `monkeysees`, project number `1`. Use the gh CLI with the `project` scope; infer the repository from origin. Issues retain specifications, acceptance criteria, comments and history; the Project owns execution order and work status.

- Add every specification and implementation issue to the Project, including closed work for historical context.
- Set `Execution order` to the intended sequence and `Phase` to its delivery stage. Order expresses preference; native issue dependencies determine what can start. Independent issues may proceed together.
- Maintain `Status` (`Todo`, `In Progress`, `Done`) and `Readiness` (`Ready`, `Needs access`, `Blocked`, `Closed`). Readiness is maintained explicitly, not automatically derived from dependencies. Check open blockers and access prerequisites before starting work, and reassess dependents when closing or superseding an issue.
- Use native blocked-by relationships as the dependency source of truth. Keep any written `Blocked by` sections consistent. A closed predecessor with unfinished work must be replaced by the successor, not treated as satisfied.
- Closed specification #1 remains the requirements reference. Closed assessment #2 is superseded by infrastructure #17; neither closure establishes pilot completion. Preserve GitHub close reasons when showing closed work as `Done`.

- Publish specs as issues; implementation tickets are separate issues.
- Read Project fields, issue bodies, labels, comments and native dependencies before acting.
- For public bodies and comments, write a temporary file using a quoted heredoc, inspect it, and pass --body-file.
- Use the role mappings in triage-labels.md.
- Link implementation tickets to their originating specification.
- PRs as a request surface: no.
