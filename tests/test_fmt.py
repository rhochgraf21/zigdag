import json
from pathlib import Path

from conftest import EXAMPLES
from hypothesis import given, settings
from hypothesis import strategies as st

from zigdag.core.record.fmt import content, format_text
from zigdag import verifies

FILES = sorted(EXAMPLES.glob("*/design/*.yaml")) + sorted(Path("design").glob("*.yaml"))


def fmt(text, name="design/functional.yaml"):
    out, problems = format_text(name, text)
    assert out is not None, problems
    return out


def test_every_example_formats_stably_and_keeps_what_it_says():
    for path in FILES:
        name, text = f"design/{path.name}", path.read_text()
        once = fmt(text, name)
        assert fmt(once, name) == once, path
        assert content(name, once) == content(name, text), path


def test_fields_go_in_a_fixed_order_and_frs_in_tree_order():
    text = """constraints:
  pure:
    with:
      allow: []
    check: effects
    serves: [a.b]
    on: app
frs:
  app.core.emit:
    statements: {x: y}
  app.cli:
    statements: {x: y}
  app:
    statements: {x: y}
  app.core:
    statements: {x: y}
"""
    out = fmt(text)
    assert out.index("frs:") < out.index("constraints:")
    order = [line.strip() for line in out.splitlines() if line.startswith("  app")]
    assert order == ["app:", "app.cli:", "app.core:", "app.core.emit:"]
    pure = out[out.index("pure:"):]
    assert [k for k in ("on:", "serves:", "check:", "with:") if k in pure] == ["on:", "serves:", "check:", "with:"]
    assert pure.index("on:") < pure.index("serves:") < pure.index("check:") < pure.index("with:")


@verifies("zigdag.core.record#keep-all")
def test_comments_stay_with_what_they_were_written_with():
    text = """# header
frs:
  app:  # beside app
    # above statements
    statements:
      x: The app shall run.  # beside x
constraints:
  pure:
    except:
      - a.b  # why
      - c
# at the end
"""
    out = fmt(text)
    assert "# header\nfrs:" in out
    assert "app:  # beside app" in out
    assert "# above statements\n    statements:" in out
    assert "x: The app shall run.  # beside x" in out
    assert "- a.b  # why\n      - c" in out
    assert out.rstrip().endswith("# at the end")


def test_lists_are_inline_unless_they_carry_comments_or_run_long():
    out = fmt("x:\n  - a\n  - b\ny: [c, d]\nz:\n  - e  # why\n")
    assert "x: [a, b]" in out and "y: [c, d]" in out and "z:\n  - e  # why" in out
    long = fmt("x: [" + ", ".join(f"name{i:03}" for i in range(20)) + "]\n")
    assert "x:\n  - name000" in long


def test_a_comment_beside_an_empty_value_stays_on_its_line():
    text = "a:\n  b:  # one\n  c:\nd:  # two\n"
    once = fmt(text)
    assert fmt(once) == once and "b:  # one" in once and "d:  # two" in once


@verifies("zigdag.core.record#keep-all")
def test_a_comment_stays_on_its_line_after_a_value_that_holds_a_unicode_line_separator():
    # YAML does not end a line at these characters, and Python's splitlines does: comments must be placed as YAML counts
    for separator in ("\u2028", "\u2029"):
        text = f'a: "{separator}"\nb:  # beside b\n# above c\nc: x\n'
        once = fmt(text)
        assert "b:  # beside b\n# above c\nc: x\n" in once and fmt(once) == once


def test_values_that_need_quotes_get_them():
    out = fmt('a: "x: y"\nb: "#no"\nc: "- dash"\nd: plain text\ne: ""\nf: [ "a,b" ]\n')
    assert 'a: "x: y"' in out and 'b: "#no"' in out and 'c: "- dash"' in out
    assert "d: plain text" in out and "e:\n" in out and 'f: ["a,b"]' in out


_keys = st.from_regex(r"[a-z][a-z0-9-]{0,8}", fullmatch=True)
_YAML_UNSAFE = ("Cs", "Cc", "Cn", "Co", "Cf")  # characters YAML does not allow in a file, or that read ambiguously
_texts = st.text(st.characters(codec="utf-8", exclude_categories=_YAML_UNSAFE), max_size=30)
_comments = st.one_of(st.none(), st.text(st.characters(codec="utf-8", exclude_categories=(*_YAML_UNSAFE, "Zl", "Zp")),
                                         max_size=20))
_trees = st.recursive(
    _texts,
    lambda inner: st.one_of(st.lists(_texts, max_size=3), st.dictionaries(_keys, inner, min_size=1, max_size=3)),
    max_leaves=8,
)


def _render(value, indent, comments, out):
    pad = " " * indent
    for key, v in value.items():
        above, beside = next(comments), next(comments)
        if above is not None:
            out.append(f"{pad}# {above}".rstrip())
        tail = f"  # {beside}" if beside else ""
        if isinstance(v, dict):
            out.append(f"{pad}{key}:{tail}")
            _render(v, indent + 2, comments, out)
        elif isinstance(v, list):
            out.append(f"{pad}{key}: [{', '.join(json.dumps(i, ensure_ascii=False) for i in v)}]{tail}")
        else:
            out.append(f"{pad}{key}: {json.dumps(v, ensure_ascii=False)}{tail}")


@verifies("zigdag.core.record#keep-all", "zigdag.core.record#stable")
@settings(max_examples=80, deadline=None)
@given(st.dictionaries(_keys, _trees, min_size=1, max_size=4), st.lists(_comments, min_size=200, max_size=200))
def test_formatting_any_file_is_stable_and_lossless(tree, comment_list):
    lines: list[str] = []
    _render(tree, 0, iter(comment_list * 5), lines)
    text = "\n".join(lines) + "\n"
    for name in ("design/functional.yaml", "design/process.yaml", "design/physical.yaml", "design/customer.yaml"):
        once = fmt(text, name)
        assert fmt(once, name) == once
        assert content(name, once) == content(name, text)
