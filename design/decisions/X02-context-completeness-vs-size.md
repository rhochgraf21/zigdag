---
kind: contradiction
status: accepted
improving: Completeness of an agent's context (fewer wrong guesses)
worsening: Context size (cost, distraction)
principles: [TRIZ separation by system level, information hiding]
affects: [arch.view.context]
---
## Resolution
Complete about the component being worked on; neighbours only by external spec (realizes, port,
contracts). Their internals are hidden by design, so leaving them out is correct rather than lossy.
