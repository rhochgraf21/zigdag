from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from arch import realizes
from arch.model import codec
from arch.model.schema import Component, DesignPath
from tests.conftest import component


@realizes("arch.model.codec#AC5")
def test_ids_come_from_paths():
    assert codec.node_id(DesignPath("components/arch/model/schema.md")) == "arch.model.schema"
    assert codec.node_id(DesignPath("components/arch.md")) == "arch"
    assert codec.node_id(DesignPath("needs/understand-system.md")) == "understand-system"
    assert codec.node_id(DesignPath("needs/nested/x.md")) is None
    assert codec.node_id(DesignPath("README.md")) is None


@realizes("arch.model.schema#AC4")
def test_criteria_parsed_with_ids_and_lines():
    node, issues = codec.parse(DesignPath("components/s/a.md"), component(criteria=2))
    assert not issues and isinstance(node, Component)
    assert [c.id for c in node.criteria] == ["s.a#AC1", "s.a#AC2"]
    assert [c.location.line for c in node.criteria] == [9, 10]  # after 7 frontmatter lines and a heading


@realizes("arch.model.schema#AC2")
def test_bad_fields_become_issues():
    text = component().replace("status: specified", "status: done\ncolour: blue")
    node, issues = codec.parse(DesignPath("components/a.md"), text)
    assert node is None
    assert {i.field for i in issues} == {"status", "colour"}


@realizes("arch.model.codec#AC3")
def test_yaml_errors_report_a_line():
    _, issues = codec.parse(DesignPath("components/a.md"), "---\nkind: component\nuses: [a, \n---\n")
    assert issues and issues[0].message.startswith("invalid YAML") and issues[0].location.line >= 2


@realizes("arch.model.schema#AC2")
@given(st.text())
def test_parsing_never_raises(text):
    codec.parse(DesignPath("components/a.md"), text)
    codec.parse(DesignPath("components/a.md"), "---\n" + text + "\n---\n")
