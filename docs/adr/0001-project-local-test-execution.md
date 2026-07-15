# ADR 0001: Execute target-project test runners locally

- Status: Accepted
- Date: 2026-07-15

## Context

TeaForge can execute pytest or Jest to collect coverage and Jest assertion evidence. Invoking a network-aware package launcher such as `npx` can download an unreviewed runner, select a version different from the target lockfile, and execute from the wrong directory. Running TeaForge's own Python for an unrelated target virtual environment can likewise produce incorrect imports or coverage.

## Decision

- Jest is discovered only from the nearest target project or an ancestor workspace `node_modules/.bin/jest`.
- TeaForge invokes Jest directly, runs from the discovered target project root, and passes exact test paths.
- TeaForge never invokes `npx` or performs dependency installation.
- Jest runtime and coverage processes have explicit timeouts.
- Pytest coverage accepts `--python-executable` so the caller can select the target project's virtual environment without resolving away its launcher symlink.
- Pytest coverage discovers the nearest project configuration root, runs collection and JSON export from that root, and resolves relative coverage file identities against the same root.
- `teaforge doctor --path ...` performs non-mutating discovery before generation.

## Consequences

The target project's package-manager installation step is explicit and reproducible. Missing runners fail with an actionable error rather than causing implicit network access. Callers are responsible for selecting a trusted target environment and an appropriate timeout.
