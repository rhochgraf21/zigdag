---
kind: constraint
applies_to: [arch]
---
arch works with any coding agent and calls no language model itself. Product-specific support
(skills formats, hook mechanisms) lives only in adapters under `arch.integrate.agent`, each optional,
with a generic fallback that works for any agent.
