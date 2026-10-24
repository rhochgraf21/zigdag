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

## Rationale
arch observes evidence; CI produces it (D06). That keeps arch fast, deterministic and out of the
business of running test suites.
