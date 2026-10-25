---
answer: fixed
by: robert
findings:
  - {rule: interface-flag-picks-behaviour, subject: arch.integrate.agent, key: arch-integrate-agent-interface-flag-picks-behaviour}
---
Split handle into orient(ws) and after_edit(ws, payload); the CLI maps the hook event to one of them, and session start no longer takes an edit payload.
