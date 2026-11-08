from zigdag.core.language import quality as q
from zigdag.core.language.lexicons import LexiconName, Lexicons
from zigdag.core.language.sentences import parse_ears

L = Lexicons()


def problems(text, solution_free=False, lexicons=L):
    parsed, found = parse_ears(text, lexicons)
    assert parsed is not None, found
    found = (*q.ears_quality(parsed, lexicons), *(q.named_solutions(parsed, lexicons) if solution_free else ()))
    return {(p.rule, p.exact) for p in found}


def test_a_clean_statement_has_no_problems():
    assert problems("When given a 10,000-line program, the app shall finish translating within 5 s.") == set()


def test_atomic():
    assert (q.ATOMIC, False) in problems("The app shall read the file and write a report.")
    assert (q.ATOMIC, True) in problems("The app shall read the input and/or the cache.")


def test_measurable():
    assert (q.MEASURABLE, False) in problems("The app shall respond fast.")
    assert (q.MEASURABLE, True) in problems("The app shall respond within 5.")
    assert (q.MEASURABLE, False) in problems("The app shall use fewer requests.")
    assert (q.MEASURABLE, False) not in problems("The app shall use fewer requests than the old app.")
    assert (q.MEASURABLE, False) not in problems("The app shall drop each order that no longer exists.")


def test_specific():
    assert (q.SPECIFIC, True) in problems("The app shall keep it.")
    assert (q.SPECIFIC, True) in problems("The app shall retry if possible.")
    assert (q.SPECIFIC, True) in problems("The app shall store items such as orders.")
    assert (q.SPECIFIC, True) in problems("The app shall keep orders that users may change.")


def test_active_and_readable():
    assert (q.ACTIVE, False) in problems("The app shall be notified of each order.")
    assert (q.READABLE, True) in problems("The app shall keep orders (all of them).")
    assert (q.READABLE, True) in problems("The app shall keep orders; and receipts.")


def test_solution_words_only_where_asked_and_never_in_the_subject():
    assert (q.SOLUTION_FREE, False) in problems("The app shall keep orders in a database.", solution_free=True)
    assert (q.SOLUTION_FREE, False) not in problems("The api shall record each order.", solution_free=True)


def test_lexicons_can_be_tuned():
    tuned = L.tuned({LexiconName.VAGUE_WORDS: ((), ("fast",))})
    assert (q.MEASURABLE, False) not in problems("The app shall respond fast.", lexicons=tuned)
