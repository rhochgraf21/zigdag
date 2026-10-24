---
kind: contradiction
status: accepted
improving: Strictness of checks (departures caught)
worsening: Adoption on existing code (wall of red on day one)
principles: [TRIZ separation in time, TRIZ separation by condition]
affects: [arch.check.baseline, arch.guide.infer, arch.check]
---
## Resolution
- In time: baseline ratchet. Existing findings never block, new ones always do, fixed ones cannot return.
- By condition: severity scales with maturity, and inferred designs start with uses equal to observed
  imports, so day one is green.
