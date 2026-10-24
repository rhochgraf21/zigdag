---
kind: constraint
applies_to: [arch]
rule:
  effects:
    forbid: [network]
---
arch never opens a network connection. It works offline, needs no account, and sends nothing anywhere.
Publishing results (for example posting a review comment) is done by the host CI system with arch's output.
