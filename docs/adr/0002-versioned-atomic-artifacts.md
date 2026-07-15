# ADR 0002: Version and atomically replace text artifacts

- Status: Accepted
- Date: 2026-07-15

## Context

TeaForge writes reports that may be consumed by people, scripts, and coding agents. Partial files, silent schema drift, or a mixed set of newly rendered and stale outputs can make a report look valid while containing inconsistent evidence.

## Decision

- PCL JSON and embedded coverage data carry an explicit `schema_version`. Coverage schema 2 also records the evidence provider and metric definitions.
- PCL loading accepts the known legacy form and rejects unknown future schemas.
- Text output is first written to a same-directory temporary file, flushed, synchronized, and atomically replaced.
- Multi-document PCL and coverage workflows parse and render all requested documents before replacing output files.
- Missing custom templates fail explicitly rather than falling back to packaged templates.

## Consequences

An interrupted individual write preserves the previous artifact. Schema incompatibility is visible instead of being guessed. The current guarantee is not a transaction across multiple files, and concurrent writers targeting the same path remain unsupported; those limitations must stay documented until a manifest/transaction protocol is introduced.
