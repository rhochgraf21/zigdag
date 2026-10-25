---
kind: question
station: interface
source: critic
by: interface-leaks-storage
subject: arch.change.ops
digest: "72b6f8001b7f"
evidence: "Draft.file(self, kind: Kind, ident: Text) -> NodeFile"
hint: Have Draft expose and accept domain node values (a component, need or criterion from the model) and let apply turn the changed model into file edits through the codec, as its solution already says.
---
The Draft protocol hands operations a NodeFile and takes one back in put, so every operation reads and writes the per-file storage form of a node instead of a model value. That contradicts AC5's aim that operations never handle files, and ties every operation to the file layout, so the codec cannot change it without touching them all.
