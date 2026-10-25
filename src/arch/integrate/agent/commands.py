"""Abstract operations, spelled as the commands an agent types.

Part of arch.integrate.agent. The only place that knows both the methods' vocabulary and the CLI's.
"""

from __future__ import annotations

from collections.abc import Mapping

from arch.guide.method import AbstractOp
from arch.model.ids import Text

COMMANDS: Mapping[AbstractOp, Text] = {
    AbstractOp.CONTEXT: Text("arch context <component | path[:line]>"),
    AbstractOp.OUTLINE: Text("arch outline [component] [--depth N]"),
    AbstractOp.MATRIX: Text("arch matrix <component>"),
    AbstractOp.OBSERVED_MATRIX: Text("arch matrix <component> --observed"),
    AbstractOp.PLAN: Text("arch plan <component>..."),
    AbstractOp.CHECK: Text("arch check"),
    AbstractOp.NEXT: Text("arch next [component]"),
    AbstractOp.DIFF: Text("arch diff [revision]"),
    AbstractOp.ADD_NEED: Text('arch add need <id> --statement "..." --stakeholder "..." --signal "..."'),
    AbstractOp.ADD_COMPONENT: Text('arch add component <id> --realizes "..." --solution "..." --hides "..." '
                                   '[--uses a,b] [--serves need] [--criterion "..."]'),
    AbstractOp.ADD_CRITERION: Text('arch add criterion <component> "When ..., the ... shall ..."'),
    AbstractOp.ADD_DECISION: Text('arch add decision <component> --title "..." --chose "..." --over "..." --because "..."'),
    AbstractOp.SET_FIELD: Text('arch set <component | need> <field> "<value>"'),
    AbstractOp.LINK: Text("arch link <component> uses|exports|serves <target>"),
    AbstractOp.UNLINK: Text("arch unlink <component> uses|exports|serves <target>"),
    AbstractOp.MOVE: Text("arch move <component> <new-id>"),
    AbstractOp.SPLIT: Text('arch split <component>#AC2,AC3 --into <new-id> --realizes "..." --solution "..." --hides "..."'),
    AbstractOp.REMOVE: Text("arch remove component|need <id> [--cascade]"),
    AbstractOp.CRITIQUE: Text("arch critique [component] [--request | --record answer.json]"),
    AbstractOp.RAISE: Text('arch raise defect|question|idea <subject> "..." --station <station> --evidence "..." --by <you>'),
    AbstractOp.RESPOND: Text('arch respond fixed|accepted|declined|answered "<reason>" <ref...> --by <you>'),
}
