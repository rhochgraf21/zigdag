---
kind: question
station: requirements
source: critic
by: requirement-not-from-parent
subject: arch.realize.python.names
digest: "3c65867bcb62"
evidence: Resolve what the names in Python source refer to
hint: Name a name resolver in the parent's solution (for example "an AST extractor, a name resolver it uses, and a scaffold emitter"), or move names under extract and mention resolution in extract's solution.
---
The parent's solution says the adapter is made of an AST extractor and a scaffold emitter, and name resolution is neither of them. The part exists to serve the extractor, so either the parent's solution is incomplete or this part belongs under arch.realize.python.extract.
