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
