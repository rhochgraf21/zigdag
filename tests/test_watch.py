"""Step 4: zigdag test. The project's own tests run with the watcher, and what it saw joins the checks: effects,
changes, values and errors crossing boundaries, protected text written out, calls made again, contracts run on
generated inputs, and evidence that is out of date."""

import json
import sys
from pathlib import Path

from test_code import found, run

from zigdag import verifies
from zigdag.cli import main
from zigdag.core.findings import Result

SETTINGS = f"""[settings]
ruleset = 1
test_command = "{sys.executable} -m pytest -q -p no:cacheprovider"
[adapters]
default = "python"
[adapters.python]
source = ["src"]
"""
PYPROJECT = '[project]\nname = "shop"\ndependencies = ["deal"]\n[tool.pytest.ini_options]\npythonpath = ["src"]\n'
CUSTOMER = """
buy:
  job: Buy a product online
  performer: Shopper
  outcomes:
    lost-order: Minimize the likelihood that a placed order is lost
"""
FUNCTIONAL = """
frs:
  shop:
    statements:
      sell: The shop shall take orders for products.
  shop.orders:
    serves: [buy.lost-order]
    statements:
      keep: The orders shall keep each placed order.
  shop.orders.order:
    statements:
      lines: The order shall give every line a product.
  shop.billing:
    serves: [buy.lost-order]
    statements:
      ship: The billing shall ship each paid order.
constraints:
  pure-orders:
    on: shop.orders
    serves: [buy.lost-order]
    check: effects
    with:
      allow: []
  contact-stays-private:
    on: shop
    serves: [buy.lost-order]
    check: data-flow
    with:
      data: [orders.Email]
      never-reaches: [stdout]
"""
ORDERS = '''"""Orders."""
import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import NewType

import deal

OrderId = NewType("OrderId", str)  # an order's identity
Email = NewType("Email", str)  # an email address: personal data
_issued: list[str] = []  # the numbers handed out so far


class Status(enum.Enum):
    """Where an order is in its life."""

    OPEN = "open"
    SHIPPED = "shipped"


@dataclass
class Order:
    """An order a shopper placed."""

    id: OrderId
    status: Status
    contact: Email
    lines: list[str] = field(default_factory=list)


_ORDERS: dict[str, Order] = {}


def number(prefix: OrderId) -> OrderId:
    """A new order number."""
    _issued.append(prefix)
    return OrderId(prefix + str(len(_issued)))


def find(order_id: OrderId) -> Order:
    """The order with this id."""
    return _ORDERS[order_id]


def receipt(order: Order) -> OrderId:
    """The number of an order's receipt."""
    return OrderId("r-1")


def pad(text: OrderId, width) -> OrderId:
    """The text, padded to a width."""
    return OrderId(text.ljust(width))


def keep(order: Order, folder) -> None:
    """Keep a copy of the order in a folder."""
    getattr(Path(folder) / "order.txt", "write_" + "text")(order.status.value)


@deal.post(lambda result: result > 0)
def half(quantity: int) -> int:
    """Half the quantity, rounded down."""
    return quantity // 2
'''
BILLING = '''"""Billing."""
from shop import orders
from shop.orders import Order, Status


def ship(order: Order) -> None:
    """Ship an order."""
    order.status = Status.SHIPPED
    order.lines.append("box")


def notify(order: Order) -> None:
    """Tell the shopper."""
    print(order.contact)


def relabel(order: Order) -> orders.OrderId:
    """A new receipt for the order."""
    return orders.receipt(order.id)


def lookup(order_id: orders.OrderId) -> Order:
    """Find an order."""
    return orders.find(order_id)


def label(order: Order) -> orders.OrderId:
    """A shipping label."""
    return orders.pad(order.id, 12)
'''
TESTS = '''import pytest

from zigdag import verifies
from shop import billing, orders
from shop.orders import Email, Order, OrderId, Status


def order() -> Order:
    return Order(OrderId("o1"), Status.OPEN, Email("alice@example.com"))


@verifies("shop.billing#ship")
def test_ship():
    shipped = order()
    billing.ship(shipped)
    assert shipped.status is Status.SHIPPED


@verifies("shop.orders#keep")
def test_notify():
    billing.notify(order())


def test_relabel_and_label():
    billing.relabel(order())
    billing.label(order())


def test_lookup():
    with pytest.raises(KeyError):
        billing.lookup(OrderId("nope"))


def test_numbers_and_keep(tmp_path):
    assert orders.number(OrderId("n")) == "n1"
    orders.keep(order(), tmp_path)
'''


def build(tmp_path: Path) -> Path:
    files = {"zigdag.toml": SETTINGS, "pyproject.toml": PYPROJECT, "design/customer.yaml": CUSTOMER,
             "design/functional.yaml": FUNCTIONAL, "src/shop/__init__.py": '"""Shop."""\n',
             "src/shop/orders.py": ORDERS, "src/shop/billing.py": BILLING, "tests/test_shop.py": TESTS}
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    return tmp_path


def watched(tmp_path: Path):
    root = build(tmp_path)
    main(["--project", str(root), "test"])
    return root, run(root)


@verifies("zigdag.watchers#record", "zigdag.watchers.python#watch", "zigdag.cli#test")
def test_zigdag_test_sees_what_reading_the_code_cannot(tmp_path):
    root, a = watched(tmp_path)
    assert a.code.observed is not None and (root / ".zigdag/pytest.xml").is_file()
    pure = " | ".join(found(a, "pure-orders"))
    assert "keep has an effect pure-orders does not allow: writing files (through open, seen while " \
           "tests.test_shop::test_numbers_and_keep ran)" in pure
    assert "number may have no effects, yet the call from tests.test_shop::test_numbers_and_keep gave a different " \
           "result the second time" in pure
    changes = found(a, "data-ownership")
    assert any("ship changed Order.status while tests.test_shop::test_ship ran" in s for s in changes)
    assert any("ship changed Order.lines in place while" in s for s in changes)
    errors = " | ".join(found(a, "declared-errors"))
    assert "a KeyError left shop.orders.find for another design parameter" in errors
    crossings = " | ".join(found(a, "edge-types"))
    assert "receipt was given a str for order, which its annotation, Order, does not allow" in crossings
    assert "pad was given an int for width, and no annotation lets through an int" in crossings
    assert any("the text of an Email was written to standard output while tests.test_shop::test_notify ran" in s
               for s in found(a, "contact-stays-private"))
    assert any("half breaks its own contract on generated inputs" in s for s in found(a, "contracts"))


@verifies("zigdag.core.analysis.checks#evidence-runs", "zigdag.core.analysis.checks#evidence-current")
def test_evidence_must_run_the_code_it_verifies_and_be_current(tmp_path):
    root, a = watched(tmp_path)
    wrong = found(a, "evidence")
    assert any("test_notify ran no code in shop.orders when it last ran" in s for s in wrong)
    assert not any("test_ship" in s for s in wrong)
    billing = root / "src/shop/billing.py"
    billing.write_text(billing.read_text() + "\n")
    a = run(root)
    todo = found(a, "evidence", Result.TODO)
    assert any("test_ship passed against code that has changed since" in s for s in todo)
    assert any("are about code that has changed since" in s for s in found(a, "observations", Result.TODO))
    assert not any("ship changed Order.status" in s for s in found(a, "data-ownership"))


@verifies("zigdag.core.vocabulary.codec#round-trip", "zigdag.core.analysis.watch#plan")
def test_the_recording_is_plain_json_with_every_file_digest(tmp_path):
    root, _ = watched(tmp_path)
    recording = json.loads((root / ".zigdag/observed.json").read_text())
    assert {"src/shop/orders.py", "tests/test_shop.py"} <= set(recording["files"])
    assert {r["test"] for r in recording["runs"]} >= {"tests.test_shop::test_ship", "tests.test_shop::test_lookup"}


@verifies("zigdag.watchers.python#same-seed")
def test_generated_inputs_and_calls_made_again_give_the_same_results_every_run(tmp_path):
    first, _ = watched(tmp_path / "first")
    second, _ = watched(tmp_path / "second")
    seen = [json.loads((root / ".zigdag/observed.json").read_text()) for root in (first, second)]
    assert seen[0]["cases"] == seen[1]["cases"] and seen[0]["replays"] == seen[1]["replays"]
    assert seen[0]["cases"][0]["outcome"] == "failed"
