---
kind: question
station: interface
source: critic
by: interface-leaks-storage
subject: arch.model.codec
digest: "971efe3c4740"
evidence: "render(value: FieldValue) -> YamlScalar"
hint: Make scalar, render and YamlScalar private to the codec, and let callers pass domain FieldValues to NodeFile.set_field and NodeFile.new, which do the encoding inside.
---
The codec says it hides the on-disk file format, but its public functions return YAML-encoded scalars, so callers write pieces of the storage format themselves. Moving off YAML, or changing how scalars are quoted, would break every caller of scalar and render.
