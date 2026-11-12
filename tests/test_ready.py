"""`zigdag ready` (DESIGN2 §4.6): one answer for a whole change, and every reason when the answer is no."""

from pathlib import Path

from zigdag import verifies
from zigdag.cli import plans, read_code, read_project
from zigdag.cli.files import from_disk
from zigdag.cli.plans import Outcome, Presence, WatchedRun
from zigdag.core.checks.run import analyse

SETTINGS = '[settings]\nruleset = 1\n[adapters]\ndefault = "python"\n[adapters.python]\nsource = ["src"]\n'
CUSTOMER = """
keep-notes:
  job: Keep notes for later
  performer: Writer
  outcomes:
    lost-note: Minimize the likelihood that a kept note is lost
"""
FUNCTIONAL = """
frs:
  notes:
    statements:
      keep: The notes shall keep each note that a writer adds.
"""
CLEAN = {"zigdag.toml": SETTINGS, "pyproject.toml": '[project]\nname = "notes"\ndependencies = []\n',
         "design/customer.yaml": CUSTOMER, "design/functional.yaml": FUNCTIONAL,
         "src/notes/__init__.py": '"""Notes."""\n'}
TESTS_PASSED, TESTS_FAILED = plans.ExitCode(0), plans.ExitCode(1)


def project(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    for name in ("design/customer.yaml", "design/functional.yaml"):  # as zigdag fmt leaves them
        formatted, _ = plans.format_text(name, (root / name).read_text())
        (root / name).write_text(formatted)
    return root


def answer(root: Path, tests: plans.ExitCode) -> Outcome:
    """What ready says of the project as it is on disk, had its tests just ended this way."""
    run = WatchedRun(False, Outcome(), "", root / ".zigdag/observed.json", ("pytest",), root, {})
    return plans.ready(run, Presence.PRESENT, tests, analyse(read_project(root), read_code(root)), (), None,
                       from_disk(root))


@verifies("zigdag.cli.plans#ready")
def test_ready_says_yes_only_when_nothing_stands_in_the_way_and_no_with_every_reason(tmp_path):
    clean = project(tmp_path / "clean", CLEAN)
    yes = answer(clean, TESTS_PASSED)
    assert yes.exit == plans.OK and yes.out[-1] == plans.READY  # a requirement with no test yet is work, not a no

    failed = answer(clean, TESTS_FAILED)
    assert failed.exit == plans.FOUND and failed.out[-1].splitlines() == [
        plans.NOT_READY, "  the tests failed (they exited 1)"]

    reaching = project(tmp_path / "reaching", {**CLEAN, "src/notes/__init__.py": '"""Notes."""\nimport requests\n'})
    (reaching / "design/functional.yaml").write_text(FUNCTIONAL + "\n\n")  # no longer as zigdag fmt leaves it
    no = answer(reaching, TESTS_PASSED).out[-1].splitlines()
    assert no[0] == plans.NOT_READY and "  1 break" in no  # requests is imported, and the project does not declare it
    assert "  1 design file is not in its layout: zigdag fmt" in no


TEST_OF_KEEP = ('from zigdag import verifies\nimport notes\n\n\n@verifies("notes#keep")\n'
                'def test_a_note_is_kept():\n    assert notes\n')
RESTATED = FUNCTIONAL.replace("each note that a writer adds", "each note that a writer adds or changes")


def unverified(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """What a change from one set of files to another leaves unverified, as each finding says it."""
    changes = plans.Changeset.of("main", plans.analysis(before), plans.analysis(after))
    return [f.say for f in changes.unverified]


@verifies("zigdag.core.analysis.checks#changed-statements")
def test_a_statement_that_changed_is_to_do_until_a_test_that_verifies_it_changes_too():
    tested = {**CLEAN, "tests/test_notes.py": TEST_OF_KEEP}
    restated = {**tested, "design/functional.yaml": RESTATED}
    assert unverified(tested, tested) == []
    assert unverified(tested, restated) == ["notes#keep changed since main, and no test that verifies it has: change "
                                            "a test to fit what it says now, or add one"]

    edited = TEST_OF_KEEP.replace("assert notes", "assert notes is not None")
    assert unverified(tested, {**restated, "tests/test_notes.py": edited}) == []
    another = TEST_OF_KEEP + TEST_OF_KEEP.replace("test_a_note_is_kept", "test_a_changed_note_is_kept")
    assert unverified(tested, {**restated, "tests/test_notes.py": another}) == []

    moved = "\n\n" + TEST_OF_KEEP  # the same test on other lines is the same test
    assert len(unverified(tested, {**restated, "tests/test_notes.py": moved})) == 1
    assert unverified(CLEAN, {**CLEAN, "design/functional.yaml": RESTATED}) == []  # no test at all: said elsewhere


@verifies("zigdag.cli.plans#ready")
def test_ready_holds_a_change_to_the_statements_it_changed(tmp_path):
    tested = {**CLEAN, "tests/test_notes.py": TEST_OF_KEEP}
    root = project(tmp_path / "restated", {**tested, "design/functional.yaml": RESTATED})
    run = WatchedRun(False, Outcome(), "", root / ".zigdag/observed.json", ("pytest",), root, {})
    no = plans.ready(run, Presence.PRESENT, TESTS_PASSED, analyse(read_project(root), read_code(root)),
                     (plans.analysis(tested),), "main", from_disk(root))
    # the test never ran here, which is its own reason; the changed statement is the last one
    assert no.exit == plans.FOUND and no.out[-1].splitlines()[-1] == (
        "  the change adds 1 thing to do since main: old gaps are debt, and new ones are not let in")
