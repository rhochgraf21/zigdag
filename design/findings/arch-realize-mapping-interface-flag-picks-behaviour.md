---
kind: question
station: interface
source: critic
by: interface-flag-picks-behaviour
subject: arch.realize.mapping
digest: a54393cb0646
evidence: "map_units(graph: Graph | None"
hint: "Make the parameter required, as in map_units(graph: Graph, facts: Facts) -> UnitMap, and have callers with no design call UnitMap.without_design(facts)."
---
Passing None for graph switches map_units from mapping units to components into a no-design mode. UnitMap.without_design(facts) already provides that mode, so one function holds two behaviours and the no-design case has two entry points.
