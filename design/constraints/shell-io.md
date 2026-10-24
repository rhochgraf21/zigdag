---
kind: constraint
applies_to: [arch.integrate]
rule:
  effects:
    allow: [fs.read, fs.write, subprocess, stdio, env]
  direct_effects:
    arch.integrate.workspace: [fs.read, fs.write, subprocess]
    arch.integrate.cli: [stdio, env]
    arch.integrate.mcp: [stdio]
---
The shell is where effects happen, and only in three places. Other integrate components may have
effects only transitively, by calling those three. `subprocess` is limited to running `git`; `env`
(working directory, arguments) is read only by the CLI.
