"""Step 5: the data model. Structures, what they contain and refer to, who changes them, where protected values may
become text, the states and features statements name, and the view of it all."""

import dataclasses
from pathlib import Path

from test_code import found, run

from zigdag import verifies
from zigdag.core import views
from zigdag.core.checks.run import analyse
from zigdag.core.code import Qualified, Symbol, SymbolKind, Unit, UnitKind
from zigdag.core.data import Cardinality, RelationKind
from zigdag.core.findings import Result, Span
from zigdag.core.names import CodePath, TYPESCRIPT
from zigdag.cli import read_project

SETTINGS = '[settings]\nruleset = 1\n[adapters]\ndefault = "python"\n[adapters.python]\nsource = ["src"]\n'
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
      paid: While the order is paid, the orders shall keep a receipt for the order.
  shop.orders.order:
    statements:
      lines: The order shall give every line a product.
  shop.orders.line:
    statements:
      hold: The line shall hold a product and a quantity.
  shop.billing:
    serves: [buy.lost-order]
    statements:
      ship: The billing shall ship each paid order.
      gift: Where the order's gift is enabled, the billing shall wrap the order.
constraints:
  contact-stays-private:
    on: shop
    serves: [buy.lost-order]
    check: data-flow
    with:
      data: [orders.Email]
      never-reaches: [stdout, stderr]
"""
ORDERS = '''"""Orders."""
import enum
from dataclasses import dataclass, field
from typing import NewType

OrderId = NewType("OrderId", str)  # an order's identity
CustomerId = NewType("CustomerId", str)  # a customer's identity
Email = NewType("Email", str)  # an email address: personal data


class Status(enum.Enum):
    """Where an order is in its life."""

    OPEN = "open"
    PAID = "paid"
    SHIPPED = "shipped"


@dataclass
class Line:
    """One product on an order."""

    product: str
    quantity: int


@dataclass
class Customer:
    """Someone who buys."""

    id: CustomerId
    email: Email


@dataclass
class Order:
    """An order a shopper placed."""

    id: OrderId
    status: Status
    customer: CustomerId
    contact: Email
    gift: bool
    lines: list[Line] = field(default_factory=list)

    def pay(self) -> None:
        """Mark the order paid."""
        self.status = Status.PAID


def place(customer: CustomerId, contact: Email) -> Order:
    """A new open order."""
    return Order(OrderId("o1"), Status.OPEN, customer, contact, False)


def receipt(order: Order) -> str:
    """The text of a receipt."""
    return f"order {order.id} for {order.contact}"
'''
BILLING = '''"""Billing."""
from shop.orders import Line, Order, Status


def ship(order: Order) -> None:
    """Ship an order."""
    order.status = Status.SHIPPED
    order.lines.append(Line("box", 1))


def notify(order: Order) -> None:
    """Tell the shopper."""
    print(order.contact)
    print(f"mail {order.contact}")
    print(order.contact.lower())


def label(order: Order) -> str:
    """A shipping label."""
    return str(order.id)


def shout(message) -> None:
    """Say something out loud."""
    print(message)
'''


def build(tmp_path: Path, functional: str = FUNCTIONAL) -> Path:
    files = {"zigdag.toml": SETTINGS, "design/customer.yaml": CUSTOMER, "design/functional.yaml": functional,
             "src/shop/__init__.py": '"""Shop."""\n', "src/shop/orders.py": ORDERS, "src/shop/billing.py": BILLING}
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    return tmp_path


@verifies("zigdag.adapters.python#read")
def test_the_adapter_reads_keys_enumerations_and_literals(tmp_path):
    code = run(build(tmp_path)).code
    order = code.symbols["shop.orders.Order"]
    assert [f.name for f in order.fields if f.key] == ["id"]
    assert code.symbols["shop.orders.Status"].members == ("OPEN", "PAID", "SHIPPED")
    assert order.field("gift").type.kind.value == "bool"


@verifies("zigdag.core.analysis.data#work-out")
def test_the_data_model_finds_what_structures_contain_and_refer_to(tmp_path):
    data = run(build(tmp_path)).data
    assert set(data.structures) == {"shop.orders.order", "shop.orders.line"}
    assert data.structures["shop.orders.order"].owner == "shop.orders"
    relations = {(r.field.name, r.kind, r.target, r.cardinality) for r in data.relations}
    assert ("lines", RelationKind.CONTAINS, "shop.orders.line", Cardinality.MANY) in relations
    assert ("customer", RelationKind.REFERS_TO, None, Cardinality.ONE) in relations  # Customer is not recorded
    kinds = {(a.dp, a.structure, a.kind.value) for a in data.accesses}
    assert ("shop.orders", "shop.orders.order", "creates") in kinds
    assert ("shop.billing", "shop.orders.order", "updates") in kinds


@verifies("zigdag.core.analysis.checks#data")
def test_only_the_owner_changes_a_structure_and_references_resolve(tmp_path):
    a = run(build(tmp_path))
    changes = found(a, "data-ownership", Result.QUESTION)
    assert any("ship may change Order.status;" in s for s in changes)
    assert any("Order.lines in place" in s for s in changes)
    assert not any("pay" in s for s in changes)  # the owner's own operation
    assert any("refers to a Customer" in s for s in found(a, "references-resolve"))


@verifies("zigdag.core.analysis.checks#data")
def test_protected_values_stay_text_free_outside_their_component(tmp_path):
    a = run(build(tmp_path))
    flows = found(a, "contact-stays-private")
    assert any("notify passes an Email straight to print" in s for s in flows)
    assert any("notify makes an Email into text (an f-string)" in s for s in flows)
    assert any("reads the text out of an Email (.lower)" in s for s in flows)
    assert not any("receipt" in s or "label" in s for s in flows)  # the owner releases; an order id is no email
    assert any("shout gives 1 values" in s for s in found(a, "contact-stays-private", Result.QUESTION))


@verifies("zigdag.core.analysis.checks#states")
def test_states_and_features_must_exist_in_the_data(tmp_path):
    a = run(build(tmp_path))
    assert not found(a, "ears.state") and not found(a, "ears.feature")
    wrong = FUNCTIONAL.replace("order is paid", "order is refunded").replace("order's gift", "order's wrapped")
    a = run(build(tmp_path, wrong))
    assert any('"refunded", which Order.status cannot be: it is one of open, paid, shipped' in s
               for s in found(a, "ears.state"))
    assert any('"wrapped", which is no field' in s for s in found(a, "ears.feature"))


@verifies("zigdag.core.analysis.checks#data")
def test_representations_of_one_structure_must_agree(tmp_path):
    root = build(tmp_path)
    (root / "design/physical.yaml").write_text("shop.orders.line: [python:Line, typescript:web.types.Line]\n")
    files = read_project(root)
    code = run(root).code
    ts = Symbol(CodePath("web.types"), "Line", SymbolKind.CLASS, True, Span("web/types.ts", 1, 1), 3, "A line.",
                fields=(dataclasses.replace(code.symbols["shop.orders.Line"].fields[0], name="product"),))
    unit = Unit(CodePath("web.types"), TYPESCRIPT, UnitKind.MODULE, True, Span("web/types.ts", 1, 1), 3)
    code = dataclasses.replace(code, units={**code.units, unit.path: unit},
                               symbols={**code.symbols, Qualified("web.types.Line"): ts})
    a = analyse(files, code)
    assert any("quantity is in python but not in typescript" in s for s in found(a, "representations-agree"))


@verifies("zigdag.core.views#data")
def test_the_data_view_shows_structures_relations_and_who_touches_what(tmp_path):
    shown = views.data(run(build(tmp_path)), "shop")
    assert "contains shop.orders.line: many, through lines" in shown
    assert "refers-to shop.orders.Customer (not recorded): one, through customer" in shown
    row = next(line for line in shown.splitlines() if line.strip().startswith("shop.billing"))
    assert "RU" in row
