---
kind: component
realizes: Offer every operation to agents as typed callable tools
solution: An MCP server over stdio whose tools are generated from the catalog
hides: The MCP protocol
uses: [catalog, change.ops, model.ids, view.report, check.engine, check.ledger, check.critique]
status: specified
---
## Acceptance criteria
- AC1: Every catalog operation shall be exposed as exactly one tool with the same input schema.
- AC2: The server shall make no network connections.

## Rationale
Secondary to the CLI; useful for agents without shell access, or where typed calls beat parsing text.
