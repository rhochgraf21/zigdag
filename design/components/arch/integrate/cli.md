---
kind: component
realizes: Offer every operation as a shell command for humans, scripts and agents
solution: Commands generated from the catalog, with human-readable output by default, `--json` for machines, and documented exit codes (0 ok, 1 new blocking findings, 2 usage error, 3 internal error)
hides: Argument parsing and terminal formatting
uses: [catalog]
status: specified
---
## Acceptance criteria
- AC1: Every catalog operation shall have exactly one command.
- AC2: `--json` output shall validate against the operation's published result schema.
- AC3: When stdout is not a terminal, output shall have no colour and no interactivity.

## Rationale
The CLI is the primary agent interface. Every agent can run shell commands, and shell commands are
easy to show, reproduce and paste.
