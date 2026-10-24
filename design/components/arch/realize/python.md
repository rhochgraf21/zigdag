---
kind: component
realizes: Relate Python code to the design
solution: An adapter registered for Python files, made of an AST extractor and a scaffold emitter
hides: Python language details
uses: [facts, model.schema]
exports: []
status: specified
---
## Acceptance criteria
- AC1: The adapter shall never import or execute user code.
- AC2: When a file has a syntax error, the adapter shall emit a parse-error fact for it and continue.
