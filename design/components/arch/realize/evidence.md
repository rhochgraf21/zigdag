---
kind: component
realizes: Extract verification results from reports produced by other tools
solution: Readers for JUnit XML, coverage.py JSON, pytest-benchmark JSON and mutmut results, linked to acceptance criteria through `@realizes` on tests
hides: Report formats
uses: [facts]
status: specified
---
## Acceptance criteria
- AC1: Each test result shall be linked to the acceptance criteria named by `@realizes` on that test.
- AC2: A missing report shall yield "no evidence", never "failed".
- AC3: Evidence shall record the revision it was produced from when the report provides it, otherwise freshness `unknown`.

## Decisions
### Read reports; don't run the tools
- Chose: read the reports that test, coverage, benchmark and mutation tools produce, and link them to acceptance criteria; CI runs the tools.
- Over: arch running test suites and benchmarks itself.
- Because: arch stays fast enough for edit loops, and deterministic.
- Consequences: evidence can be stale, so freshness is tracked; benchmark noise stays with the benchmark setup.
