---
answer: declined
by: robert
findings:
  - {rule: interface-leaks-storage, subject: arch.integrate.mcp, key: arch-integrate-mcp-interface-leaks-storage}
---
Only serve() and this part's own tests call server(); no other part sees MCPServer. The tests drive the real server on purpose, because the binding to the MCP library is what they check.
