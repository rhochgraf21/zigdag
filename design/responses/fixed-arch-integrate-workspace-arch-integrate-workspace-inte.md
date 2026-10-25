---
answer: fixed
by: robert
findings:
  - {rule: interface-leaks-storage, subject: arch.integrate.workspace, key: arch-integrate-workspace-interface-leaks-storage}
---
design_dir is private now; callers use design(), design_files() and the ledger methods, which take design paths.
