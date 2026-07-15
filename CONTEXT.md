# TeaForge Domain Context

TeaForge converts executable test evidence into reviewable engineering artifacts. The implementation should use these terms consistently in code, CLI help, reports, and architecture decisions.

## Core terms

### Test Subject

The source file and function or method whose behavior a test exercises. A subject identity is proven from imports and calls when possible. Coverage generation must fail when source identity cannot be proven; PCL generation may preserve an explicitly marked fallback identity.

### PCL Document

A Program Check List for one Test Subject. It contains design-time inputs and checks, optional runtime evidence, source identity, execution status, warnings, and a stable artifact schema version. One document may be split into multiple 25-column sheets without changing its subject identity.

### Static Evidence

Inputs and expectations inferred without executing the target tests. Static evidence describes test intent, but can be incomplete when values are built dynamically.

### JavaScript Syntax Evidence

Structural Static Evidence produced from TeaForge-packaged Tree-sitter JavaScript, TypeScript, and TSX grammars. Adapters consume stable imports, test cases, calls, exported symbols, and source-function facts rather than grammar nodes. It proves syntax structure, not TypeScript types or runtime values.

### Runtime Evidence

Matcher, expected value, observed actual value, and pass/fail status captured while an already-installed target-project Jest runs. Runtime Evidence supplements rather than replaces Static Evidence.

### Coverage Evidence

Executed and missing statement/branch locations read from Python coverage data or Istanbul JSON. Coverage Evidence is distinct from assertion evidence and must remain traceable to its source file.

### Flowchart

A typed Mermaid diagram of internal control flow for a Test Subject: decisions, loops, error paths, and exits.

### Sequence Diagram

A typed Mermaid diagram of interaction order across participants such as caller, service, persistence, and external systems. TeaForge does not infer a trustworthy sequence solely from assertion values; the caller supplies the reviewed diagram source.

### Artifact

A versioned JSON, HTML, PDF, Mermaid, or SVG output produced from evidence. Text artifacts are written through same-directory temporary files and atomic replacement. Concurrent writers to the same path are outside the current contract.

### Capability Check

A non-mutating `teaforge doctor` check that reports whether a required executable, Python module, packaged resource, renderer, or target-project discovery rule is satisfied.

## Invariants

1. TeaForge never downloads or installs target-project test runners during analysis.
2. Target tests and renderers execute from their discovered context with exact paths, one workflow deadline, memory-bounded captured output, and process-tree cleanup on timeout.
3. A failed test and a failed TeaForge invocation are different results. Evidence-bearing Jest failures use exit code 2.
4. Runtime Evidence never silently overwrites the test's Static Evidence.
5. Unsupported or ambiguous diagram types and source identities fail explicitly.
6. New artifact schemas are versioned; unknown future versions are rejected rather than guessed.
7. Machine-readable command modes emit versioned JSON for both success and post-dispatch failure paths.

## Current boundaries

JavaScript/TypeScript discovery uses structural Tree-sitter grammars rather than regex matching, but it is not a TypeScript type checker and does not evaluate dynamic imports or computed test construction. Runtime evidence has default sensitive-key and common credential-pattern redaction plus size limits, but each organization must decide whether that policy is sufficient. File-level C0/C1 gates are available; organization-wide aggregation and policy profiles remain outside the current contract.

Directory discovery excludes generated dependency and environment trees by default. An explicitly supplied file remains eligible even when it is located under an excluded directory.
