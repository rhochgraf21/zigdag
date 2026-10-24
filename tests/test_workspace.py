from __future__ import annotations

import subprocess

import pytest

from arch import realizes
from arch.change import apply
from arch.change.ops import AddComponent, Remove, Removal
from arch.integrate.workspace import StaleEdit, Workspace
from arch.model.ids import ComponentId, Text
from arch.model.schema import Kind
from tests.conftest import NEED, component


def project(tmp_path):
    for path, text in {"design/needs/n.md": NEED, "design/components/s.md": component(serves="n"),
                       "design/components/s/a.md": component(serves="n"),
                       "design/components/s/a/x.md": component()}.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    return Workspace(tmp_path)


@realizes("arch.integrate.workspace#AC2")
def test_writes_are_all_or_nothing_and_refuse_stale_files(tmp_path):
    ws = project(tmp_path)
    r = apply(ws.design(), [AddComponent(ComponentId("s.b"), Text("Do b"), Text("B"), Text("b's secret"), serves=("n",))])
    (tmp_path / "design/components/s/b.md").write_text("someone else's file")
    with pytest.raises(StaleEdit):
        ws.write(r.design_edits, r.source_edits)
    assert (tmp_path / "design/components/s/b.md").read_text() == "someone else's file"
    (tmp_path / "design/components/s/b.md").unlink()
    ws.write(r.design_edits, r.source_edits)
    assert "s.b" in ws.design().components


def test_deleting_a_subtree_prunes_empty_directories(tmp_path):
    ws = project(tmp_path)
    r = apply(ws.design(), [Remove(Text("s.a"), Kind.COMPONENT, Removal.CASCADE)])
    ws.write(r.design_edits, r.source_edits)
    assert not (tmp_path / "design/components/s/a").exists()
    assert set(ws.design().components) == {"s"}


def test_design_at_a_revision(tmp_path):
    ws = project(tmp_path)
    git = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)  # noqa: E731
    git("init", "-q")
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    (tmp_path / "design/components/s/a/x.md").unlink()
    assert "s.a.x" in ws.design_at("HEAD").components and "s.a.x" not in ws.design().components
