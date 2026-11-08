"""Reading what zigdag needs of a project, from disk or from a git revision. Only the reading is here: which files to
read, and what was read, are decided in plans.py. Everything after this works on text.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from zigdag.cli import plans
from zigdag.cli.plans import Files, GitError, Presence

GIT = "git"
ENCODING = "utf-8"
_ABSENT = (FileNotFoundError, IsADirectoryError, NotADirectoryError)  # what reading a file that is not there raises


def text(path: Path) -> str | None:
    """A file's text, or None when there is no such file."""
    try:
        return path.read_text(encoding=ENCODING)
    except _ABSENT:
        return None


def from_disk(root: Path) -> Files:
    where = plans.on_disk(root)
    reading = plans.Reading.of(text(where.settings), Presence(where.conventional_source.is_dir()))
    paths = plans.present(root, [(path, Presence(path.is_file())) for path in where.always])
    for base in plans.walked(root, reading):
        for here, folders, names in os.walk(base):
            folders[:] = plans.visited(folders)
            paths.extend(plans.found(root, here, names))
    return {path: plans.at_root(root, path).read_text(encoding=ENCODING) for path in reading.chosen(paths)}


def _git(root: Path, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([GIT, "-C", f"{root}", *args], capture_output=True, input=stdin)


def _git_read(root: Path, revision: str, paths: Sequence[str]) -> dict[str, str]:
    """The text of each path at the revision, read in one git process. Paths absent there are left out."""
    done = _git(root, "cat-file", "--batch", stdin=plans.batch_request(revision, paths))
    return plans.batch_texts(paths, done.stdout)


def from_git(root: Path, revision: str) -> Files:
    """The project's files as they are at a git revision."""
    done = _git(root, "ls-tree", "-r", "--name-only", revision)
    listing = plans.listed(revision, done.returncode, done.stdout, done.stderr)
    if listing.failed:
        raise GitError(listing.error)
    reading = plans.git_reading(listing, _git_read(root, revision, listing.settings_paths))
    return plans.git_files(reading, _git_read(root, revision, reading.chosen(listing.paths)))
