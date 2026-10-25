---
kind: idea
station: requirements
source: agent
by: claude
subject: arch.check.critique
digest: "5ab25f78be4b"
hint: In the critique operation, list nodes with open rule findings as held back, with those findings, instead of putting them in the request.
---
A critique request can include a node that a deterministic lint already flags, such as a field over its word limit, so the critic judges text that must change anyway and the round is wasted. Holding such nodes back until their rule findings are fixed would put the cheap checks before the expensive one.
