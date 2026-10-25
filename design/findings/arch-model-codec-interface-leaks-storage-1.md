---
kind: question
station: interface
source: critic
by: interface-leaks-storage
subject: arch.model.codec
digest: "971efe3c4740"
evidence: "Frontmatter.fields: Mapping[FieldName, object] | None"
hint: Keep Frontmatter and frontmatter() internal and have callers use parse/load, which return typed Nodes. If a caller really needs partial reads, return typed domain fields instead of Mapping[FieldName, object].
---
frontmatter() returns the raw parsed frontmatter as an untyped mapping of objects. That is the file's storage representation, not a domain value, so callers have to interpret file data and are tied to the frontmatter layout the codec is meant to hide.
