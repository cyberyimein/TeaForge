# Changelog

## 0.2.0 - 2026-07-15

TeaForge moves from an early pytest document demo to a beta-quality, installable CLI.

### Added

- Versioned PCL and coverage artifacts for pytest, Jest, Angular/Jest, and Playwright tests.
- Project-local Jest runtime assertion evidence with expected/actual values, pass/fail state, redaction, and bounded JSONL capture.
- Tree-sitter JavaScript, TypeScript, and TSX syntax evidence shared by parsers and coverage analysis.
- File-level C0/C1 gates, Mermaid flowchart and sequence-diagram report pages, and optional PDF export.
- `teaforge doctor` capability checks and machine-readable JSON output.
- Linux, Windows, Python 3.11-3.14, Node 20/22, packaging, lint, branch-coverage, Jest, Mermaid, and PDF CI gates.

### Changed

- External processes now share monotonic workflow deadlines, retain bounded diagnostics, and clean up descendant processes on timeout.
- Pytest and Jest run from discovered target-project roots without downloading target dependencies.
- Test discovery excludes generated dependency and virtual-environment trees by default.
- Text artifacts are rendered before same-directory atomic replacement.

### Security

- Runtime evidence redacts common credential fields and patterns and enforces value, record, and file-size limits.
- External commands execute without a shell and use exact resolved runner and test paths.
