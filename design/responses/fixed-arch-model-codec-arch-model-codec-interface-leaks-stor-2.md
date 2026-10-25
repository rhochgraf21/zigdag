---
answer: fixed
by: robert
findings:
  - {rule: interface-leaks-storage, subject: arch.model.codec, key: arch-model-codec-interface-leaks-storage-1}
---
First declined; reversed after two more critics raised the same leak. The codec now publishes read_document, typed like document, and frontmatter is private.
