---
kind: component
realizes: Convert between files in the design's format and the values they hold, without losing or reformatting human-written content
solution: Markdown files with YAML frontmatter, read with a round-trip parser and edited with minimal text patches
hides: The on-disk file format
uses: [ids, policy, schema]
status: specified
---
## Acceptance criteria
- AC1: For every valid file t, render(parse(t)) shall equal t.
- AC2: When one field of a node changes, the text diff shall touch only the lines of that field.
- AC3: Parse errors shall report file, line and column.
- AC4: When given plain values, the codec shall write a whole file in the design's format from which every value reads back unchanged.
- AC4: Newly created files shall use a canonical field order and formatting.
- AC5: A component's id shall come from its path under design/components, and the file shall not repeat it.

## Rationale
People and agents will hand-edit files occasionally. If arch reformatted on every write, every operation
would produce a noisy diff and nobody would trust it.
