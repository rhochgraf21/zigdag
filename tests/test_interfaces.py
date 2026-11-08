"""The interface checks (DESIGN2 §4.1): shallow components, mode parameters, wide parameters, and abstractions with
one implementation, on a small project whose shapes component another component uses."""

from pathlib import Path

from zigdag import verifies
from zigdag.cli import read_code, read_project
from zigdag.core.checks.run import analyse
from zigdag.core.code import Abstraction
from zigdag.core.findings import Result

SETTINGS = '[settings]\nruleset = 1\n[adapters]\ndefault = "python"\n[adapters.python]\nsource = ["src"]\n'
CUSTOMER = """
draw-boxes:
  job: Draw a box on a page
  performer: Designer
  outcomes:
    wrong-size: Minimize the likelihood that a box is drawn at the wrong size
"""
FUNCTIONAL = """
frs:
  app:
    statements:
      draw: The app shall draw boxes.
  app.shapes:
    serves: [draw-boxes.wrong-size]
    statements:
      measure: The shapes shall measure a box.
  app.cli:
    serves: [draw-boxes.wrong-size]
    statements:
      print: The cli shall print the size of a box.
"""
SHAPES = '''"""Boxes, and what can be measured of them."""
import abc
import enum
from dataclasses import dataclass
from typing import Literal, Protocol


class Unit(enum.Enum):
    """A unit of length."""

    METRE = "m"
    FOOT = "ft"


@dataclass(frozen=True)
class Box:
    """A box on a page."""

    width: int
    height: int


def area(box: Box, rounded: bool) -> int:
    """The area of a box."""
    if rounded:
        return round(box.width * box.height, -1)
    return box.width * box.height


def length(box: Box, unit: Unit) -> float:
    """The width of a box in a unit."""
    match unit:
        case Unit.FOOT:
            return box.width * 3.28
    return float(box.width)


def label(box: Box, loud: bool, style: Literal["plain", "bold"]) -> str:
    """A label for a box; loud and style are passed on, not branched on."""
    return shout(str(box), loud, style)


def shout(text: str, loud: bool, style: str) -> str:
    """The text, louder."""
    return text.upper() if loud else text


def width_of(box: Box) -> int:
    """Only the width."""
    return box.width


def both(box: Box) -> int:
    """Both sides."""
    return box.width + box.height


def same(box: Box) -> Box:
    """The box itself."""
    return box


class Drawer(Protocol):
    """Draws a box."""

    def draw(self, box: Box) -> str: ...


class Plain:
    """Draws a box as text, and has the shape of a Drawer without naming it."""

    def draw(self, box: Box) -> str:
        return f"{box}"


class Store(abc.ABC):
    """Keeps boxes."""

    @abc.abstractmethod
    def keep(self, box: Box) -> None: ...


class Disk(Store):
    """Keeps boxes in a file."""

    def keep(self, box: Box) -> None:
        return None


class Memory(Store):
    """Keeps boxes in a list."""

    def keep(self, box: Box) -> None:
        return None


class Exporter(metaclass=abc.ABCMeta):
    """Writes boxes out; for users to implement."""
'''
CLI = '''"""The command line: one entry point with all the work behind it."""
from app.shapes import Box, Unit, area, both, label, length, same, width_of


def main() -> None:
    """Print what can be measured of a box."""
    box = Box(2, 3)
    print(area(box, True))
    print(length(box, Unit.METRE))
    print(label(box, False, "plain"))
    print(width_of(box), both(box), same(box))
    for side in (box.width, box.height):
        print(side)
    print("done")
'''


def build(tmp_path: Path, process: str | None = None) -> Path:
    files = {"zigdag.toml": SETTINGS, "design/customer.yaml": CUSTOMER, "design/functional.yaml": FUNCTIONAL,
             "src/app/__init__.py": '"""Boxes."""\n', "src/app/shapes.py": SHAPES, "src/app/cli.py": CLI,
             **({"design/process.yaml": process} if process else {})}
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    return tmp_path


def asked(tmp_path: Path, rule: str, process: str | None = None) -> dict[str, str]:
    root = build(tmp_path, process)
    a = analyse(read_project(root), read_code(root))
    assert not any(f.rule == rule and f.result is not Result.QUESTION for f in a.report.findings)
    return {f.about: f.say for f in a.report.findings if f.rule == rule}


@verifies("zigdag.adapters.python#read")
def test_the_adapter_reads_branches_field_reads_and_abstractions(tmp_path):
    code = read_code(build(tmp_path))
    params = {p.name: p for p in code.symbols["app.shapes.area"].signature.params}
    assert params["rounded"].branched_on and not params["box"].branched_on
    assert params["box"].fields_read == ("width", "height")
    narrow = code.symbols["app.shapes.width_of"].signature.params[0]
    assert narrow.fields_read == ("width",) and not narrow.used_whole
    assert code.symbols["app.shapes.same"].signature.params[0].used_whole
    assert code.symbols["app.shapes.Drawer"].abstraction is Abstraction.PROTOCOL
    assert code.symbols["app.shapes.Store"].abstraction is Abstraction.ABSTRACT_BASE
    assert code.symbols["app.shapes.Exporter"].abstraction is Abstraction.ABSTRACT_BASE
    assert code.symbols["app.shapes.Disk"].abstraction is None


@verifies("zigdag.core.analysis.checks#modes")
def test_a_parameter_that_picks_the_behaviour_is_asked_about(tmp_path):
    asks = asked(tmp_path, "no-mode-parameters")
    assert set(asks) == {"app.shapes.area", "app.shapes.length"}  # label passes its flags on; shout is not used
    assert "rounded parameter (bool)" in asks["app.shapes.area"]
    assert "unit parameter (Unit)" in asks["app.shapes.length"]


@verifies("zigdag.core.analysis.checks#narrow")
def test_a_parameter_read_for_one_field_is_asked_about(tmp_path):
    asks = asked(tmp_path, "narrow-parameters")
    assert set(asks) == {"app.shapes.width_of", "app.shapes.length"}  # both reads two fields; same returns the box
    assert "reads only box.width of a Box: it could take the width instead" in asks["app.shapes.width_of"]


@verifies("zigdag.core.analysis.checks#single-implementation")
def test_an_abstraction_with_one_implementation_is_asked_about(tmp_path):
    asks = asked(tmp_path, "no-single-implementations")
    assert set(asks) == {"app.shapes.Drawer"}  # Store has two; Exporter has none, so it may be for users
    assert "a protocol with one implementation, Plain" in asks["app.shapes.Drawer"]


@verifies("zigdag.core.analysis.checks#shallow")
def test_a_component_with_little_code_behind_its_interface_is_asked_about(tmp_path):
    asks = asked(tmp_path, "min-depth")
    assert set(asks) == {"app.shapes"}  # the cli is one name with all its work behind it
    assert "lines each, where 5 are asked for" in asks["app.shapes"]
    tuned = "min-depth:\n  with:\n    ratio: 1\n"
    assert asked(tmp_path, "min-depth", tuned) == {}
