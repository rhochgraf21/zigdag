"""Building parts at the same time (DESIGN2 §4.8): what a change asks of each part, what the branch of one part is
held to, and what ready says on such a branch."""

import subprocess
from dataclasses import replace
from pathlib import Path

from zigdag import verifies
from zigdag.cli import files, main, plans
from zigdag.cli.plans import Outcome, Presence, WatchedRun
from zigdag.core.checks.part_rules import SETTLED_FIRST, STAY_IN_PART, PartBranch, check_part, relied_on
from zigdag.core.checks.run import Analysis, analyse
from zigdag.core import code as model
from zigdag.core.code import Observations, Run
from zigdag.core.names import branch_of, part_built_on
from zigdag.core.work import asked, waiting

SETTINGS = '[settings]\nruleset = 1\n[adapters]\ndefault = "python"\n[adapters.python]\nsource = ["src"]\n'
CUSTOMER = """keep-shop:
  job: Sell products online
  performer: Shopkeeper
  outcomes:
    wrong-total: Minimize the likelihood that a shopper is shown a wrong total
"""
FUNCTIONAL = """frs:
  shop:
    statements:
      sell: The shop shall sell products.

  shop.pricing:
    serves: [keep-shop.wrong-total]
    statements:
      price: The pricing shall give the price of a product in cents.

  shop.checkout:
    serves: [keep-shop.wrong-total]
    statements:
      total: The checkout shall give the total of a basket in cents.

constraints:
  edge-types:
    off: true  # the shop passes plain text and numbers between its parts, to keep the example small
"""
PROCESS = """planned-effects:
  off: true  # the shop's functions work their answers out in place, to keep the example small
"""
PRICING = '"""Prices."""\n\n\ndef price(product: str) -> int:\n    """A product\'s price, in cents."""\n    return 450\n'
CHECKOUT = ('"""The checkout."""\n\nfrom shop.pricing import price\n\n\ndef total(basket: list[str]) -> int:\n'
            '    """What a basket costs, in cents."""\n    return sum(price(product) for product in basket)\n')
TESTS = ('from zigdag import verifies\nfrom shop.checkout import total\nfrom shop.pricing import price\n\n\n'
         '@verifies("shop.pricing#price")\ndef test_tea_costs_four_fifty():\n    assert price("tea") == 450\n\n\n'
         '@verifies("shop.checkout#total")\ndef test_two_teas_cost_nine_hundred():\n'
         '    assert total(["tea", "tea"]) == 900\n')
SHOP = {"zigdag.toml": SETTINGS, "pyproject.toml": '[project]\nname = "shop"\ndependencies = []\n',
        ".gitignore": ".zigdag/\n", "README.md": "# shop\n", "design/customer.yaml": CUSTOMER,
        "design/functional.yaml": FUNCTIONAL, "design/process.yaml": PROCESS, "src/shop/__init__.py": '"""A shop."""\n',
        "src/shop/pricing.py": PRICING, "src/shop/checkout.py": CHECKOUT, "tests/test_shop.py": TESTS}
PRICING_PART, CHECKOUT_PART = "shop.pricing", "shop.checkout"
DISCOUNTED = "The pricing shall give the price of a product in cents after the discount of the product."
WITH_DISCOUNTS = FUNCTIONAL.replace("The pricing shall give the price of a product in cents.", DISCOUNTED)
TEST_OF_TOTAL = "tests.test_shop::test_two_teas_cost_nine_hundred"


def git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                          capture_output=True, text=True, check=True)
    return done.stdout.strip()


def write(root: Path, changed: dict[str, str]) -> None:
    for name, text in changed.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)


def repository(root: Path, contents: dict[str, str] = SHOP) -> Path:
    """A project in a git repository, committed on main."""
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    write(root, contents)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the shop")
    return root


def on_branch(root: Path, part: str, changed: dict[str, str]) -> tuple[PartBranch, Analysis, Analysis]:
    """The branch of a part, cut from main and tracking it, with some files changed: as git and zigdag read it."""
    git(root, "checkout", "-q", "-b", branch_of(part), "--track", "main")
    write(root, changed)
    on = plans.on_part(files.checkout(root), "main")
    assert not on.refused and on.branch is not None
    start = plans.analysis(files.from_git(root, on.starts[0]))
    return on.branch, start, plans.analysis(files.from_disk(root))


def broken(branch: PartBranch, start: Analysis, now: Analysis) -> dict[str, str]:
    return {f.about: f.rule for f in check_part(branch, start, now)}


@verifies("zigdag.core.vocabulary.names#branches")
def test_the_branch_of_a_part_is_named_after_the_part():
    assert branch_of(CHECKOUT_PART) == "part/shop.checkout" and part_built_on("part/shop.checkout") == CHECKOUT_PART
    assert part_built_on("main") is None and part_built_on("part/Not A Part") is None


@verifies("zigdag.core.analysis.checks#stay-in-part")
def test_the_branch_of_a_part_may_change_the_part_the_tests_and_the_log_and_nothing_else(tmp_path):
    inside = on_branch(repository(tmp_path / "inside"), CHECKOUT_PART, {
        "src/shop/checkout.py": CHECKOUT + "\n\nEMPTY = 0\n", "tests/test_shop.py": TESTS + "\n", "design/log.jsonl": ""})
    assert inside[0].touched == ("design/log.jsonl", "src/shop/checkout.py", "tests/test_shop.py")
    assert broken(*inside) == {}

    outside = on_branch(repository(tmp_path / "outside"), CHECKOUT_PART, {
        "src/shop/pricing.py": PRICING + "\n", "design/functional.yaml": WITH_DISCOUNTS, "README.md": "# a shop\n",
        "src/shop/basket.py": '"""Baskets."""\n'})
    found = {f.about: f.say for f in check_part(*outside)}
    assert set(found) == {"src/shop/pricing.py", "design/functional.yaml", "README.md", "src/shop/basket.py"}
    assert all(rule == STAY_IN_PART for rule in broken(*outside).values())
    assert found["src/shop/pricing.py"].startswith("src/shop/pricing.py is the code of shop.pricing")
    assert "zigdag raise" in found["design/functional.yaml"]
    assert found["README.md"].startswith("README.md is no part's code")


@verifies("zigdag.core.analysis.checks#stay-in-part")
def test_a_file_the_branch_removed_is_still_the_part_that_owned_it(tmp_path):
    root = repository(tmp_path / "removed")
    git(root, "checkout", "-q", "-b", branch_of(CHECKOUT_PART), "--track", "main")
    (root / "src/shop/pricing.py").unlink()
    on = plans.on_part(files.checkout(root), "main")
    start = plans.analysis(files.from_git(root, on.starts[0]))
    assert broken(on.branch, start, plans.analysis(files.from_disk(root)))["src/shop/pricing.py"] == STAY_IN_PART


@verifies("zigdag.core.analysis.checks#settled-first")
def test_the_branch_of_a_part_may_not_change_what_other_parts_are_built_against(tmp_path):
    body = on_branch(repository(tmp_path / "body"), PRICING_PART,
                     {"src/shop/pricing.py": PRICING.replace("return 450", "return 400")})
    assert relied_on(body[1], PRICING_PART) == {"shop.pricing.price": CHECKOUT_PART}
    assert broken(*body) == {}  # what price does is the part's own; what it takes and gives is not

    moved = on_branch(repository(tmp_path / "moved"), PRICING_PART,
                      {"src/shop/pricing.py": PRICING.replace("product: str", "product: str, code: str")})
    assert broken(*moved) == {"shop.pricing.price": SETTLED_FIRST}

    gone = on_branch(repository(tmp_path / "gone"), PRICING_PART,
                     {"src/shop/pricing.py": PRICING.replace("def price", "def cost")})
    assert broken(*gone) == {"shop.pricing.price": SETTLED_FIRST}


@verifies("zigdag.cli.plans#part-branch")
def test_a_command_is_told_of_the_part_whose_branch_it_runs_on(tmp_path):
    root = repository(tmp_path / "told")
    assert plans.on_part(files.checkout(root), None).branch is None  # main is no part's branch

    git(root, "checkout", "-q", "-b", branch_of(CHECKOUT_PART))
    untracked = plans.on_part(files.checkout(root), "main")
    assert untracked.refused and "tracks no branch" in untracked.refusal.err[0]

    git(root, "branch", "-q", "--set-upstream-to=main")
    assert "--base" in plans.on_part(files.checkout(root), None).refusal.err[0]
    git(root, "checkout", "-q", "main")
    write(root, {"README.md": "# the shop\n"})
    git(root, "commit", "-q", "-am", "a word")
    git(root, "checkout", "-q", branch_of(CHECKOUT_PART))
    on = plans.on_part(files.checkout(root), "main")
    assert (on.branch.part, on.branch.line, on.branch.behind, on.branch.touched) == (CHECKOUT_PART, "main", 1, ())


def seen_failing(contents: dict[str, str], test: str, ran: set[str]) -> Analysis:
    """The project, had one of its tests failed while the watcher saw it run some units."""
    code = plans.code_model(contents)
    return analyse(plans.project_files(contents), replace(
        code, reports_read=True, results={t.id: model.Outcome.FAILED if t.id == test else model.Outcome.PASSED
                                          for t in code.tests},
        observed=Observations(runs={test: Run(test, frozenset(ran), True)})))


@verifies("zigdag.core.analysis.work#asked")
def test_a_change_asks_each_part_for_a_test_of_what_it_added_or_changed():
    before = plans.analysis(SHOP)
    assert asked(before, before) == {}
    restated = asked(before, plans.analysis({**SHOP, "design/functional.yaml": WITH_DISCOUNTS}))
    assert list(restated) == [PRICING_PART]
    assert restated[PRICING_PART].reasons == (f"shop.pricing#price: needs a test of what it says now: {DISCOUNTED}",)

    answered = TESTS.replace('price("tea") == 450', 'price("tea") == 400')
    assert asked(before, plans.analysis({**SHOP, "design/functional.yaml": WITH_DISCOUNTS,
                                         "tests/test_shop.py": answered})) == {}

    new_part = FUNCTIONAL.replace("\nconstraints:", "  shop.receipts:\n    serves: [keep-shop.wrong-total]\n    statements:\n"
                             "      show: The receipts shall show the total of a basket.\n\nconstraints:")
    receipts = asked(before, plans.analysis({**SHOP, "design/functional.yaml": new_part}))["shop.receipts"]
    assert receipts.reasons == (
        "shop.receipts#show: needs a test of what it says now: The receipts shall show the total of a basket.",
        "shop.receipts: no code yet: write the module, package or class this DP is")


@verifies("zigdag.core.analysis.work#waiting")
def test_a_failing_test_waits_when_it_ran_the_code_of_a_part_that_is_not_built_yet():
    restated = {**SHOP, "design/functional.yaml": WITH_DISCOUNTS}
    unbuilt = asked(plans.analysis(SHOP), plans.analysis(restated))
    through_pricing = waiting(seen_failing(restated, TEST_OF_TOTAL, {"shop.checkout", "shop.pricing"}),
                              CHECKOUT_PART, unbuilt)
    assert through_pricing.on == (PRICING_PART,) and through_pricing.is_all
    assert [f.about for f in through_pricing.set_aside] == ["shop.checkout#total"]

    alone = waiting(seen_failing(restated, TEST_OF_TOTAL, {"shop.checkout"}), CHECKOUT_PART, unbuilt)
    assert alone.on == () and not alone.is_all and [t.id for t in alone.own] == [TEST_OF_TOTAL]
    assert not waiting(plans.analysis(restated), CHECKOUT_PART, unbuilt).tests  # nothing ran, so nothing waits


def answered(root: Path, after: Analysis, tests: plans.ExitCode, branch: PartBranch, start: Analysis) -> list[str]:
    """The last thing ready says on a part's branch, line by line."""
    run = WatchedRun(False, Outcome(), "", root / ".zigdag/observed.json", ("pytest",), root, {})
    return plans.ready(run, Presence.PRESENT, tests, after, (plans.analysis(SHOP),), "main", files.from_disk(root),
                       branch, (start,)).out[-1].splitlines()


@verifies("zigdag.cli.plans#built-waiting", "zigdag.cli.plans#part-ready")
def test_ready_on_the_branch_of_a_part_says_built_when_only_other_parts_are_waited_for(tmp_path):
    root = repository(tmp_path / "waits", {**SHOP, "design/functional.yaml": WITH_DISCOUNTS})
    branch, start, _ = on_branch(root, CHECKOUT_PART, {})
    restated = dict(files.from_disk(root))
    waits = seen_failing(restated, TEST_OF_TOTAL, {"shop.checkout", "shop.pricing"})
    assert answered(root, waits, plans.FOUND, branch, start) == ["built: waiting on shop.pricing to land"]

    own = seen_failing(restated, TEST_OF_TOTAL, {"shop.checkout"})
    assert answered(root, own, plans.FOUND, branch, start)[:2] == [plans.NOT_READY, "  the tests failed (they exited 1)"]

    behind = replace(branch, behind=2)
    assert answered(root, waits, plans.FOUND, behind, start) == [
        plans.NOT_READY, "  main has 2 commits that this branch does not: merge main, and ask again",
        "  1 failing test waits for shop.pricing to land, which is not this branch's to fix"]

    strayed = replace(branch, touched=("src/shop/pricing.py",))
    assert answered(root, waits, plans.FOUND, strayed, start)[:2] == [plans.NOT_READY, "  1 break"]


RUNNABLE = {**SHOP, "pyproject.toml": '[project]\nname = "shop"\ndependencies = []\n'
                                      '[tool.pytest.ini_options]\npythonpath = ["src"]\n'}
TOTALLED = "The checkout shall give the total of a basket in cents after each discount."
BOTH_RESTATED = WITH_DISCOUNTS.replace("The checkout shall give the total of a basket in cents.", TOTALLED)


def said(capsys, *arguments: str) -> list[str]:
    """What a zigdag command prints, line by line."""
    capsys.readouterr()
    main(list(arguments))
    return capsys.readouterr().out.splitlines()


def folder_of(root: Path, part: str) -> Path:
    """A folder with the branch of a part checked out in it, as an agent building the part works in."""
    folder = root.parent / part
    git(root, "worktree", "add", "-q", str(folder), branch_of(part))
    return folder


@verifies("zigdag.cli#work", "zigdag.core.analysis.work#next", "zigdag.core.analysis.work#stops")
def test_work_hands_a_change_out_part_by_part_until_it_is_done(tmp_path, capsys):
    root = repository(tmp_path / "shop", RUNNABLE)
    began = git(root, "rev-parse", "HEAD")
    work = lambda: said(capsys, "--project", str(root), "work", "--base", began)  # noqa: E731
    assert work() == ["done"]  # nothing changed, so nothing is asked

    write(root, {"design/functional.yaml": BOTH_RESTATED})
    assert work()[0] == "blocked: the design is not settled:"  # it is not committed, so no branch would have it
    git(root, "commit", "-q", "-am", "discounts")

    assert work()[:2] == ["build shop.pricing", "  on part/shop.pricing, which lands on main"]
    assert git(root, "rev-parse", "--abbrev-ref", "part/shop.pricing@{upstream}") == "main"  # taken, and tracking
    assert work()[0] == "build shop.checkout"  # checkout uses pricing, and still they are built at the same time
    assert work() == ["wait: 2 parts being built: shop.checkout, shop.pricing"]

    pricing = folder_of(root, PRICING_PART)
    ready = lambda folder: said(capsys, "--project", str(folder), "ready", "--base", began)[-1]  # noqa: E731
    assert ready(pricing) != plans.READY  # the statement changed, and its test has not
    write(pricing, {"tests/test_shop.py": TESTS.replace('price("tea") == 450', 'price("tea") == 450  # no discount')})
    assert ready(pricing) == plans.READY
    assert work()[0] == "land shop.pricing"
    git(pricing, "commit", "-q", "-am", "pricing")
    git(root, "merge", "-q", branch_of(PRICING_PART))
    assert work() == ["wait: 1 part being built: shop.checkout"]

    checkout = folder_of(root, CHECKOUT_PART)
    in_checkout = lambda *arguments: said(capsys, "--project", str(checkout), *arguments)  # noqa: E731
    thread = in_checkout("raise", "question", "shop.pricing", "is a discount per product?", "--by", "agent")[0]
    blocked = work()
    assert blocked[:2] == ["blocked: question on shop.pricing, raised from shop.checkout: is a discount per product?",
                           "  stopped: shop.checkout"]
    in_checkout("answer", thread.removeprefix("raised "), "answered", "per product", "--by", "robert")
    assert work()[0].startswith("wait")

    git(checkout, "merge", "-q", "main")
    write(checkout, {"tests/test_shop.py": (checkout / "tests/test_shop.py").read_text().replace(
        '== 900', '== 900  # no discount')})
    assert ready(checkout) == plans.READY
    assert work()[0] == "land shop.checkout"
    git(checkout, "add", "-A")
    git(checkout, "commit", "-q", "-m", "checkout")
    git(root, "merge", "-q", branch_of(CHECKOUT_PART))
    assert work() == ["done"]


@verifies("zigdag.core.views#changed", "zigdag.core.analysis.work#delta")
def test_the_context_of_a_part_says_what_a_change_changed_for_it_and_asks_of_it():
    before, after = plans.analysis(SHOP), plans.analysis({**SHOP, "design/functional.yaml": WITH_DISCOUNTS})
    shown = plans.view(after, plans.View.CONTEXT, CHECKOUT_PART, (before,), "main").out[0].splitlines()
    # checkout uses pricing, so what changed in pricing concerns it; nothing is asked of checkout itself
    assert shown[2:6] == ["", "  changed since main:", "    ~ FR shop.pricing",
                          f'        statements price: "The pricing shall give the price of a product in cents." → '
                          f'"{DISCOUNTED}"']
    assert "  asked, and not given yet:" not in shown

    pricing = plans.view(after, plans.View.CONTEXT, PRICING_PART, (before,), "main").out[0]
    assert (f"  asked, and not given yet:\n    shop.pricing#price: needs a test of what it says now: {DISCOUNTED}\n"
            in pricing)
    unchanged = plans.view(before, plans.View.CONTEXT, PRICING_PART, (before,), "main").out[0]
    assert "  nothing that concerns it changed since main\n" in unchanged
    assert "changed since" not in plans.view(after, plans.View.CONTEXT, PRICING_PART).out[0]  # no base, no change
