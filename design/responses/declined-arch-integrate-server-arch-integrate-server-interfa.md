---
answer: declined
by: robert
findings:
  - {rule: interface-leaks-storage, subject: arch.integrate.server, key: arch-integrate-server-interface-leaks-storage}
---
Only serve() and the review tests call make_server(); no other part sees the HTTP server. The tests need the real server to check its loopback, host and origin guards.
