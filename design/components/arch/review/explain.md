---
kind: component
realizes: Say why each code change was made and what the names in it mean
solution: Reasons traced from changed criteria, their tests, changed interfaces and new components, and names resolved from code facts
hides: How reasons and names are traced
uses: [model.ids, realize.facts]
status: specified
---
## Acceptance criteria
- AC1: Each code change shall state every reason traced for it, or state that no reason was given.
- AC2: When a changed definition is linked to a criterion that the change added or reworded, the change shall cite that criterion.
- AC3: When a test of such a criterion calls a changed definition, the change shall cite that criterion.
- AC4: When a changed line calls an interface that the change altered or removed, the change shall cite that interface.
- AC5: When every changed line other than blank lines calls such an interface, the change shall be marked as a follow-on.
- AC6: When code belongs to a component that the change adds, the change shall cite that component.
- AC7: Each name in a changed line that resolves to a definition shall carry the signature and description of that definition.
- AC8: When every changed line is an import or part of the list of exported names, the change shall say that it only changes imports.
- AC9: A new file shall be explained one top-level definition at a time.
- AC10: When a changed definition's signature changed and its description did not, the change shall ask whether the description is still true.
- AC11: When a new or changed interface name needs a description and has none, the change shall say so.
- AC12: Each local variable in a changed line shall carry the line that set it.

