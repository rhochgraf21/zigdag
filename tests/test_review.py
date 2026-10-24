from __future__ import annotations

import subprocess

from arch import realize, realizes
from arch.check import check
from arch.integrate.cli import main
from arch.model import codec
from arch.model.graph import Graph
from arch.model.ids import DesignPath, Text
from arch.realize.facts import Compatibility, FileChange, LineNo, PortChangeType, Roots, Snapshot, SourcePath, port_changes
from arch.realize.history import NumStat, parse_numstat
from arch.review.summary import Risk, ReviewInput, review
from tests.conftest import NEED, component

ROOTS = Roots(("src",), ("tests",))


def facts(code):
    return realize.extract(Snapshot({SourcePath(k): v for k, v in code.items()}, ROOTS))


@realizes("arch.realize.facts#AC2")
def test_port_changes_are_classified_for_callers():
    before = facts({"src/m.py": (
        "import deal\n"
        "def gone(): ...\n"
        "def grows(a: A) -> R: ...\n"
        "def optional_extra(a: A) -> R: ...\n"
        "def returns(a: A) -> R: ...\n"
        "@deal.pre(lambda a: a)\ndef guarded(a: A) -> R: ...\n")})
    after = facts({"src/m.py": (
        "import deal\n"
        "def grows(a: A, b: B) -> R: ...\n"
        "def optional_extra(a: A, b: B = B()) -> R: ...\n"
        "def returns(a: A) -> S: ...\n"
        "@deal.pre(lambda a: not a)\ndef guarded(a: A) -> R: ...\n"
        "def fresh(): ...\n")})
    got = {(p.symbol, p.type): p.compatibility for p in port_changes(before, after)}
    assert got == {
        ("gone", PortChangeType.REMOVED): Compatibility.BREAKING,
        ("grows", PortChangeType.SIGNATURE): Compatibility.BREAKING,
        ("optional_extra", PortChangeType.SIGNATURE): Compatibility.COMPATIBLE,
        ("returns", PortChangeType.SIGNATURE): Compatibility.NEEDS_REVIEW,
        ("guarded", PortChangeType.CONTRACT): Compatibility.NEEDS_REVIEW,
        ("fresh", PortChangeType.ADDED): Compatibility.COMPATIBLE,
    }


def test_names_kept_through_a_package_facade_are_not_removed():
    before = facts({"src/p/__init__.py": "class Box:\n    size: Size\n    def open(self) -> Lid: ...\n"})
    after = facts({"src/p/__init__.py": "from p.box import Box\n__all__ = ['Box']\n",
                   "src/p/box.py": "class Box:\n    size: Size\n    def open(self) -> Lid: ...\n",
                   "src/p/util.py": "from p.box import Box\n"})  # imported, not re-exported: not part of p.util's port
    changes = port_changes(before, after)
    assert not [c for c in changes if c.unit == "p" and c.compatibility is not Compatibility.COMPATIBLE]
    assert not [c for c in changes if c.unit == "p.util"]


def test_numstat_parsing():
    assert parse_numstat(NumStat("3\t1\tsrc/a.py\n-\t-\timg.png\n")) == (
        FileChange(SourcePath("img.png"), LineNo(0), LineNo(0)), FileChange(SourcePath("src/a.py"), LineNo(3), LineNo(1)))


DESIGN = {"needs/n.md": NEED, "components/s.md": component(serves="n"),
          "components/s/a.md": component(serves="n", status="verified"), "components/s/b.md": component(serves="n"),
          "components/s/c.md": component(serves="n", uses="a")}
CODE = {"src/s/__init__.py": "", "src/s/a.py": "def f(x: X) -> Y: ...\n", "src/s/b.py": "def g() -> Z: ...\n",
        "src/s/c.py": "from s.a import f\n", "tests/test_a.py": "@realizes('s.a#AC1')\ndef test_f(): ...\n"}


def run_review(code_after, design_after=DESIGN, changed=None):
    before, after = (codec.load({DesignPath(k): v for k, v in d.items()}) for d in (DESIGN, design_after))
    fb, fa = facts(CODE), facts(code_after)
    inp = ReviewInput(Text("main"), before, after, fb, fa, check(Graph(before), fb), check(Graph(after), fa),
                      changed or tuple(FileChange(SourcePath(p), LineNo(5), LineNo(1)) for p in sorted(code_after)
                                       if code_after[p] != CODE.get(p)))
    return review(inp)


@realizes("arch.review.summary#AC1")
def test_layers_come_in_review_order_and_collapse():
    text = run_review({**CODE, "src/s/b.py": "import s.c\ndef g() -> Z: ...\n"}).to_markdown()
    titles = ["1. Intent", "2. Design", "3. Structure", "4. Contracts", "5. Evidence", "6. Code"]
    positions = [text.index(t) for t in titles]
    assert positions == sorted(positions) and text.count("<details") >= 6


@realizes("arch.review.summary#AC2", "arch.review.summary#AC3")
def test_files_are_ranked_by_documented_risk():
    r = run_review({**CODE, "src/s/a.py": "def f(x: X, y: Y) -> Y: ...\n",  # breaking change in a verified component
                    "src/s/b.py": "import s.c\ndef g() -> Z: ...\n",     # undeclared new dependency
                    "src/s/c.py": "from s.a import f\n# tidy\n"})          # nothing notable
    by_path = {f.path: f for f in r.files}
    assert by_path["src/s/a.py"].risk is Risk.HIGH and "breaking" in "; ".join(by_path["src/s/a.py"].reasons)
    assert by_path["src/s/b.py"].risk is Risk.HIGH and any("newly depends on s.c" in x for x in by_path["src/s/b.py"].reasons)
    assert by_path["src/s/b.py"].reasons[1] == "new blocking finding"  # the undeclared import (C001)
    assert by_path["src/s/c.py"].risk is Risk.LOW  # only "no linked evidence" (+1)
    quiet = run_review({**CODE, "src/s/a.py": "def f(x: X) -> Y:\n    return x\n"})
    assert quiet.files[0].risk is Risk.LOW and "verified, evidence passing" not in quiet.files[0].reasons  # no report yet


@realizes("arch.review.summary#AC4")
def test_summary_fits_a_pull_request_comment():
    many = tuple(FileChange(SourcePath(f"src/s/gen{i:04}.py"), LineNo(300), LineNo(0)) for i in range(3000))
    r = run_review(CODE, changed=many)
    assert len(r.to_markdown()) <= 65_000 and "more medium- or high-risk files" in r.to_markdown()


def test_cli_review_against_the_merge_base(tmp_path, capsys):
    for path, text in {**{f"design/{k}": v for k, v in DESIGN.items()}, **CODE}.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    git = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)  # noqa: E731
    git("init", "-q")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    (tmp_path / "src/s/a.py").write_text("def f(x: X, y: Y) -> Y: ...\n")
    (tmp_path / "src/s/new.py").write_text("def h() -> W: ...\n")
    assert main(["--project", str(tmp_path), "review", "HEAD"]) == 0
    out = capsys.readouterr().out
    assert "1 breaking port changes" in out and "| low | `src/s/new.py` | s |" in out  # new module of component s


DIFF = """diff --git a/src/s/a.py b/src/s/a.py
index 1..2 100644
--- a/src/s/a.py
+++ b/src/s/a.py
@@ -1,3 +1,4 @@ def f
 def f(x):
-    return x
+    y = x + 1
+    return y
 # end
diff --git a/src/s/old.py b/src/s/new.py
similarity index 92%
rename from src/s/old.py
rename to src/s/new.py
diff --git a/img.png b/img.png
new file mode 100644
Binary files /dev/null and b/img.png differ
"""


@realizes("arch.realize.history#AC3")
def test_unified_diffs_become_hunks_with_line_numbers():
    from arch.realize.facts import Content, DiffLineKind, FileShape
    from arch.realize.history import UnifiedDiff, parse_diff
    files = {f.path: f for f in parse_diff(UnifiedDiff(DIFF))}
    a = files["src/s/a.py"]
    assert a.shape is FileShape.MODIFIED and (a.added, a.removed) == (2, 1) and a.hunks[0].header == "def f"
    added = [l for l in a.hunks[0].lines if l.kind is DiffLineKind.ADDED]
    assert [(l.text, l.new_line) for l in added] == [("    y = x + 1", 2), ("    return y", 3)]
    assert files["src/s/new.py"].shape is FileShape.RENAMED and files["src/s/new.py"].old_path == "src/s/old.py"
    assert files["img.png"].content is Content.BINARY and files["img.png"].shape is FileShape.ADDED
