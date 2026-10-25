---
kind: question
station: interface
source: critic
by: interface-leaks-storage
subject: arch.model.codec
digest: "5606e2868690"
evidence: "frontmatter(path: DesignPath, text: SourceText) -> Frontmatter"
hint: Keep frontmatter parsing private and give callers domain values instead, e.g. a typed reader for the non-node files they need, so only the codec knows the files have frontmatter.
---
The codec hides the on-disk file format, yet publishes a function and type for the raw YAML frontmatter (untyped field values plus body). Any caller that uses it is tied to files having YAML frontmatter, so the format can no longer change freely.
