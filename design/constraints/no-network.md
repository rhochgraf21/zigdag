---
kind: constraint
applies_to: [arch]
rule:
  effects:
    forbid: [network]
    except_in: [arch.integrate.server, arch.integrate.cli]
---
arch never opens a network connection. It works offline, needs no account, and sends nothing anywhere.
The one exception is the review page's server, which listens on 127.0.0.1 only (see the decision on
arch.integrate.server); the CLI may start it but has no direct network effect of its own.
Publishing results (for example posting a review comment) is done by the host CI system with arch's output.
