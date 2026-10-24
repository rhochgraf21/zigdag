---
kind: decision
status: accepted
affects: [arch.realize.evidence, arch.check.conformance]
---
## Context
arch could run test suites, benchmarks and mutation testing itself.

## Decision
arch reads the reports those tools produce (JUnit, coverage, pytest-benchmark, mutmut) and links them
to acceptance criteria. CI runs the tools.

## Consequences
arch stays fast enough for edit loops and deterministic. Performance evidence keeps its noise (which
belongs to the benchmark setup, not to arch). Evidence can be stale, so freshness is tracked.
