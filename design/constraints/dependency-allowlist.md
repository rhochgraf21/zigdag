---
kind: constraint
applies_to: [arch]
rule:
  imports:
    allow_third_party: [ruamel.yaml, deal, mcp]
    allow_third_party_in:
      arch.realize.treesitter: [tree_sitter]
---
Runtime dependencies are few and deliberate: a round-trip YAML parser, deal for contracts on arch's own
ports, the MCP SDK and tree-sitter (both optional extras). The CLI uses the standard library. Test tooling (pytest, hypothesis, crosshair,
mutmut) is development-only. Adding a runtime dependency requires a decision record.
