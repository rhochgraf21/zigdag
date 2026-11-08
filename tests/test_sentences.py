from hypothesis import given
from hypothesis import strategies as st

from zigdag.core.language.lexicons import Lexicons
from zigdag.core.language.sentences import Pattern, parse_ears, parse_job, parse_outcome
from zigdag import verifies

L = Lexicons()


def ears(text):
    parsed, problems = parse_ears(text, L)
    return parsed, [p.say for p in problems]


@verifies("zigdag.core.language#parse")
def test_each_ears_pattern_is_recognised():
    cases = {
        "The emit shall translate a checked program into Verus.": Pattern.UBIQUITOUS,
        "When given the same program twice, the emit shall produce the same Verus.": Pattern.EVENT,
        "While the order is paid, the receipts shall keep a receipt for the order.": Pattern.STATE,
        "If a construct has no model, then the emit shall stop with an error.": Pattern.UNWANTED,
        "Where the settings' dry run is enabled, the cli shall not write files.": Pattern.OPTIONAL,
        "While the order is paid, when a refund arrives, the api shall record the refund.": Pattern.COMPLEX,
    }
    for text, pattern in cases.items():
        parsed, problems = ears(text)
        assert parsed is not None and not problems, (text, problems)
        assert parsed.pattern is pattern, text


def test_state_and_feature_clauses_name_a_structure_its_field_and_a_value():
    parsed, _ = ears("While the order's status is paid, the receipts shall keep a receipt for the order.")
    assert (parsed.while_.structure, parsed.while_.field, parsed.while_.value) == ("order", "status", "paid")
    parsed, _ = ears("Where the settings' dry run is enabled, the cli shall not write files.")
    assert (parsed.where.structure, parsed.where.field, parsed.where.value) == ("settings", "dry run", "enabled")
    assert parsed.negated


def test_malformed_statements_say_what_is_wrong():
    assert "ends with a full stop" in ears("The emit shall translate a program")[1][0]
    assert "the main clause" in ears("Emit translates a program.")[1][0]
    assert "is followed by" in ears("If a construct has no model, the emit shall stop.")[1][0]
    assert "starts with a verb" in ears("The emit shall Verus.")[1][0]
    assert "enabled" in ears("Where the settings' dry run is on, the cli shall not write files.")[1][0]


def test_outcomes_follow_minimize_the_measure():
    assert parse_outcome("Minimize the likelihood that a placed order is lost") == ()
    assert parse_outcome("Minimize the time between changing a program and seeing a verdict") == ()
    assert parse_outcome("Maximize the joy") != ()
    assert parse_outcome("Minimize the cost of it") != ()
    assert parse_outcome("Minimize the time between a and") != ()


def test_jobs_start_with_a_verb():
    assert parse_job("Verify that a Mojo program meets its spec", L) == ()
    assert parse_job("A verified program", L) != ()


@verifies("zigdag.core.language#never-raise")
@given(st.text(max_size=200))
def test_parsers_never_raise(text):
    parse_ears(text, L)
    parse_outcome(text)
    parse_job(text, L)


_SUBJECTS = st.sampled_from(["emit", "orders db", "core", "translator names"])
_RESPONSES = st.sampled_from(["translate a program", "keep every order", "stop with an error"])
_CLAUSES = st.sampled_from([
    ("", Pattern.UBIQUITOUS),
    ("When given a program, ", Pattern.EVENT),
    ("While the order is paid, ", Pattern.STATE),
    ("If a construct has no model, then ", Pattern.UNWANTED),
    ("Where the settings' dry run is enabled, ", Pattern.OPTIONAL),
])


@verifies("zigdag.core.language#parse")
@given(_CLAUSES, _SUBJECTS, st.booleans(), _RESPONSES)
def test_every_sentence_the_grammar_allows_parses_back(clause, subject, negated, response):
    opening, pattern = clause
    the = "the" if opening else "The"
    text = f"{opening}{the} {subject} shall {'not ' if negated else ''}{response}."
    parsed, problems = parse_ears(text, L)
    assert parsed is not None and not problems, (text, problems)
    assert (parsed.pattern, parsed.subject, parsed.negated) == (pattern, subject, negated)
