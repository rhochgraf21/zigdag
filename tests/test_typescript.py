"""The TypeScript adapter: source read by a parser into the code model, and checked by the same rules as Python."""

from __future__ import annotations

from pathlib import Path

from zigdag import verifies
from zigdag.adapters.adapter import Presence
from zigdag.adapters.known import adapters
from zigdag.adapters.typescript import TypeScriptFiles, read_typescript
from zigdag.adapters.typescript.adapter import TypeScriptAdapter
from zigdag.adapters.tools import Started, ToolOutput, not_started
from zigdag.adapters.typescript import tests as ts_tests
from zigdag.adapters.typescript import observed
from zigdag.adapters.typescript.adapter import WATCHER
from zigdag.adapters.typescript.profiler import read_profile
from zigdag.adapters.typescript.tools import ESLINT, TSC, diagnostics, read_eslint, read_tsc
from zigdag.adapters.typescript.modules import Resolver, declared_libraries, package_of, read_aliases, unit_path
from zigdag.cli import plans
from zigdag.core.code import (
    Abstraction,
    CodeModel,
    DependencyKind,
    Diagnosis,
    Level,
    Outcome,
    Severity,
    SymbolKind,
    ToolName,
    TypeKind,
    UnitKind,
)
from zigdag.core.codec import Unreadable
from zigdag.core.record.model import EvidenceKind
from zigdag.core.findings import Result
from zigdag.core.kinds.registry import Part
from zigdag.core.names import PYTHON, TYPESCRIPT
from zigdag.core.settings import read_settings

SETTINGS = ('[settings]\nruleset = 1\n[adapters]\ndefault = "typescript"\n[adapters.typescript]\n'
            'source = ["web"]\n')
PACKAGE = '{ "dependencies": { "react": "^18" }, "devDependencies": { "@types/node": "^20" } }'
CONFIG = '''{
  // comments and a last comma are allowed here
  "compilerOptions": { "baseUrl": ".", "paths": { "@/*": ["src/*"] }, },
}'''
TYPES = '''/** An order's identity. */
export type OrderId = string & { readonly __brand: "OrderId" };

/** How far an order has got. */
export type Status = "placed" | "paid";

/** One line of a cart. */
export interface Line {
  readonly sku: string;
  quantity: number;
}

/** What can be priced. */
export interface Priced {
  price(rate?: number): number;
}

export enum Colour { Red = "red", Blue = "blue" }

const hidden = 1;
'''
CART = '''import type { Line, Priced } from "@/types";

/** What a shopper means to buy. */
export class Cart implements Priced {
  private readonly lines: Line[] = [];
  static made = 0;

  constructor(public readonly owner: string, limit: number) {}

  /** Put a line in the cart. */
  add(line: Line): void {
    this.lines.push(line);
  }

  price(rate?: number): number {
    return 0;
  }

  #secret(): void {}
}
'''
INDEX = '''export { Cart } from "./cart";
export * from "./totals";
'''
TOTALS = '''import { Line } from "../types.js";

/** How many things the lines hold together. */
export const count = (lines: readonly Line[]): number => lines.length;
'''
CLIENT = '''import * as path from "node:path";
import debounce from "lodash/debounce";
import { Cart, count } from "@/cart";
import type { Line } from "../types";

const ENDPOINT = process.env.API_URL ?? "/api";

/** Send the cart. */
export async function place(cart: Cart, line: Line): Promise<void> {
  console.error(count([]));
  try {
    await fetch(path.join(ENDPOINT, "orders"));
  } catch (error) {
    throw new PlacementError("not placed");
  }
  line.quantity = 2;
  const made = new Cart("x", 1);
  if (new Date().getTime() > Date.now()) { throw new PlacementError("late"); }
}

export class PlacementError extends Error {}

export const soon = debounce(place, 200);

export function load(name: string) {
  eval(name);
  return [require("./lazy"), require(name), import("../types"), import(name)];
}
'''
SOURCES = {"web/src/types.ts": TYPES, "web/src/cart/cart.ts": CART, "web/src/cart/index.ts": INDEX,
           "web/src/cart/totals.ts": TOTALS, "web/src/api/client.ts": CLIENT}


def read(sources: dict[str, str] = SOURCES) -> CodeModel:
    return read_typescript(TypeScriptFiles(sources, ("web",), {"web/package.json": PACKAGE},
                                           {"web/tsconfig.json": CONFIG}))


@verifies("zigdag.adapters.typescript#read")
def test_a_file_is_a_module_a_folders_index_is_the_folder_and_each_folder_on_the_way_is_a_package():
    units = read().units
    assert {path: unit.kind for path, unit in units.items()} == {
        "web/src/types": UnitKind.MODULE, "web/src/cart/cart": UnitKind.MODULE, "web/src/cart/totals": UnitKind.MODULE,
        "web/src/api/client": UnitKind.MODULE, "web/src/cart": UnitKind.PACKAGE, "web/src/api": UnitKind.PACKAGE,
        "web/src": UnitKind.PACKAGE, "web": UnitKind.PACKAGE}
    assert all(unit.adapter == TYPESCRIPT and unit.level is Level.COMPONENT for unit in units.values())
    assert units["web/src/cart"].span.path == "web/src/cart/index.ts" and units["web/src/cart"].size == 2
    assert unit_path("web/src/cart/index.tsx") == "web/src/cart" and unit_path("index.ts") == "index"


@verifies("zigdag.adapters.typescript#read")
def test_declarations_are_symbols_with_what_the_code_says_of_them():
    symbols = read().symbols
    kinds = {name.rpartition(".")[2]: (s.kind, s.public) for name, s in symbols.items() if "types." in name}
    assert kinds == {"OrderId": (SymbolKind.NAMED_TYPE, True), "Status": (SymbolKind.NAMED_TYPE, True),
                     "Line": (SymbolKind.CLASS, True), "Priced": (SymbolKind.CLASS, True),
                     "price": (SymbolKind.METHOD, True), "Colour": (SymbolKind.CLASS, True),
                     "hidden": (SymbolKind.CONSTANT, False)}  # what is not exported is not public
    line, priced = symbols["web/src/types.Line"], symbols["web/src/types.Priced"]
    assert line.description == "One line of a cart." and [f.name for f in line.fields] == ["sku", "quantity"]
    assert line.abstraction is None and priced.abstraction is Abstraction.PROTOCOL  # a shape that asks for methods
    assert symbols["web/src/types.Colour"].members == ("Red", "Blue")
    cart = symbols["web/src/cart/cart.Cart"]
    assert [f.name for f in cart.fields] == ["lines", "owner"]  # a constructor's parameter with a modifier is a field
    assert [b.name for b in cart.bases] == ["web/src/types.Priced"]
    assert symbols["web/src/cart/cart.Cart.__init__"].kind is SymbolKind.METHOD  # as the model names a constructor
    assert not symbols["web/src/cart/cart.Cart.#secret"].public
    count = symbols["web/src/cart/totals.count"]  # a function given to a constant is a function
    assert count.kind is SymbolKind.FUNCTION and count.signature.params[0].type.kind is TypeKind.CONTAINER


@verifies("zigdag.adapters.typescript#read")
def test_a_type_is_read_as_written_in_the_models_terms():
    place = read().symbols["web/src/api/client.place"].signature
    cart, line = place.params
    assert (cart.type.kind, cart.type.name) == (TypeKind.REF, "web/src/cart/cart.Cart")  # through the folder's index
    assert line.type.name == "web/src/types.Line" and place.returns.kind is TypeKind.CONTAINER  # Promise<void>
    text = '''export function f(a: boolean, b: string | null, c: any, d: "x" | "y", e: Map<string, Thing>,
                                 f: { inline: number }, g: Thing[]): undefined {}
              export interface Thing { id: string }'''
    types = {p.name: p.type for p in read({"web/t.ts": text}).symbols["web/t.f"].signature.params}
    assert [types[n].kind for n in "abcdef"] == [TypeKind.BOOL, TypeKind.UNION, TypeKind.ANY, TypeKind.LITERAL,
                                                 TypeKind.CONTAINER, TypeKind.UNKNOWN]
    assert types["b"].named == "builtins.string" and types["d"].values == ("x", "y")
    assert types["e"].args[1].name == "web/t.Thing" and types["g"].args[0].name == "web/t.Thing"


@verifies("zigdag.adapters.typescript#imports")
def test_an_import_is_followed_to_the_module_that_declares_the_name_or_is_a_library_by_its_package():
    model = read()
    imports = {(str(d.source), d.target) for d in model.dependencies if d.kind is DependencyKind.IMPORT}
    assert {("web/src/api/client", "path"), ("web/src/api/client", "lodash"), ("web/src/api/client", "web/src/cart"),
            ("web/src/api/client", "web/src/types"), ("web/src/cart", "web/src/cart/cart"),
            ("web/src/cart", "web/src/cart/totals"), ("web/src/cart/totals", "web/src/types"),
            ("web/src/api/client.load", "web/src/types")} <= imports
    references = {(str(d.source), d.target) for d in model.dependencies if d.kind is DependencyKind.REFERENCE}
    # Cart and count are imported from the folder, which only passes them on: each is followed to where it is declared
    assert ("web/src/api/client.place", "web/src/cart/cart.Cart") in references
    assert ("web/src/api/client.place", "web/src/cart/totals.count") in references
    assert ("web/src/api/client.place", "path.join") in references
    assert package_of("node:fs/promises") == "fs" and package_of("@scope/pkg/deep") == "@scope/pkg"
    resolver = Resolver.of(SOURCES, [read_aliases("web/tsconfig.json", CONFIG)])
    assert resolver.resolve("web/src/api/client.ts", "@/cart").unit == "web/src/cart"
    assert resolver.resolve("web/src/api/client.ts", "./missing").name == ""  # it names nothing that was read
    assert read_aliases("web/tsconfig.json", "{") is None
    libraries = model.libraries[TYPESCRIPT]
    assert libraries.declared == {"react", "@types/node"} and "fs" in libraries.standard
    assert declared_libraries("[]") is None and declared_libraries("{") is None


@verifies("zigdag.adapters.typescript#effects")
def test_calls_that_touch_the_world_are_effects_and_code_made_from_text_is_unknown():
    model = read()
    effects = {(str(e.at), e.effect, e.via) for e in model.effects}
    assert effects == {("web/src/api/client", "env", "process.env.API_URL"),
                       ("web/src/api/client.place", "stderr", "console.error"),
                       ("web/src/api/client.place", "network", "fetch"),
                       ("web/src/api/client.place", "time", "new Date"),
                       ("web/src/api/client.place", "time", "Date.now")}
    assert sorted(u.what for u in model.unknowns) == ["eval", "import", "require"]  # each named by what cannot be read
    caught, escapes = sorted(model.raises, key=lambda r: r.span.line)
    assert caught.error.name == "web/src/api/client.PlacementError"
    assert not caught.caught and not escapes.caught  # thrown from a catch, and outside any try: neither is caught
    files = read({"web/io.ts": 'import fs from "fs";\nimport { readFile } from "fs/promises";\n'
                               'export function f() { fs.writeFileSync("a", ""); return readFile("a"); }\n'
                               'export function g() { try { throw new Error("x"); } catch { return 1; } }'})
    assert sorted((e.effect, e.via) for e in files.effects) == [("read", "fs.readFile"), ("write", "fs.writeFileSync")]
    assert [r.caught for r in files.raises] == [True]


@verifies("zigdag.adapters.typescript#effects")
def test_a_change_to_a_field_of_a_value_whose_type_the_code_says_is_read():
    changes = {(str(a.at), a.value.root, a.field, a.in_place) for a in read().accesses}
    assert changes == {("web/src/api/client.place", "web/src/types.Line", "quantity", False),
                       ("web/src/cart/cart.Cart.add", "web/src/cart/cart.Cart", "lines", True)}


@verifies("zigdag.adapters.typescript#unread")
def test_a_file_the_parser_cannot_read_is_a_question_and_nothing_is_taken_from_it():
    model = read({"web/ok.ts": "export const a = 1;\n", "web/bad.ts": "export function ( {\n"})
    (problem,) = model.problems
    assert problem.result is Result.QUESTION and problem.about == "web/bad.ts"
    assert set(model.symbols) == {"web/ok.a"} and "web/bad" in model.units  # the file is still a module to place
    unread_config = read_typescript(TypeScriptFiles({"web/ok.ts": ""}, ("web",), {}, {"web/tsconfig.json": "{"}))
    assert [p.about for p in unread_config.problems] == ["web/tsconfig.json"]
    assert unread_config.libraries[TYPESCRIPT].declared is None  # no package.json was read


@verifies("zigdag.adapters.typescript.type_script_adapter#choose")
def test_the_adapter_is_there_only_when_configured_and_wants_source_but_not_tests_or_declarations():
    plain, _ = read_settings("[settings]\nruleset = 1\n")
    assert TypeScriptAdapter.of(plain) is None
    settings, problems = read_settings(SETTINGS)
    assert not problems and [a.name for a in adapters(settings, Presence.ABSENT)] == [PYTHON, TYPESCRIPT]
    typescript = TypeScriptAdapter.of(settings)
    assert typescript.wants("web/src/cart.ts") and typescript.wants("web/src/App.tsx")
    assert typescript.wants("package.json") and typescript.wants("web/tsconfig.json")
    assert typescript.wants("web/src/cart.test.ts") and typescript.is_test("web/src/__tests__/cart.ts")
    assert typescript.wants("tests/e2e.ts") and not typescript.is_source("web/src/cart.spec.tsx")  # tests, not source
    for other in ("web/src/types.d.ts", "api/main.ts", "web/src/cart.js", "api/main.test.ts"):
        assert not typescript.wants(other), other
    assert typescript.read({"src/shop.py": ""}) is None and typescript.test_run({}, (), Path(".")) is None


RECORD = {
    "design/customer.yaml": """
buy:
  job: Buy a product
  performer: Shopper
  outcomes:
    lost-order: Minimize the likelihood that a placed order is lost
""",
    "design/functional.yaml": """
frs:
  shop:
    statements:
      sell: The shop shall take orders for products from shoppers.
  shop.cart:
    serves: [buy.lost-order]
    statements:
      hold: The cart shall hold what a shopper means to buy.
  shop.api:
    serves: [buy.lost-order]
    statements:
      send: The api shall send each placed order.
  shop.types:
    serves: [buy.lost-order]
    statements:
      name: The types shall name what an order is made of.
constraints:
  quiet-cart:
    on: shop.cart
    serves: [buy.lost-order]
    check: effects
    with:
      allow: []
  api-talks:
    on: shop.api
    serves: [buy.lost-order]
    check: effects
    with:
      allow: [network]
""",
    "design/physical.yaml": "shop: [web/src]\nshop.cart: [cart]\nshop.api: [api]\nshop.types: [types]\n",
}


def said(analysis, rule: str) -> list[str]:
    return [f.say for f in analysis.report.of_result(Result.BREAKS) if f.rule == rule]


@verifies("zigdag.adapters.typescript#read", "zigdag.core.analysis.resolve#own")
def test_typescript_is_placed_and_checked_by_the_rules_that_check_python():
    files = {"zigdag.toml": SETTINGS, "web/package.json": PACKAGE, "web/tsconfig.json": CONFIG, **RECORD, **SOURCES}
    analysis = plans.analysis(files)
    owner = analysis.tree.unit_owner
    assert owner["web/src/cart/totals"] == "shop.cart" and owner["web/src/api/client"] == "shop.api"
    assert not said(analysis, "placement") and not said(analysis, "coverage")
    assert not said(analysis, "quiet-cart")
    assert sorted(s.split(": ")[1].split(" (")[0] for s in said(analysis, "api-talks")) == [
        "reading environment variables", "reading the clock", "writing to standard error"]  # each effect of a place once
    assert said(analysis, "declared-libraries") == ["lodash is imported but not declared as a dependency"]
    order, cells = analysis.context.relations.matrix(analysis.tree, "shop")
    assert {pair for pair in cells} == {("shop.api", "shop.cart"), ("shop.api", "shop.types"),
                                        ("shop.cart", "shop.types")}


PYTHON_BESIDE = {"src/tools/__init__.py": '"""Tools written in Python, beside the TypeScript."""\n'}


@verifies("zigdag.core.analysis.checks#not-read")
def test_a_rule_says_so_when_it_covers_code_whose_adapter_does_not_read_what_the_rule_reads():
    # Python's adapter supplies mutants, so the mutation rule runs; TypeScript's does not read them.
    files = {"zigdag.toml": SETTINGS, "web/package.json": PACKAGE, "web/tsconfig.json": CONFIG, **RECORD, **SOURCES,
             **PYTHON_BESIDE}
    questions = [f for f in plans.analysis(files).report.of_result(Result.QUESTION) if f.rule == "not-checked"]
    (unread,) = [f.say for f in questions if f.about == TYPESCRIPT]
    assert unread == ("these rules say nothing of typescript code, since the typescript adapter does not read its "
                      "mutants yet: mutation")
    alone = {name: text for name, text in files.items() if name not in PYTHON_BESIDE}
    waits = [f.say for f in plans.analysis(alone).report.of_result(Result.QUESTION) if f.rule == "code-not-read"]
    assert any("no adapter supplied mutants" in say and "mutation" in say for say in waits)  # then it waits whole


ROOT = Path("/project")
# As eslint 10 prints it: each file by its full path on disk.
ESLINT_JSON = """[{"filePath": "/project/web/src/api/client.ts", "messages": [
  {"ruleId": "@typescript-eslint/no-unused-vars", "severity": 2, "message": "'x' is defined but never used.",
   "line": 4, "column": 22},
  {"ruleId": "no-console", "severity": 1, "message": "Unexpected console statement.", "line": 9, "column": 3},
  {"ruleId": null, "fatal": true, "severity": 2, "message": "Parsing error: Unexpected token"}]},
 {"filePath": "/project/web/src/types.ts", "messages": []}]"""
# As tsc 5.9 prints it with --pretty false: each file from where it ran, and a long error over several lines.
TSC_TEXT = """web/src/api/client.ts(4,3): error TS2322: Type 'number' is not assignable to type 'string'.
web/src/types.ts(9,1): error TS2345: Argument of type 'A' is not assignable to parameter of type 'B'.
  Property 'id' is missing in type 'A'.
"""


@verifies("zigdag.adapters.typescript#tools")
def test_eslint_and_tsc_are_read_each_in_its_own_form_at_the_source_file_it_means():
    unused, console, fatal = read_eslint(ESLINT_JSON, Diagnosis.LINT, ToolName("eslint"))
    assert (unused.code, unused.severity, unused.span.line) == ("@typescript-eslint/no-unused-vars", Severity.ERROR, 4)
    assert console.severity is Severity.WARNING and (fatal.code, fatal.span.line) == ("fatal", 1)
    assert isinstance(read_eslint("{", Diagnosis.LINT, ToolName("eslint")), Unreadable)
    assert isinstance(read_eslint('[{"messages": []}]', Diagnosis.LINT, ToolName("eslint")), Unreadable)
    assigned, missing = read_tsc(TSC_TEXT, Diagnosis.TYPES, ToolName("tsc"))
    assert (str(assigned.span), assigned.code) == ("web/src/api/client.ts:4:3", "TS2322")
    assert missing.say.endswith("parameter of type 'B'. Property 'id' is missing in type 'A'.")
    unread = read_tsc("error TS5083: Cannot read file 'tsconfig.json'.\n", Diagnosis.TYPES, ToolName("tsc"))
    assert isinstance(unread, Unreadable)  # tsc did not check the code
    found, failure = diagnostics(ToolOutput(ESLINT, Started.STARTED, 1, ESLINT_JSON), SOURCES)  # 1: it found errors
    assert failure is None and {d.span.path for d in found} == {"web/src/api/client.ts"}
    assert "eslint failed (exit 2)" in diagnostics(ToolOutput(ESLINT, Started.STARTED, 2, ""), SOURCES)[1].say
    assert "tsc could not be started" in diagnostics(not_started(TSC), SOURCES)[1].say
    settings, _ = read_settings(SETTINGS + 'tsc = "web/node_modules/.bin/tsc"\n')
    typescript = TypeScriptAdapter.of(settings)
    files = {**SOURCES, "web/tsconfig.json": CONFIG}
    assert typescript.tool_runs({}, (Diagnosis.LINT,)) == () and typescript.tool_runs(files, (Diagnosis.SECURITY,)) == ()
    lint, types = typescript.tool_runs(files, (Diagnosis.LINT, Diagnosis.TYPES))
    assert lint.command == ("npx", "eslint", "--format=json", "web")
    assert types.command == ("web/node_modules/.bin/tsc", "--noEmit", "--pretty", "false", "--project", "web")
    model = typescript.read(files, (ToolOutput(TSC, Started.STARTED, 2, TSC_TEXT),))
    assert len(model.diagnostics) == 2 and Diagnosis.TYPES.part in model.supplied


CART_TEST = '''import { describe, expect, it, test, bench } from "vitest";
import fc from "fast-check";
import { Cart } from "./cart";
import { count } from "@/cart";

describe("the cart", () => {
  it("holds a line verifies(shop.cart#hold, shop#sell)", () => { expect(new Cart("a", 1)).toBeTruthy(); });
  describe("when empty", () => {
    it.skip("counts nothing", () => {});
  });
  it("counts any lines", () => { fc.assert(fc.property(fc.array(fc.nat()), (n) => count([]) === 0)); });
});
test.each([1, 2])("counts %i of $what", (n) => {});
bench("counting", () => { count([]); });
it(`named ${1} at run time`, () => {});
'''
TEST_PATH = "web/src/cart/cart.test.ts"
# As vitest 5 writes it: a file from the folder vitest ran in, and a test by its groups and its name.
JUNIT = """<?xml version="1.0" encoding="UTF-8" ?>
<testsuites><testsuite name="src/cart/cart.test.ts" tests="5">
  <testcase classname="src/cart/cart.test.ts" name="the cart &gt; holds a line verifies(shop.cart#hold, shop#sell)"></testcase>
  <testcase classname="src/cart/cart.test.ts" name="the cart &gt; when empty &gt; counts nothing"><skipped/></testcase>
  <testcase classname="src/cart/cart.test.ts" name="counts 1 of tea"></testcase>
  <testcase classname="src/cart/cart.test.ts" name="counts 2 of milk"><failure message="no"></failure></testcase>
  <testcase classname="src/other.test.ts" name="the cart &gt; counts any lines"></testcase>
</testsuite></testsuites>"""


@verifies("zigdag.adapters.typescript#tests")
def test_each_test_of_a_test_file_is_named_as_vitest_names_it_and_linked_by_its_name():
    files = TypeScriptFiles(SOURCES, ("web",), {}, {"web/tsconfig.json": CONFIG}, {TEST_PATH: CART_TEST}, JUNIT,
                            ".zigdag/typescript.junit")
    model = read_typescript(files)
    tests = {t.id.partition("::")[2]: t for t in model.tests}
    assert set(tests) == {"the cart > holds a line verifies(shop.cart#hold, shop#sell)",
                          "the cart > when empty > counts nothing", "the cart > counts any lines",
                          "counts %i of $what", "counting"}  # a test whose name is worked out has none to know it by
    holds = tests["the cart > holds a line verifies(shop.cart#hold, shop#sell)"]
    assert [link.target for link in holds.links] == ["shop.cart#hold", "shop#sell"]
    assert {"web/src/cart/cart.Cart", "web/src/cart/totals.count", "web/src/cart", "vitest"} <= set(holds.imports)
    assert tests["the cart > counts any lines"].evidence is EvidenceKind.PROPERTY_TEST
    assert tests["counting"].evidence is EvidenceKind.BENCHMARK and holds.evidence is EvidenceKind.UNIT_TEST
    results = {test.partition("::")[2]: outcome for test, outcome in model.results.items()}
    assert results == {"the cart > holds a line verifies(shop.cart#hold, shop#sell)": Outcome.PASSED,
                       "the cart > when empty > counts nothing": Outcome.SKIPPED,
                       "counts %i of $what": Outcome.FAILED}  # run for two cases: the worse result is its own
    assert ts_tests.read_report("<not xml", []) is None and model.reports_read
    settings, _ = read_settings(SETTINGS + 'test_command = "npx vitest run --root web"\n')
    typescript = TypeScriptAdapter.of(settings)
    run = typescript.test_run({TEST_PATH: CART_TEST}, ("ignored",), ROOT)
    assert not run.watched and run.command == (
        "npx", "vitest", "run", "--root", "web", "--reporter=default", "--reporter=junit",
        "--outputFile.junit=/project/.zigdag/typescript.junit")
    assert typescript.test_run(SOURCES, (), ROOT) is None  # no tests, nothing to run


@verifies("zigdag.adapters.typescript#tests")
def test_a_passing_typescript_test_is_evidence_for_the_statement_its_name_says_it_verifies():
    files = {"zigdag.toml": SETTINGS, "web/package.json": PACKAGE, "web/tsconfig.json": CONFIG, **RECORD, **SOURCES,
             TEST_PATH: CART_TEST, ".zigdag/typescript.junit": JUNIT}
    analysis = plans.analysis(files)
    evidence = {f.about: f.result for f in analysis.report.findings if f.rule == "evidence"}
    assert "shop.cart#hold" not in evidence and "shop#sell" not in evidence  # verified by a test that passed
    assert evidence["shop.api#send"] is Result.TODO


CORE_TS = '''/** An order. */
export interface Order { id: string; cents: number; email: Email; card: string | null }
/** Where to write to a shopper. */
export class Email { constructor(readonly address: string) {} }
/** What to charge. */
export interface Plan { cents: number; card: string }

/** Decide what an order is charged. */
export function plan(order: Order, vip: boolean): Plan {
  const cents = vip ? order.cents * 9 : order.cents;
  return { cents, card: order.card ?? "" };
}

/** A label for an order. */
export function label(order: Order): string {
  return order.id;
}

/** Whether a kind is the big one. */
export function big(kind: string, order: Order): boolean {
  if (kind === "big") { return true; }
  return keep(order);
}
function keep(order: Order): boolean { return order.cents > 0; }
'''
SHELL_TS = '''import { plan, label, Order, Plan } from "./core";
import { charge } from "./bank";

/** Only carries out what the core decided. */
export function checkout(order: Order): void {
  const decided: Plan = plan(order, false);
  charge(decided.card, decided.cents);
}

/** Decides for itself, in code with effects. */
export function discount(order: Order): void {
  if (order.cents > 100) {
    charge(order.card ?? "", order.cents * 9);
  }
}

/** Tells the shopper. */
export function tell(order: Order): void {
  console.log(`sent ${label(order)} to ${order.email}`);
  console.error(order.email);
}
'''
BANK_TS = '''/** Charge a card. */
export function charge(card: string, cents: number): void {
  fetch("/charge", { method: "POST" });
}
'''
FLOW_RECORD = {
    "design/customer.yaml": RECORD["design/customer.yaml"],
    "design/functional.yaml": """
frs:
  shop:
    statements:
      sell: The shop shall take orders for products from shoppers.
  shop.core:
    serves: [buy.lost-order]
    statements:
      decide: The core shall decide what each order is charged.
  shop.shell:
    serves: [buy.lost-order]
    statements:
      carry: The shell shall carry out what the core decided.
  shop.bank:
    serves: [buy.lost-order]
    statements:
      charge: The bank shall charge a card.
constraints:
  pure-core:
    on: shop.core
    serves: [buy.lost-order]
    check: effects
    with:
      allow: []
  quiet-email:
    on: shop
    serves: [buy.lost-order]
    check: data-flow
    with:
      data: [core.Email]
      never-reaches: [stdout, stderr]
""",
    "design/physical.yaml": "shop: [web/src]\n",
}
FLOW = {"zigdag.toml": SETTINGS, **FLOW_RECORD, "web/src/core.ts": CORE_TS, "web/src/shell.ts": SHELL_TS,
        "web/src/bank.ts": BANK_TS}


def findings(rule: str, result: Result = Result.BREAKS) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f in plans.analysis(FLOW).report.of_result(result):
        if f.rule == rule:
            out.setdefault(f.about.rpartition(".")[2], []).append(f.say)
    return out


@verifies("zigdag.adapters.typescript#values")
def test_where_a_typescript_functions_values_come_from_is_traced_for_planned_effects():
    breaks = findings("planned-effects")
    assert "checkout" not in breaks, breaks.get("checkout")  # it passes on what a pure function returned
    assert any("works out `order.cents > 100` in code with effects" in s for s in breaks["discount"])
    assert any("works out `order.cents * 9`" in s for s in breaks["discount"])
    assert "plan" not in breaks and "big" not in breaks  # the core is pure: it may decide


@verifies("zigdag.adapters.typescript#values")
def test_what_a_typescript_function_does_with_a_parameter_is_read_for_narrow_parameters():
    core = read({"web/src/core.ts": CORE_TS}).symbols
    (order,) = core["web/src/core.label"].signature.params
    assert (order.fields_read, order.used_whole, order.branched_on) == (("id",), False, False)
    kind, passed = core["web/src/core.big"].signature.params
    assert kind.branched_on and passed.used_whole and not passed.fields_read  # handed on whole to another function
    asks = findings("narrow-parameters", Result.QUESTION)
    assert any("order" in s and "id" in s for s in asks["label"])


@verifies("zigdag.adapters.typescript#values")
def test_a_protected_value_released_or_given_to_an_effect_in_typescript_breaks_data_flow():
    uses = [(u.via, u.kind.value, u.effect) for u in read({"web/src/shell.ts": SHELL_TS}).uses
            if str(u.at) == "web/src/shell.tell"]
    assert ("a template", "release", None) in uses and ("console.error", "effect", "stderr") in uses
    breaks = findings("quiet-email")
    assert any("console.error" in s for s in breaks["tell"]), breaks


# As Node 26 writes a CPU profile: each node of the calls with its place and the lines the run was found on, then
# which node each sample was taken in and how long after the one before, in millionths of a second.
CPU_PROFILE = {
    "nodes": [
        {"id": 1, "callFrame": {"functionName": "(root)", "url": "", "lineNumber": -1}, "children": [2, 3, 4]},
        {"id": 2, "callFrame": {"functionName": "count", "url": "file:///project/web/src/cart/totals.ts",
                                "lineNumber": 3}, "positionTicks": [{"line": 4, "ticks": 3}, {"line": 5, "ticks": 1}]},
        {"id": 3, "callFrame": {"functionName": "run", "url": "node:internal/timers", "lineNumber": 10}},
        {"id": 4, "callFrame": {"functionName": "(idle)", "url": "", "lineNumber": -1}}],
    "startTime": 1_000_000, "endTime": 3_000_000,
    "samples": [2, 2, 3, 4], "timeDeltas": [400_000, 400_000, 200_000, 1_000_000]}


@verifies("zigdag.adapters.typescript#profile")
def test_a_node_cpu_profile_gives_each_line_its_share_of_the_time_and_no_memory():
    import json

    profile = read_profile(json.dumps(CPU_PROFILE), ROOT)
    assert (profile.elapsed, profile.peak) == (2.0, None)  # it measures time only
    shares = {str(line.span): round(line.time, 1) for line in profile.lines}
    # count was in two samples, 0.8 s of the 2 s: three quarters of it on line 4, as the profiler found the run there
    assert shares == {"web/src/cart/totals.ts:4:1": 30.0, "web/src/cart/totals.ts:5:1": 10.0,
                      "node:internal/timers:11:1": 10.0}  # waiting is no line's time
    assert isinstance(read_profile("{", ROOT), Unreadable) and isinstance(read_profile("{}", ROOT), Unreadable)
    settings, _ = read_settings(SETTINGS + 'test_command = "npx vitest run --root web"\n')
    profiling = TypeScriptAdapter.of(settings).profiled_tests(("-t", "cart"), ROOT)
    assert profiling.command == (
        "npx", "vitest", "run", "--root", "web", "--pool=forks", "--no-file-parallelism", "--execArgv=--cpu-prof",
        "--execArgv=--cpu-prof-dir=/project/.zigdag", "--execArgv=--cpu-prof-name=profile.json", "-t", "cart")
    files = {"zigdag.toml": SETTINGS, **RECORD, **SOURCES, "web/tsconfig.json": CONFIG}
    analysis = plans.analysis(files)
    shown = plans.costs(analysis, plans.reading_of(files).adapters, ROOT, json.dumps(CPU_PROFILE), None).out[0]
    assert "the tests ran for 2.0 s\n" in shown and "shop.cart" in shown and "memory allocated" not in shown
    assert "node --cpu-prof measures time only: memory and leaks are not known" in shown


def seen_line(name: str, ran: dict[str, str], test_text: str = CART_TEST) -> str:
    """One line as the watcher writes it: a test, and the files whose code ran, each with what it held."""
    import json

    return json.dumps({"test": {"file": TEST_PATH, "digest": observed.digest(test_text), "name": name},
                       "ran": [{"file": path, "digest": observed.digest(text)} for path, text in ran.items()]})


@verifies("zigdag.adapters.typescript#watched")
def test_what_the_watcher_saw_says_which_modules_each_test_ran_while_nothing_has_changed():
    holds = "the cart > holds a line verifies(shop.cart#hold, shop#sell)"
    seen = "\n".join([
        seen_line(holds, {"web/src/cart/cart.ts": CART, "web/src/cart/totals.ts": TOTALS}),
        seen_line("counts 1 of tea", {"web/src/cart/totals.ts": TOTALS}),
        seen_line("counts 2 of milk", {"web/src/cart/totals.ts": "as it was before a change"}),
        seen_line("a test that is gone", {})]) + "\n"
    files = TypeScriptFiles(SOURCES, ("web",), {}, {"web/tsconfig.json": CONFIG}, {TEST_PATH: CART_TEST}, JUNIT,
                            ".zigdag/typescript.junit", seen=seen)
    model = read_typescript(files)
    runs = {test.partition("::")[2]: run for test, run in model.observed.runs.items()}
    assert set(runs) == {holds, "counts %i of $what"}  # a test seen running that is no longer written is left out
    assert runs[holds].ran == {"web/src/cart/cart", "web/src/cart/totals"} and runs[holds].current
    assert not runs["counts %i of $what"].current  # one of its cases ran code that has changed since
    assert Part.OBSERVATIONS in model.supplied and not model.problems
    assert observed.read_seen("not json\n") is None and observed.read_seen('{"test": {}}\n') is None
    garbled = read_typescript(TypeScriptFiles(SOURCES, ("web",), tests={TEST_PATH: CART_TEST}, seen="{"))
    assert garbled.observed is None and [p.about for p in garbled.problems] == [observed.SEEN_FILE]


@verifies("zigdag.adapters.typescript#watched")
def test_tests_that_ran_with_no_watcher_attached_are_a_thing_to_do_that_says_how_to_attach_it():
    ran = TypeScriptFiles(SOURCES, ("web",), {}, {"web/tsconfig.json": CONFIG}, {TEST_PATH: CART_TEST}, JUNIT,
                          ".zigdag/typescript.junit")
    (problem,) = read_typescript(ran).problems
    assert problem.result is Result.TODO and "setupFiles: process.env.ZIGDAG_WATCHER" in problem.say
    never_ran = TypeScriptFiles(SOURCES, ("web",), tests={TEST_PATH: CART_TEST})
    assert not read_typescript(never_ran).problems  # tests that have not run have had no watcher to miss
    settings, _ = read_settings(SETTINGS)
    run = TypeScriptAdapter.of(settings).test_run({TEST_PATH: CART_TEST}, (), ROOT)
    assert run.environment == {"ZIGDAG_WATCHER": str(WATCHER), "ZIGDAG_SEEN": "/project/.zigdag/observed.typescript.jsonl",
                               "ZIGDAG_ROOT": "/project"}
    assert run.clears == (observed.SEEN_FILE,) and WATCHER.is_file()  # the watcher is shipped where it is said to be


@verifies("zigdag.adapters.typescript#watched")
def test_a_test_seen_running_no_code_of_what_it_verifies_is_linked_to_the_wrong_thing():
    holds = "the cart > holds a line verifies(shop.cart#hold, shop#sell)"
    files = {"zigdag.toml": SETTINGS, "web/package.json": PACKAGE, "web/tsconfig.json": CONFIG, **RECORD, **SOURCES,
             TEST_PATH: CART_TEST, ".zigdag/typescript.junit": JUNIT,
             ".zigdag/observed.typescript.jsonl": seen_line(holds, {"web/src/types.ts": TYPES}) + "\n"}
    (wrong,) = [f.say for f in plans.analysis(files).report.of_result(Result.BREAKS)
                if f.rule == "evidence" and f.about == "shop.cart#hold"]
    assert "ran no code in shop.cart when it last ran, so it is linked to the wrong thing" in wrong


CONTRACTED_TS = CORE_TS.replace('''export function label(order: Order): string {
  return order.id;''', '''export function label(order: Order): string {
  requires(order.id.length > 0, "an order has an id");
  return order.id;''').replace("/** An order. */", 'import { requires, ensures } from "ts-code-contracts";\n/** An order. */')


@verifies("zigdag.adapters.typescript#contracts")
def test_a_function_that_calls_requires_or_ensures_states_a_contract():
    symbols = read({"web/src/core.ts": CONTRACTED_TS}).symbols
    assert symbols["web/src/core.label"].contract and not symbols["web/src/core.plan"].contract
    own = 'import { ensures } from "./promises";\nexport function f(n: number): number { return ensures(n > 0) ? n : n; }\n'
    files = TypeScriptFiles({"web/a.ts": own, "web/promises.ts": "export function ensures(c: unknown): asserts c {}\n"},
                            ("web",))
    assert not read_typescript(files).symbols["web/a.f"].contract  # a module of that name is not one the project named
    named = TypeScriptFiles(files.sources, ("web",), contracts="web/promises")
    assert read_typescript(named).symbols["web/a.f"].contract
    settings, _ = read_settings(SETTINGS + 'contracts = "web/promises"\n')
    assert TypeScriptAdapter.of(settings).read(dict(files.sources)).symbols["web/a.f"].contract


@verifies("zigdag.adapters.typescript#contracts", "zigdag.core.analysis.checks#not-read")
def test_a_pure_typescript_function_another_part_uses_needs_a_contract_and_its_mutants_are_not_made():
    analysis = plans.analysis({**FLOW, "web/src/core.ts": CONTRACTED_TS})
    asked_for = {f.about.rpartition(".")[2]: f.say for f in analysis.report.of_result(Result.BREAKS)
                 if f.rule == "contracted-interfaces"}
    assert "label" not in asked_for and "plan" in asked_for  # label states one; plan is used by the shell and does not
    assert "say what it promises (requires, ensures, from ts-code-contracts)" in asked_for["plan"]
    from zigdag.core.watch import plan as watch_plan

    handed = watch_plan(analysis, [], {})  # what a watcher is told to run: none of it is TypeScript's
    assert not handed.contracts and not handed.mutated


ZOD_TS = '''import { z } from "zod";

/** One line of a cart. */
export const Line = z.object({
  sku: z.string().min(1),
  /** How many of it. */
  quantity: z.number().int().positive(),
});
export type Line = z.infer<typeof Line>;

export const Status = z.enum(["placed", "paid"]);
export type Status = z.infer<typeof Status>;

/** A placed order. */
export const Order = z.object({
  id: z.string().uuid().describe("Its identity."),
  lines: z.array(Line),
  status: Status,
  note: z.string().optional(),
  kind: z.literal("order"),
  owner: z.union([z.string(), z.null()]),
  meta: z.object({ at: z.date() }),
}).strict();
export type Order = z.infer<typeof Order>;

export const Gift = Order.extend({ wrap: z.boolean() });
export const Slim = Order.pick({ id: true });
export const MAX = 3;

/** Read an order from what was sent. */
export function parse(sent: unknown): Order {
  return Order.parse(sent);
}
'''


@verifies("zigdag.adapters.typescript#schemas")
def test_a_zod_schema_of_an_object_is_a_structure_with_its_keys_as_fields():
    symbols = read({"web/src/model.ts": ZOD_TS}).symbols
    line, order = symbols["web/src/model.Line"], symbols["web/src/model.Order"]
    assert line.kind is SymbolKind.CLASS and line.description == "One line of a cart."
    assert [(f.name, f.type.name, f.description) for f in line.fields] == [
        ("sku", "builtins.string", None), ("quantity", "builtins.number", "How many of it.")]
    kinds = {f.name: f.type.kind for f in order.fields}
    assert kinds == {"id": TypeKind.REF, "lines": TypeKind.CONTAINER, "status": TypeKind.REF, "note": TypeKind.UNION,
                     "kind": TypeKind.LITERAL, "owner": TypeKind.UNION, "meta": TypeKind.UNKNOWN}
    by_name = {f.name: f for f in order.fields}
    assert by_name["id"].key and by_name["id"].description == "Its identity."
    assert by_name["lines"].type.args[0].name == "web/src/model.Line"  # another schema, by its name
    assert by_name["status"].type.name == "web/src/model.Status" and by_name["note"].type.named == "builtins.string"
    assert symbols["web/src/model.Status"].members == ("placed", "paid")
    gift = symbols["web/src/model.Gift"]
    assert [b.name for b in gift.bases] == ["web/src/model.Order"] and [f.name for f in gift.fields] == ["wrap"]
    assert symbols["web/src/model.Slim"].kind is SymbolKind.CONSTANT  # worked out from another: not followed
    assert symbols["web/src/model.MAX"].kind is SymbolKind.CONSTANT
    parse = symbols["web/src/model.parse"].signature  # the type taken from the schema is the schema's structure
    assert parse.returns.name == "web/src/model.Order"
