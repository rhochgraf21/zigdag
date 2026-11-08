from zigdag.core.names import CodeName, OutcomeRef, fr_name, parent, slug, subject
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
