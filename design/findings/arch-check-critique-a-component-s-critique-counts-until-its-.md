---
kind: idea
station: interface
source: agent
by: claude
subject: arch.check.critique
digest: "5ab25f78be4b"
hint: "Q001 runs without facts in some paths (the critique listing), so the key must be the same with and without facts: perhaps a second question, Q002, keyed by the interface digest and asked only when facts are known."
---
A component's critique counts until its design text changes, but interface questions judge its code: when the public declarations change and the text does not, nobody is asked to judge the new interface. Folding a digest of the interface into the Q001 key would remove the need to remember a re-critique after an API change.
