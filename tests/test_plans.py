"""planned-effects (DESIGN2 §4.1), on a small checkout whose decisions are made in pure code, and the command line's own
plans, which are how zigdag itself follows the rule."""

from pathlib import Path

from test_code import found, run

from zigdag import verifies
from zigdag.cli import _parser, main, plans
from zigdag.core.findings import Result
from zigdag.core.log import LOG_FILE

SETTINGS = '[settings]\nruleset = 1\n[adapters]\ndefault = "python"\n[adapters.python]\nsource = ["src"]\n'
PYPROJECT = '[project]\nname = "shop"\ndependencies = ["deal"]\n'
CUSTOMER = """
pay:
  job: Pay for an order
  performer: Shopper
  outcomes:
    wrong-charge: Minimize the likelihood that an order is charged the wrong amount
"""
FUNCTIONAL = """
frs:
  shop:
    statements:
      sell: The shop shall take payment for orders.
  shop.core:
    serves: [pay.wrong-charge]
    statements:
      plan: The core shall decide what each order is charged.
  shop.shell:
    serves: [pay.wrong-charge]
    statements:
      charge: The shell shall charge each order.
  shop.bank:
    serves: [pay.wrong-charge]
    statements:
      talk: The bank shall talk to the bank.
constraints:
  pure-core:
    on: shop.core
    serves: [pay.wrong-charge]
    check: effects
    with:
      allow: []
"""
CORE = '''"""What each order is charged: decided here, without effects."""
from dataclasses import dataclass
from typing import NewType

import deal

Card = NewType("Card", str)
Cents = NewType("Cents", int)


@dataclass(frozen=True)
class Order:
    """An order to pay for."""

    card: Card
    cents: Cents


@dataclass(frozen=True)
class Charge:
    """One charge to make."""

    card: Card
    cents: Cents


@dataclass(frozen=True)
class Plan:
    """What paying for an order does."""

    charges: tuple[Charge, ...]
    approve: bool
    note: str  # what to say when asking for approval


@deal.ensure(lambda order, result: result.charges == (Charge(order.card, order.cents),))
def plan_checkout(order: Order) -> Plan:
    """Charge the order once; ask for approval above a hundred."""
    charges = (Charge(order.card, order.cents),)
    return Plan(charges, order.cents > 10000, f"approve {len(charges)} charges")


def wire(card: Card, cents: Cents) -> bytes:
    """A charge, as the bank reads it."""
    return f"{card} {cents}".encode()
'''
BANK = '''"""The bank, reached over the network."""
import socket

from shop.core import Card, Cents, wire


def charge(card: Card, cents: Cents) -> None:
    """Charge a card."""
    socket.create_connection(("bank", 443)).sendall(wire(card, cents))


def status(card: Card) -> str:
    """What the bank says about a card."""
    return socket.create_connection(("bank", 443)).recv(64).decode()
'''
SHELL = '''"""Paying: carrying out what the core decided."""
import deal

from shop import bank
from shop.core import Order, Plan, plan_checkout


def carry_out(plan: Plan) -> None:
    """Does what the plan says, and nothing else."""
    for c in plan.charges:
        bank.charge(c.card, c.cents)
    if plan.approve:
        print(plan.note)


def checkout(order: Order) -> None:
    """Plans, then carries the plan out."""
    carry_out(plan_checkout(order))


def forward(order: Order) -> None:
    """Passes its own parameter on, which decides nothing."""
    bank.charge(order.card, order.cents)


@deal.has()
def label(order: Order) -> str:
    """Declared pure in its code, so its result is a plan value."""
    return f"order for {order.card}"


def announce(order: Order) -> None:
    print(label(order))


def discount(order: Order) -> None:
    """Decides, in code with effects."""
    if order.cents > 100:
        bank.charge(order.card, order.cents * 9 // 10)


def vip(order: Order) -> None:
    """Branches on its parameter, which no pure function decided."""
    if order.card:
        bank.charge(order.card, order.cents)


def echo(plan: Plan) -> None:
    """Passes what an effect returned on to another call."""
    print(bank.status(plan.charges[0].card))


def capped(plan: Plan) -> None:
    """Hides a decision in a library call."""
    bank.charge(plan.charges[0].card, max(plan.charges[0].cents, 0))
'''


def build(tmp_path: Path, design: bool = True) -> Path:
    files = {"zigdag.toml": SETTINGS, "pyproject.toml": PYPROJECT, "src/shop/__init__.py": '"""Shop."""\n',
             "src/shop/core.py": CORE, "src/shop/bank.py": BANK, "src/shop/shell.py": SHELL,
             **({"design/customer.yaml": CUSTOMER, "design/functional.yaml": FUNCTIONAL} if design else {})}
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    return tmp_path


def broken(tmp_path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f in run(build(tmp_path)).report.findings:
        if f.rule == "planned-effects":
            assert f.result is Result.BREAKS, f.say
            out.setdefault(f.about.rpartition(".")[2], []).append(f.say)
    return out


@verifies("zigdag.core.analysis.checks#planned", "zigdag.adapters.python#read")
def test_code_that_only_carries_out_what_pure_code_decided_holds(tmp_path):
    breaks = broken(tmp_path)
    for holds in ("carry_out", "checkout", "forward", "announce", "label", "plan_checkout", "charge", "status"):
        assert holds not in breaks, breaks.get(holds)


@verifies("zigdag.core.analysis.checks#planned")
def test_deciding_in_code_with_effects_breaks_and_says_what_to_move(tmp_path):
    breaks = broken(tmp_path)
    assert any("works out `order.cents > 100` in code with effects: work it out in a pure function" in s
               for s in breaks["discount"])
    assert any("works out `order.cents * 9 // 10`" in s for s in breaks["discount"])
    assert any("branches on `order.card`, which is not a plan value" in s for s in breaks["vip"])
    assert any("passes `bank.status(plan.charges[0].card)` to builtins.print" in s for s in breaks["echo"])
    assert any("passes `max(plan.charges[0].cents, 0)` to shop.bank.charge" in s for s in breaks["capped"])


@verifies("zigdag.core.init#record")
def test_init_lists_each_function_that_breaks_the_rule_as_debt(tmp_path):
    root = build(tmp_path, design=False)
    main(["--project", str(root), "init"])
    process = (root / "design/process.yaml").read_text()
    assert "planned-effects:" in process and "shop.shell.discount" in process and "shop.shell.checkout" not in process
    assert not found(run(root), "planned-effects")


@verifies("zigdag.core.analysis.checks#contracted")
def test_a_pure_function_an_interface_offers_states_a_contract(tmp_path):
    said = {f.about.rpartition(".")[2]: f.say for f in run(build(tmp_path)).report.findings
            if f.rule == "contracted-interfaces"}
    assert "plan_checkout" not in said  # it states what it promises
    assert "used outside shop.core" in said["wire"]  # the bank relies on it, and it promises nothing
    assert "called by shop.shell.announce, which has effects" in said["label"]
    assert not {"carry_out", "checkout", "charge"} & set(said)  # code with effects is not asked for contracts


@verifies("zigdag.cli.plans#decide")
def test_the_log_gets_its_union_merge_rule_once():
    first = plans.appended(None, None, "event")
    assert [w.path for w in first] == [LOG_FILE, plans.GIT_ATTRIBUTES]
    again = plans.appended("event\n", first[1].text, "next")
    assert [w.path for w in again] == [LOG_FILE] and again[0].text == "event\nnext\n"


@verifies("zigdag.cli.plans#decide")
def test_the_route_names_the_command_and_the_project(tmp_path):
    args, rest = _parser().parse_known_args(["--project", "sub", "show", "--data"])
    shown = plans.route(args, rest, tmp_path)
    assert shown.command is plans.Command.VIEW and shown.view == plans.DATA_VIEW and shown.root == tmp_path / "sub"
    args, rest = _parser().parse_known_args(["check", "--unknown"])
    assert plans.route(args, rest, tmp_path).rejected
    args, rest = _parser().parse_known_args(["critique", "--record", "answer.json"])
    assert plans.route(args, rest, tmp_path).command is plans.Command.REFUSED  # recording needs --by
