---
answer: declined
by: robert
findings:
  - {rule: interface-flag-picks-behaviour, subject: arch.integrate.catalog, key: arch-integrate-catalog-interface-flag-picks-behaviour}
---
A dry run is the same edit stopped before the write, so its preview cannot disagree with what the write would do; it does not pick between different behaviours. AC1 still holds, since a dry run writes less than the operation declares, never more. Separate preview operations would double edit and init on every surface for one branch.
