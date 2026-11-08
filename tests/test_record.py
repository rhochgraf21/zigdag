from conftest import FUNCTIONAL, project, rules, says

from zigdag.core.findings import Result
from zigdag.core.kinds.params import ParamType
from zigdag.core.kinds.registry import BUILT_IN_KINDS
from zigdag.core.language.lexicons import Lexicons
from zigdag.core.language.quality import ears_quality
from zigdag.core.language.sentences import parse_ears
from zigdag import verifies


@verifies("zigdag.core.analysis.checks#report")
def test_a_minimal_record_holds():
    report = project()
    assert not report.breaks, says(report, Result.BREAKS)
    assert rules(report, Result.QUESTION) == {"code-not-read"}


def test_an_empty_project_has_things_to_do():
    report = project(settings=None, customer=None, functional=None)
    assert not report.breaks
    assert {"settings", "customer", "root"} <= rules(report, Result.TODO)


def test_every_fr_has_its_parent_and_there_is_one_root():
    deep = project(functional=FUNCTIONAL + """
  app.core.emit.deep:
    statements:
      x: The deep shall translate a program.
""")
    assert "parents" in rules(deep, Result.BREAKS)
    two_roots = project(functional=FUNCTIONAL + """
  other:
    statements:
      x: The other shall translate a program.
""")
    assert "root" in rules(two_roots, Result.BREAKS)


def test_serves_belongs_only_on_the_first_level():
    report = project(functional="""
frs:
  app:
    serves: [verify-programs.wrong-proof-passes]
    statements:
      run: The app shall translate a program.
  app.core:
    statements:
      translate: The core shall translate a program.
""")
    assert any("belongs only on the first level" in s for s in says(report, Result.BREAKS))
    assert any("say which outcomes this FR serves" in s for s in says(report, Result.TODO))


def test_unknown_outcomes_and_frs_break():
    report = project(functional=FUNCTIONAL.replace("wrong-proof-passes", "no-such") + """
constraints:
  pure:
    on: app.nowhere
    serves: [verify-programs.wrong-proof-passes]
    check: effects
    with:
      allow: []
""")
    found = says(report, Result.BREAKS)
    assert 'no outcome "verify-programs.no-such"' in found
    assert 'no FR "app.nowhere"' in found


def test_an_fr_has_exactly_one_function():
    report = project(functional="""
frs:
  app:
    statements:
      a: The app shall translate a program.
      b: The app shall check a program.
  app.core:
    serves: [verify-programs.wrong-proof-passes]
    statements:
      a: When asked, the core shall translate a program.
""")
    assert sum(f.rule == "ears.function" for f in report.of_result(Result.BREAKS)) == 2


def test_the_subject_is_the_fr_name():
    report = project(functional=FUNCTIONAL.replace("The core shall", "The engine shall"))
    assert "ears.subject" in rules(report, Result.BREAKS)


def test_check_kinds_and_parameters_are_validated():
    report = project(functional=FUNCTIONAL + """
constraints:
  a:
    on: app
    serves: [verify-programs.wrong-proof-passes]
    check: no-such-kind
  b:
    on: app
    serves: [verify-programs.wrong-proof-passes]
    check: effects
    with:
      allow: [read, teleport]
  c:
    on: app
    serves: [verify-programs.wrong-proof-passes]
    check: effects
""")
    found = " | ".join(says(report, Result.BREAKS))
    assert 'no check kind "no-such-kind"' in found
    assert "unknown effects: teleport" in found
    assert '"allow" must be given' in found


def test_resource_and_custom_effects_are_effects():
    settings = '[settings]\nruleset = 1\n[effects."verus.run"]\ndescription = "x"\ncalls = ["a.b"]\n'
    report = project(settings=settings, functional=FUNCTIONAL + """
constraints:
  a:
    on: app
    serves: [verify-programs.wrong-proof-passes]
    check: effects
    with:
      allow: [verus.run, app.core.write]
""")
    assert not report.breaks, says(report, Result.BREAKS)


def test_built_ins_are_tuned_in_their_own_domain_and_always_on_ones_stay_on():
    report = project(
        functional=FUNCTIONAL + "constraints:\n  max-lines:\n    with:\n      function: 10\n"
                                "  encapsulation:\n    off: true\n",
        process="max-lines:\n  with:\n    function: ten\n",
    )
    found = " | ".join(says(report, Result.BREAKS))
    assert "tune it in design/process.yaml" in found
    assert "encapsulation is always on" in found
    assert "is not a whole number" in found


def test_max_children():
    children = "".join(f"""
  app.core.c{i}:
    statements:
      x: The c{i} shall translate a program.
""" for i in range(10))
    report = project(functional=FUNCTIONAL + children)
    assert "max-children" in rules(report, Result.BREAKS)
    tuned = project(functional=FUNCTIONAL + children, process="max-children:\n  with:\n    count: 12\n")
    assert "max-children" not in rules(tuned, Result.BREAKS)


def test_design_files_are_named_by_domain_and_names_are_defined_once():
    from zigdag.core.checks.run import ProjectFiles, check

    report = check(ProjectFiles(None, {
        "design/notes.yaml": "a: b\n",
        "design/functional.yaml": FUNCTIONAL,
        "design/functional/more.yaml": "frs:\n  app.core:\n    statements:\n      x: The core shall translate a program.\n",
    }))
    assert {"design-files", "defined-once"} <= rules(report, Result.BREAKS)


@verifies("zigdag.core.vocabulary.kinds#define")
def test_every_rendered_sentence_is_valid_ears():
    samples = {ParamType.EFFECTS: ("read", "network"), ParamType.NAMES: ("app.core.models", "lark"),
               ParamType.COUNT: 7, ParamType.RATIO: 2.5, ParamType.TEXT: "x"}
    lexicons = Lexicons()
    for kind in BUILT_IN_KINDS.values():
        params = {n: (s.default if s.default is not None else samples[s.type]) for n, s in kind.params.items()}
        for excepted in ((), ("emit.translator_names",)):
            text = kind.sentence("core", params, excepted)
            parsed, problems = parse_ears(text, lexicons)
            assert parsed is not None and not problems, (kind.name, text, problems)
            exact = [p.say for p in ears_quality(parsed, lexicons) if p.exact]
            assert not exact, (kind.name, text, exact)
