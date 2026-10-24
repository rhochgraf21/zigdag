---
kind: constraint
applies_to: [arch.integrate]
rule:
  effects:
    allow: [fs.read, fs.write, subprocess, stdio, env, network]
  direct_effects:
    arch.integrate.workspace: [fs.read, fs.write, subprocess]
    arch.integrate.cli: [stdio, env]
    arch.integrate.mcp: [stdio]
    arch.integrate.server: [network]
---
Effects happen only in the shell, and only four parts of it cause them. Other integrate components
have effects only by calling those four. `subprocess` runs only `git`. Only the CLI reads `env`, which
holds the working directory and the arguments. Only the review server uses `network`, and only on the
local machine.
