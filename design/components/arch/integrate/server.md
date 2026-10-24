---
kind: component
realizes: Serve the review page on this machine, where reviewers give their verdicts
solution: The standard library's threaded HTTP server bound to 127.0.0.1, accepting verdicts only as JSON from its own page, recording them through the catalog
hides: HTTP
uses: [catalog, model.ids, review.page, review.session, view.render]
status: specified
---
## Acceptance criteria
- AC1: The server shall bind 127.0.0.1 only.
- AC2: A write shall be refused unless it is JSON with this server's Host and no foreign Origin.

## Decisions
### Loopback only, and no randomness needed for safety
- Chose: bind 127.0.0.1; accept writes only as application/json (forcing a CORS preflight the server never grants), with this server's Host (against DNS rebinding) and no foreign Origin
- Over: a random per-session token, or not serving at all
- Because: the determinism constraint forbids randomness, and these checks stop other pages and sites from writing without one
- Backed by: no-network, shell-io
