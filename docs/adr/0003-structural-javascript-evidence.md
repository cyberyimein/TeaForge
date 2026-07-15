# ADR 0003: Isolate JavaScript syntax evidence behind Tree-sitter facts

- Status: Accepted
- Date: 2026-07-15

## Context

TeaForge must infer imports, Jest test identity, calls, exported subjects, and source-function spans without executing a target project. Regex and delimiter scanning can mistake comments or strings for code, diverge between Jest, Angular, Playwright, and coverage adapters, and lose TypeScript/TSX structure. Installing a parser into every target project would violate the local-runner boundary.

## Decision

- TeaForge declares Python Tree-sitter plus JavaScript and TypeScript grammars as its own base dependencies.
- A single JavaScript Syntax Evidence module parses `.js`, `.jsx`, `.mjs`, `.cjs`, `.ts`, `.tsx`, `.mts`, and `.cts` inputs.
- The module exposes stable facts for imports, Jest cases and lexical full names, calls, exported symbols, and source-function spans. Adapter code does not receive raw Tree-sitter nodes.
- Syntax errors carry a stable `javascript-syntax-error` code and source location instead of silently falling back to regex matches.
- The parser never executes code and never reads or changes target-project package dependencies.

## Consequences

Comments and strings cannot create false import or test evidence, and all JavaScript-facing adapters share one grammar boundary. The Python wheel grows by the grammar dependencies. Tree-sitter proves syntax structure only: TeaForge still does not type-check TypeScript, evaluate dynamic imports, or execute computed test construction; runtime evidence remains the appropriate fallback for dynamic values.
