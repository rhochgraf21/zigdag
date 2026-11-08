from zigdag.core.record.tree import Map, Seq, Text, read_tree
from zigdag import verifies


def tree(text):
    node, problems = read_tree("design/x.yaml", text)
    return node, [p.say for p in problems]


@verifies("zigdag.core.record#text-only")
def test_every_value_is_text():
    node, _ = tree("a: no\nb: 3\nc:\n")
    assert [(e.key, e.value.text) for e in node] == [("a", "no"), ("b", "3"), ("c", "")]


@verifies("zigdag.core.record#read")
def test_anchors_aliases_tags_and_duplicates_are_refused():
    assert any("anchors" in s for s in tree("a: &x 1\nb: *x\n")[1])
    assert any("tags" in s for s in tree("a: !thing 1\n")[1])
    assert any("duplicate" in s for s in tree("a: 1\na: 2\n")[1])
    assert tree("a: [1\n")[0] is None


@verifies("zigdag.core.record#read")
def test_comments_become_reasons_and_spans_are_kept():
    node, _ = tree("rule:  # beside\n  x: 1\n# above\nother:\n  except:\n    - code.name  # why\n")
    rule, other = node.entries
    assert rule.reason == "beside" and other.reason == "above"
    item = other.value.get("except").value.items[0]
    assert isinstance(item, Text) and item.reason == "why" and item.span.line == 6
    assert isinstance(other.value, Map) and isinstance(other.value.get("except").value, Seq)
