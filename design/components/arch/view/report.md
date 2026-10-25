---
kind: component
realizes: Present the results of checks, edits, diffs and plans to people and agents
solution: One report type per result, each rendering the same content as Markdown or JSON
hides: Formatting of results
uses: [render, change, check.engine, guide.next, guide.plan, model.ids, check.ledger, check.critique]
status: specified
---
## Acceptance criteria
- AC1: Each report shall render as Markdown and as JSON with the same content, and compute nothing itself.
- AC2: A rejected edit shall be reported with the reason and the statement that nothing was changed.
- AC3: A findings report shall list errors and warnings, and count info findings unless asked to list them.

## Decisions
### Results are model objects that render themselves
- Chose: catalog operations return report objects wrapping the model result; surfaces call `to_markdown` or `to_json`.
- Over: the catalog building text and dictionaries.
- Because: code that builds text and dictionaries operates on data; with reports, the model stays the source and each surface picks a rendering.
- Previously: the catalog formatted findings and plans itself.
