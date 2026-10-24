---
kind: constraint
applies_to: [arch]
rule:
  budget:
    context_p95_ms: 300
    scoped_check_p95_ms: 1000
    full_check_cold_s: 30
  reference_repo: ~100k lines of Python, ~300 components, warm cache unless stated
---
arch runs inside agents' edit loops, so it must be fast enough to run on every edit without anyone
deciding whether it is worth it.
