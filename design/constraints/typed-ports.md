---
kind: constraint
applies_to: [arch]
rule:
  port_types:
    forbid: [str, int, float, bool, dict, list, tuple, set, Any]
    allow_in_returns: [bool]
    except_in: [arch.integrate.cli, arch.integrate.mcp, arch.integrate.server]
---
Public ports use domain types (ids, enums, value objects), not bare built-ins. Raw text from users is
parsed into domain types at the CLI and MCP boundary and never travels further as plain strings.
Built-ins are fine inside a component. `bool` is fine as a return value (a predicate); a `bool`
parameter is a flag and should be an enum.
