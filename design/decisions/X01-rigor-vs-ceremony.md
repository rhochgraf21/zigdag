---
kind: contradiction
status: accepted
improving: Verifiability (more structure and contracts mean more is checked)
worsening: Authoring and upkeep effort (ceremony), so the design rots
principles: [TRIZ separation in time, ASIT closed world]
affects: [arch.check, arch.guide.infer, arch.integrate.agent]
---
## Resolution
- Separation in time: maturity (draft, specified, contracted, verified). Rules tighten as a component
  matures, so formality is added where and when it pays.
- ASIT closed world: the resource already present, the coding agent, does the authoring through
  validated operations; people review design diffs instead of writing nodes.
- Make the design pay rent daily: context cards and plans make the agent's own work better, so it has
  a reason to keep the design current.
