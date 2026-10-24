---
kind: component
realizes: Exchange everything arch reads and writes with the project's files, quickly
solution: One shell that reads and writes project files, runs git, and caches facts by content hash
hides: Filesystem layout, caching and version-control invocation
uses: [change, check, model.codec, model.ids, model.schema, realize, review.session, review.page]
status: specified
---
## Acceptance criteria
- AC1: A warm check on an unchanged tree shall re-extract no files.
- AC2: A batch of edits shall be written entirely or not at all (temporary files, then rename).
- AC3: Deleting the cache at any time shall change no results.
- AC4: The project root shall be found by searching upward for `design/` or `arch.toml`, and the search shall stop at the repository root.
- AC5: Until configured, source roots shall default to `src/` (or the project root when there is no `src/`), and test roots to `tests/`.
- AC6: When arch.toml sets source or test roots, they shall replace the defaults.
- AC8: The workspace shall give the sources as committed at any revision, the merge base with a revision, and the source files changed since a revision including untracked ones.
- AC7: Test reports shall be read from `[evidence] junit` globs (default `.arch/evidence/*.xml`), and history from the last `[history] commits` commits (default 500) when the project is in a git repository.
- AC9: If arch.toml is malformed, then arch shall report a usage error that names the problem.
