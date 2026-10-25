---
answer: fixed
by: robert
findings:
  - {rule: interface-leaks-storage, subject: arch.model.codec, key: arch-model-codec-interface-leaks-storage-2}
---
Three critics raised this, so the earlier decline was wrong. The codec now publishes read_document, the typed counterpart of document: plain text and lists of one-line mappings, with YAML kept inside. frontmatter and Frontmatter are private, and every ledger file reads and renders back byte for byte.
