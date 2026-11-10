"""Step 2: the Python adapter, the DP tree, the code checks, evidence, the views and init, on a small project."""

from pathlib import Path

from zigdag import verifies
from zigdag.adapters.python import PythonFiles, read_python
from zigdag.cli import read_code, read_project
from zigdag.core import views
from zigdag.core.checks.run import ProjectFiles, analyse
from zigdag.core.code import SymbolKind
from zigdag.core.findings import Result
from zigdag.core.init import init
from zigdag.core.relate import Where, classify
from zigdag.core.resolve import Level

SETTINGS = '[settings]\nruleset = 1\n[adapters]\ndefault = "python"\n[adapters.python]\nsource = ["src"]\n'
PYPROJECT = '[project]\nname = "tiny"\ndependencies = ["ruamel.yaml>=0.18"]\n'
CUSTOMER = """
buy-things:
  job: Buy a product online
  performer: Shopper
  outcomes:
    lost-order: Minimize the likelihood that a placed order is lost
"""
FUNCTIONAL = """
frs:
  tiny:
    statements:
      sell: The tiny shall take orders for products.
  tiny.core:
    serves: [buy-things.lost-order]
    statements:
      price: The core shall price an order.
  tiny.core.model:
    statements:
      hold: The model shall hold an order and its lines.
  tiny.core.model.order:
    statements:
      lines: The order shall give every line a product.
  tiny.core.rules:
    statements:
      price: The rules shall price an order in cents.
  tiny.cli:
    serves: [buy-things.lost-order]
    statements:
      run: The cli shall print the price of an order.
constraints:
  pure-core:
    on: tiny.core
    serves: [buy-things.lost-order]
    check: effects
    with:
      allow: []
"""
SOURCES = {
    "src/tiny/__init__.py": '"""Tiny."""\n',
    "src/tiny/core/__init__.py": '"""The core."""\n',
    "src/tiny/core/model.py": '''"""Orders."""
from dataclasses import dataclass
from typing import NewType

OrderId = NewType("OrderId", str)  # an order's identity
Cents = NewType("Cents", int)  # an amount of money, in cents


@dataclass(frozen=True)
class Order:
    """An order a shopper placed."""

    id: OrderId
    total: Cents
''',
    "src/tiny/core/rules.py": '''"""Pricing."""
import deal

from tiny.core.model import Cents, Order


class PricingError(Exception):
    """An order that cannot be priced."""


@deal.raises(PricingError)
def price(order: Order) -> Cents:
    """The amount to charge for the order, in cents."""
    if order.total < 0:
        raise PricingError("negative")
    return order.total


def label(order: Order, currency: str) -> str:
    """The order's price, written for people."""
    return f"{price(order)} {currency}"


def checked(order: Order) -> bool:
    """Whether the order can be priced."""
    try:
        price(order)
    except PricingError:
        return False
    return True


@deal.has()
def leaky() -> None:
    """Claims to be pure."""
    print("oops")


def _secret() -> int:
    return 1
''',
    "src/tiny/cli.py": '''"""The command line."""
import subprocess
from pathlib import Path

from tiny.core.model import Cents, Order, OrderId
from tiny.core.rules import _secret, label, price


def main() -> None:
    """Print a price, and save it."""
    order = Order(OrderId("o1"), Cents(5))
    print(label(order, "USD"), _secret())
    Path("out.txt").write_text(str(price(order)))
    subprocess.run(["true"])
''',
}
TEST = '''from zigdag import verifies
from tiny.core.rules import price


@verifies("tiny.core.rules#price")
def test_price():
    pass


@verifies("tiny.core#nothing")
def test_broken_link():
    pass
'''
REPORT = '<testsuite><testcase classname="tests.test_tiny" name="test_price"/></testsuite>'


def build(tmp_path: Path, functional: str = FUNCTIONAL, extra: dict | None = None, report: bool = True) -> Path:
    files = {"zigdag.toml": SETTINGS, "pyproject.toml": PYPROJECT, "design/customer.yaml": CUSTOMER,
             "design/functional.yaml": functional, "tests/test_tiny.py": TEST, **SOURCES,
             **({".zigdag/pytest.xml": REPORT} if report else {}), **(extra or {})}
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    return tmp_path


def run(root: Path):
    files = read_project(root)
    return analyse(files, read_code(root))


def found(analysis, rule: str, result: Result = Result.BREAKS) -> list[str]:
    return [f"{f.about}: {f.say}" for f in analysis.report.findings if f.rule == rule and f.result is result]


@verifies("zigdag.adapters#read", "zigdag.adapters.python#read", "zigdag.core.code#hold")
def test_the_adapter_reads_units_symbols_effects_raises_and_tests(tmp_path):
    a = run(build(tmp_path))
    code = a.code
    assert {"tiny", "tiny.core", "tiny.core.model", "tiny.core.rules", "tiny.cli"} <= set(code.units)
    assert code.symbols["tiny.core.model.OrderId"].kind is SymbolKind.NAMED_TYPE
    assert not read_python(PythonFiles({}, ("src",), (), {}, None, {})).units  # no source, nothing read
    assert not code.symbols["tiny.core.rules._secret"].public
    effects = {(str(e.at), e.effect) for e in code.effects}
    assert {("tiny.cli.main", "stdout"), ("tiny.cli.main", "write"), ("tiny.cli.main", "syscall"),
            ("tiny.core.rules.leaky", "stdout")} <= effects
    raised = {(str(r.at), r.caught) for r in code.raises}
    assert ("tiny.core.rules.price", False) in raised
    assert code.symbols["tiny.core.rules.leaky"].declared_effects == ()
    assert {t.id for t in code.tests} == {"tests.test_tiny::test_price", "tests.test_tiny::test_broken_link"}
    assert code.results["tests.test_tiny::test_price"].value == "passed"


@verifies("zigdag.core.analysis.resolve#own")
def test_the_tree_maps_names_to_code_by_default_and_works_out_levels(tmp_path):
    a = run(build(tmp_path))
    dps = a.tree.dps
    assert dps["tiny"].level is Level.SYSTEM and dps["tiny.core.rules"].level is Level.COMPONENT
    assert dps["tiny.core.model.order"].level is Level.STRUCTURE
    assert a.tree.owner("tiny.core.model.Order.total") == "tiny.core.model.order"
    assert a.tree.owner("tiny.core.model.OrderId") == "tiny.core.model"


@verifies("zigdag.core.analysis#check", "zigdag.core.analysis.relate#reach")
def test_effects_reached_through_calls_break_the_rule_that_covers_them(tmp_path):
    a = run(build(tmp_path))
    assert any("leaky" in s and "writing to standard output" in s for s in found(a, "pure-core"))
    assert any("declares its effects" in s for s in found(a, "declared-effects"))
    assert classify(a.code, a.tree, "subprocess.run").where is Where.STANDARD
    assert classify(a.code, a.tree, "tiny.core.rules.price").owner == "tiny.core.rules"


def test_an_except_entry_skips_the_code_it_names(tmp_path):
    functional = FUNCTIONAL.replace("      allow: []", "      allow: []\n    except:\n      - rules.leaky")
    a = run(build(tmp_path, functional))
    assert not found(a, "pure-core")
    a = run(build(tmp_path, functional.replace("rules.leaky", "rules.nowhere")))
    assert any("names no code" in s for s in found(a, "except"))


@verifies("zigdag.core.analysis.checks#report")
def test_encapsulation_edge_types_errors_and_descriptions(tmp_path):
    a = run(build(tmp_path))
    assert any("_secret" in s for s in found(a, "encapsulation"))
    edge = " | ".join(found(a, "edge-types"))
    assert "label" in edge and "str is not defined by the project" in edge
    assert "tiny.core.rules.price:" not in edge and "checked:" not in edge  # NewTypes, structures and bool returns pass
    assert not found(a, "declared-errors")  # price declares PricingError
    assert any("Order" in s or "label" in s for s in found(a, "described-names")) is False


def test_undeclared_libraries_and_cycles_break(tmp_path):
    extra = {"src/tiny/core/model.py": SOURCES["src/tiny/core/model.py"] + "import requests\nimport tiny.core.rules\n"}
    a = run(build(tmp_path, extra=extra))
    assert any("requests is imported" in s for s in found(a, "declared-libraries"))
    assert any("cycle" in s for s in found(a, "no-cycles"))


def test_evidence_links_results_and_kinds(tmp_path):
    a = run(build(tmp_path))
    assert any("tiny.core#nothing" in s for s in found(a, "evidence.links"))
    todo = found(a, "evidence", Result.TODO)
    assert any("no test verifies tiny.cli#run" in s for s in todo)
    assert not any("tiny.core.rules#price:" in s for s in todo)
    failed = run(build(tmp_path, report=True, extra={".zigdag/pytest.xml": REPORT.replace(
        'name="test_price"/>', 'name="test_price"><failure/></testcase>')}))
    assert any("failed" in s for s in found(failed, "evidence"))


@verifies("zigdag.core.analysis.resolve#own")
def test_coverage_breaks_for_code_no_design_parameter_owns(tmp_path):
    a = run(build(tmp_path, extra={"src/other/__init__.py": "x = 1\n"}))
    assert any("other belongs to no design parameter" in s for s in found(a, "coverage"))


@verifies("zigdag.core.views#show")
def test_the_views_show_the_zigzag_the_context_and_what_to_do_next(tmp_path):
    a = run(build(tmp_path))
    shown = views.show(a, "tiny")
    assert "design matrix" in shown and "cli" in shown and "level: system" in shown
    ctx = views.context(a, "src/tiny/cli.py")
    assert "Shopper wants to: Buy a product online" in ctx and "it uses:" in ctx and "label(" in ctx
    assert views.next_steps(a).splitlines()[1].strip().startswith("tiny")


@verifies("zigdag.core.init#record")
def test_init_records_existing_code_so_the_first_check_holds(tmp_path, capsys):
    from zigdag.cli import main

    root = build(tmp_path)
    for name in ("design/functional.yaml", "design/customer.yaml", "zigdag.toml", "tests/test_tiny.py"):
        (root / name).unlink()
    assert main(["--project", str(root), "init"]) == 0
    assert "need a decision" in capsys.readouterr().out  # leaky claims to be pure and is not: a person decides
    a = run(root)
    assert [f.rule for f in a.report.of_result(Result.BREAKS)] == ["declared-effects"]
    assert a.report.of_result(Result.TODO)
    assert main(["--project", str(root), "init"]) == 2  # it never overwrites a record without --force
    written, _ = init(ProjectFiles(None, {}, None), a.code)
    assert "tiny.core.rules: {}" in written["design/functional.yaml"]


LONG_LINES = 100  # longer than every file of the tiny project


@verifies("zigdag.core.analysis.checks#oversized")
def test_a_file_longer_than_the_rule_allows_breaks_and_one_within_it_holds(tmp_path):
    long_file = '"""Notes."""\n' + "".join(f"N{i} = {i}\n" for i in range(LONG_LINES))
    limit = "max-lines:\n  with:\n    file: {}\n"
    over = run(build(tmp_path, extra={"src/tiny/core/notes.py": long_file,
                                      "design/process.yaml": limit.format(LONG_LINES)}))
    assert found(over, "max-lines") == [f"tiny.core.notes: the file of tiny.core.notes is {LONG_LINES + 1} lines; "
                                        f"at most {LONG_LINES}"]
    (tmp_path / "design/process.yaml").write_text(limit.format(LONG_LINES + 1))
    assert found(run(tmp_path), "max-lines") == []


@verifies("zigdag.core.views#next")
def test_next_puts_things_of_one_kind_in_one_line_and_shows_only_the_first_kinds(tmp_path):
    untested = "".join(f"\n  tiny.core.rules.r{i}:\n    statements:\n      hold: The r{i} shall hold a rule.\n"
                       for i in range(3))
    lines = views.next_steps(run(build(tmp_path, functional=FUNCTIONAL.replace("\nconstraints:", untested
                                                                                + "\nconstraints:")))).splitlines()
    assert "  tiny.core.rules.r0 and 2 more like it: no code yet: write the module, package or class this DP is" in lines
    assert sum("no test verifies" in line for line in lines) == 1 and not any("r1" in line for line in lines)
    assert len(lines) <= views.NEXT_SHOWN + 2


@verifies("zigdag.core.analysis.checks#undesigned")
def test_a_module_the_design_does_not_name_breaks_until_the_design_names_it(tmp_path):
    root = build(tmp_path, extra={"src/tiny/core/surprise.py": '"""Nobody designed this."""\nX = 1\n'})
    assert [s.split(":")[0] for s in found(run(root), "designed-modules")] == ["tiny.core.surprise"]
    (root / "design/physical.yaml").write_text("tiny.core: [core, core.surprise]\n")
    assert found(run(root), "designed-modules") == []


@verifies("zigdag.core.init#default-setup")
def test_a_default_setup_writes_the_settings_a_starter_record_and_every_tunable_rule(tmp_path, capsys):
    from zigdag.cli import main
    from zigdag.core.init import tunable

    empty = tmp_path / "shop-site"
    empty.mkdir()
    assert main(["--project", str(empty), "init", "--default"]) == 0
    written = "".join((empty / name).read_text() for name in ("design/functional.yaml", "design/process.yaml"))
    assert "shop_site: {}" in written and all(f"\n{rule}:" in written.replace("  ", "") for rule in tunable())
    assert "file: 1000" in written and "# The shop site shall keep each function within 200 lines" in written
    assert (empty / "zigdag.toml").is_file() and (empty / "design/customer.yaml").read_text().startswith("#")
    assert not run(empty).report.breaks  # nothing is broken before any code is written
    assert main(["--project", str(empty), "init", "--default"]) == 2  # it never replaces a record

    coded = build(tmp_path / "coded")
    for name in ("design/functional.yaml", "design/customer.yaml", "zigdag.toml", "tests/test_tiny.py"):
        (coded / name).unlink()
    assert main(["--project", str(coded), "init", "--default"]) == 0
    assert "tiny.core.rules: {}" in (coded / "design/functional.yaml").read_text()  # the code is recorded as init does
    assert "max-lines:" in (coded / "design/process.yaml").read_text()
    assert [f.rule for f in run(coded).report.of_result(Result.BREAKS)] == ["declared-effects"]  # as plain init leaves


@verifies("zigdag.core.views#rules")
def test_the_list_of_rules_in_the_docs_is_what_zigdag_checks_prints():
    from zigdag.core.kinds.registry import BUILT_IN_KINDS
    from zigdag.core.settings import Settings

    listed = views.rules(Settings())
    assert all(f"| `{kind}` |" in listed for kind in BUILT_IN_KINDS)  # no rule is left out
    assert listed == Path("docs/rules.md").read_text(), "the rules changed: write the list again with zigdag checks"
