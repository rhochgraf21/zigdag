---
kind: component
realizes: Convert between design files and nodes without losing or reformatting human-written content
solution: A Markdown-with-YAML-frontmatter codec built on a round-trip YAML parser; edits are applied as minimal text patches to the original file
hides: The on-disk file format
uses: [ids, policy, schema]
status: specified
---
## Acceptance criteria
- AC1: For every valid file t, render(parse(t)) shall equal t.
- AC2: When one field of a node changes, the text diff shall touch only the lines of that field.
- AC3: Parse errors shall report file, line and column.
- AC4: Newly created files shall use a canonical field order and formatting.
- AC5: The id of a component shall be derived from its path under `design/components/`; files shall not repeat it.

## Rationale
People and agents will hand-edit files occasionally. If arch reformatted on every write, every operation
would produce a noisy diff and nobody would trust it.
