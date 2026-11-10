"""The report by direction (DESIGN2 §4.6): each direction of code quality ends as ruff and ty end a run, with all its
checks passed, what was found, or why it was not checked."""

import json

from test_tools import CORE, build

from zigdag import verifies
from zigdag.cli import main


def reported(root, capsys, *full: str) -> list[str]:
    main(["--project", str(root), "check", *full])
    return capsys.readouterr().out.splitlines()


FULL = "--full"


@verifies("zigdag.core.analysis.checks#directions")
def test_each_direction_lists_its_findings_as_a_linter_does_then_says_what_it_found(tmp_path, capsys):
    shown = reported(build(tmp_path), capsys, FULL)
    lint = "src/shop/core.py:2:8: break[lint] shop.core: ruff F401: `os` imported but unused"
    assert lint in shown and shown.index(lint) < shown.index("lint: Found 1 break.")
    assert "typecheck: Found 1 break." in shown  # the type error in charge; the one in tolerated is excepted
    assert "security: Not checked: no rule of it is in force." in shown  # not checked is never reported as passing
    assert shown[-1].endswith("things to do") and shown[-1].startswith("2 breaks")


@verifies("zigdag.core.analysis.checks#directions")
def test_a_direction_with_nothing_found_passes_and_still_counts_its_debt(tmp_path, capsys):
    root = build(tmp_path)
    core = root / "src/shop/core.py"
    core.write_text(CORE.replace("import os\n", "").replace("    return str(cents)\n\n\ndef tolerated",
                                                             "    return cents\n\n\ndef tolerated"))
    shown = reported(root, capsys, FULL)
    assert "lint: All checks passed!" in shown
    assert "typecheck: All checks passed! 1 diagnostic is in excepted code." in shown


@verifies("zigdag.core.analysis.checks#directions")
def test_a_direction_no_rule_checks_says_so_rather_than_passing(tmp_path, capsys):
    shown = reported(build(tmp_path, process=""), capsys, FULL)
    assert "lint: Not checked: no rule of it is in force." in shown
    assert "typecheck: Not checked: no rule of it is in force." in shown


@verifies("zigdag.core.analysis.checks#directions")
def test_a_tool_that_cannot_run_breaks_its_own_direction(tmp_path, capsys):
    root = build(tmp_path)
    (root / "zigdag.toml").write_text((root / "zigdag.toml").read_text() + 'ruff = "no-such-linter"\n')
    shown = reported(root, capsys, FULL)
    failed = next(s for s in shown if "break[tools]" in s)
    assert failed.startswith("lint: break[tools] ruff could not be started")
    assert shown.index(failed) < shown.index("lint: Found 1 break.")


def test_each_finding_in_json_names_its_direction(tmp_path, capsys):
    main(["--project", str(build(tmp_path)), "check", "--json"])
    findings = json.loads(capsys.readouterr().out)
    assert {f["direction"] for f in findings if f["rule"] == "lint"} == {"lint"}
    assert {f["direction"] for f in findings if f["rule"] == "types"} == {"typecheck"}


@verifies("zigdag.cli.plans#summary")
def test_by_default_each_direction_is_one_row_with_its_breaks_and_its_findings_go_to_its_file(tmp_path, capsys):
    root = build(tmp_path)
    shown = reported(root, capsys)
    lint = next(s for s in shown if s.startswith("lint "))
    assert [c.strip() for c in lint.split("  ") if c] == ["lint", "Found 1 break", ".zigdag/check/lint.txt"]
    status = lint.index("Found")  # breaks are listed under the status column
    under = shown[shown.index(lint) + 1]
    assert under == " " * status + "src/shop/core.py:2:8: break[lint] shop.core: ruff F401: `os` imported but unused"
    rows = [s for s in shown if s and not s.startswith(" ") and s.split()[0] in
            ("design", "lint", "typecheck", "architecture", "security", "correctness")]
    assert len(rows) == 6 and len({r.index(r.split()[1]) for r in rows}) == 1  # every status in one column
    assert next(s for s in shown if s.startswith("security ")).split() == ["security", "Not", "checked"]  # why: file
    assert not any("question[" in s for s in shown)  # only in the files
    assert shown[-1] == "To see every finding: zigdag check --full"
    files = {p.name: p.read_text() for p in (root / ".zigdag/check").iterdir()}
    assert set(files) == {"design.txt", "lint.txt", "typecheck.txt", "architecture.txt", "security.txt",
                          "correctness.txt"}  # every direction's, so none is left from an earlier run
    assert files["lint.txt"].splitlines()[-1] == "lint: Found 1 break."


@verifies("zigdag.cli.plans#summary")
def test_only_the_first_breaks_of_a_direction_are_shown_and_the_rest_are_counted(tmp_path, capsys):
    root = build(tmp_path)
    unused = "".join(f"import {m}\n" for m in ("abc", "ast", "base64", "bisect", "csv", "dis", "enum", "glob",
                                                 "gzip", "heapq", "hmac", "html"))
    core = root / "src/shop/core.py"
    core.write_text(core.read_text().replace("import os\n", unused + "import os\n"))  # sorted, as ruff wants
    shown = reported(root, capsys)
    lint = next(i for i, s in enumerate(shown) if s.startswith("lint "))
    assert "Found 13 breaks" in shown[lint]
    assert sum("break[lint]" in s for s in shown) == 10
    assert shown[lint + 11].strip() == "and 3 more breaks in .zigdag/check/lint.txt"


@verifies("zigdag.core.analysis.checks#directions")
def test_code_the_design_does_not_place_is_an_architecture_finding_not_a_design_one(tmp_path, capsys):
    root = build(tmp_path)
    (root / "src/other.py").write_text('"""Code that no design parameter is."""\n')
    main(["--project", str(root), "check", "--json"])
    coverage = [f for f in json.loads(capsys.readouterr().out) if f["rule"] == "coverage"]
    assert coverage and {f["direction"] for f in coverage} == {"architecture"}
