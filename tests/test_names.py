from zigdag.core.code import CodeModel, Unit, UnitKind
from zigdag.core.findings import Span
from zigdag.core.names import TYPESCRIPT, CodeName, OutcomeRef, enclosing, fr_name, is_inside, nesting, parent, slug, subject, within
from zigdag import verifies


@verifies("zigdag.core.vocabulary.names#read")
def test_fr_names_are_dotted_lowercase_identifiers():
    assert fr_name("mojo2verus.core.emit") == "mojo2verus.core.emit"
    assert fr_name("shop.orders_db") == "shop.orders_db"
    for bad in ("Mojo", "a..b", "a.", ".a", "a-b", "a b", "1a"):
        assert fr_name(bad) is None


def test_slugs_are_lowercase_words_joined_by_hyphens():
    assert slug("wrong-proof-passes") == "wrong-proof-passes"
    for bad in ("Wrong", "a_b", "a--b", "-a", "a-"):
        assert slug(bad) is None


def test_outcome_references_name_a_job_and_an_outcome():
    assert OutcomeRef.parse("verify-programs.wrong-proof-passes") == OutcomeRef("verify-programs", "wrong-proof-passes")
    assert OutcomeRef.parse("verify-programs") is None
    assert OutcomeRef.parse("a.b.c") is None


@verifies("zigdag.core.vocabulary.names#read")
def test_code_names_take_a_known_adapter_or_none():
    assert CodeName.parse("terraform:aws_s3_bucket.site") == CodeName("terraform", "aws_s3_bucket.site")
    assert CodeName.parse("emit.translator_names") == CodeName(None, "emit.translator_names")
    assert CodeName.parse("cobol:x") is None
    assert CodeName.parse("a b") is None


def test_the_subject_is_the_last_part_with_underscores_as_spaces():
    assert subject("shop.orders_db") == "orders db"
    assert parent("shop.orders_db") == "shop"
    assert parent("shop") is None


@verifies("zigdag.core.vocabulary.names#parts")
def test_a_code_names_parts_are_joined_by_dots_or_by_slashes():
    assert enclosing("web/src/cart.Order") == ("web/src/cart.Order", "web/src/cart", "web/src", "web")
    assert enclosing("shop.api.orders") == ("shop.api.orders", "shop.api", "shop")
    assert is_inside("web/src/cart", "web/src") and is_inside("shop.api", "shop") and is_inside("web", "web")
    assert not is_inside("web/srcs", "web/src") and not is_inside("shopping", "shop")  # a part is a whole part
    assert nesting("web/src/cart.Order") == 3 and nesting("shop") == 0
    assert within("web/src", "cart") == ("web/src.cart", "web/src/cart")
    folder, module = (Unit(path, TYPESCRIPT, UnitKind.MODULE, True, Span(f"{path}.ts", 1, 1), 1)
                      for path in ("web/src", "web/src/cart"))
    model = CodeModel(units={folder.path: folder, module.path: module})
    assert model.unit_of("web/src/cart.Order") == "web/src/cart" and model.unit_of("web/other") is None
