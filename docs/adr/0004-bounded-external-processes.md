# ADR 0004: Own external process deadlines and cleanup centrally

- Status: Accepted
- Date: 2026-07-15

## Context

TeaForge runs target-project Jest, target-environment coverage.py, and Mermaid CLI. A timeout applied only to the immediate process can leave worker, browser, or test child processes alive. Capturing arbitrary stdout and stderr in memory can also exhaust the TeaForge process before its diagnostic truncation runs.

## Decision

- All external commands pass through one External Process module; adapters do not call `subprocess.run` directly.
- Commands execute without a shell and receive an explicit workflow deadline.
- Multi-stage adapters create one monotonic `WorkflowDeadline`; later commands receive only its remaining budget and are not started after it expires.
- stdout and stderr are drained concurrently while retaining only bounded head/tail diagnostics.
- POSIX commands start in a new session and TeaForge signals the whole process group on timeout.
- Windows commands use a kill-on-close Job Object when available, then `taskkill /T` tree cleanup and direct-process termination as progressively narrower fallbacks.
- Results expose command, exit code, duration, output, and truncation state. Timeouts carry a stable `process-timeout` code and their bounded partial result.

## Consequences

Jest workers and Mermaid's browser no longer outlive an expired TeaForge workflow under the supported process-group mechanisms, and noisy tools cannot grow captured output without bound. Output intended as a machine payload must fit the configured capture limit or be rejected by its downstream parser. Platform process APIs add implementation complexity, so POSIX descendant cleanup is covered by an executable test and Windows Job Object setup fails safely to direct-process cleanup when unavailable.
