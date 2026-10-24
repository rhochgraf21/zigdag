---
kind: component
realizes: Load and persist everything arch reads and writes in a project, quickly
solution: Find the project root and optional `arch.toml`, read design files and sources into snapshots, run `git` for history and base revisions, cache facts by content hash under `.arch/cache/`, and write edits atomically
hides: Filesystem layout, caching and version-control invocation
uses: [change, check, model.codec, model.ids, model.schema, realize]
status: specified
---
## Acceptance criteria
- AC1: A warm check on an unchanged tree shall re-extract no files.
- AC2: A batch of edits shall be written entirely or not at all (temporary files, then rename).
- AC3: Deleting the cache at any time shall change no results.
- AC4: The project root shall be found by searching upward for `design/` or `arch.toml`, and the search shall stop at the repository root.
- AC5: Until configured, source roots shall default to `src/` (or the project root when there is no `src/`), and test roots to `tests/`.
- AC6: `[roots] source` and `tests` in `arch.toml` shall replace those defaults; a malformed `arch.toml` shall be a usage error naming the problem.
