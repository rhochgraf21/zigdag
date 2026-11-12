"""The Terraform adapter: a rendered plan and the source it was rendered from, read into the code model (DESIGN2
§5.3). zigdag never runs Terraform and never contacts a cloud: the project renders the plan, and this reads the file.

It supplies the container level: each resource is a unit, and what resources reference are their dependencies. It
supplies who is granted what, what may reach what, and which settings point at which resource. Its tests are the
runs of `terraform test`, and its diagnostics are what tflint and trivy report.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import deal

from zigdag.adapters.terraform import access
from zigdag.adapters.terraform import tests as tf_tests
from zigdag.adapters.terraform.plan import Plan, Resource, read_plan
from zigdag.adapters.terraform.source import Block, BlockKind, blocks, constant_locals
from zigdag.adapters.terraform.tests import Mode
from zigdag.adapters.terraform.tools import diagnostics
from zigdag.adapters.tools import ToolOutput
from zigdag.core.code import (
    CodeModel,
    Dependency,
    DependencyKind,
    Diagnostic,
    Grant,
    Level,
    Place,
    Qualified,
    Setting,
    Unit,
    UnitKind,
)
from zigdag.core.codec import Unreadable
from zigdag.core.findings import Finding, RecordPath, Result, RuleName, Span, Subject, finding
from zigdag.core.kinds.registry import Part
from zigdag.core.measures import Column, Line, LineCount
from zigdag.core.names import TERRAFORM, Identifier
from zigdag.core.texts import Content, FileText, Say

ADAPTER_RULE = RuleName("terraform")
SUFFIX = ".tf"
_UNLOCATED_SIZE = LineCount(0)  # a resource whose block was not found has no lines of its own to count

# The resource types that run code or store data, and so are containers (DESIGN2 §5.3). Every other resource
# supports one. A project teaches zigdag more with `containers` in [adapters.terraform].
RUNS_CODE = frozenset({
    "aws_ecs_service", "aws_lambda_function", "aws_instance", "aws_autoscaling_group", "aws_eks_cluster",
    "aws_apprunner_service", "aws_elastic_beanstalk_environment", "aws_batch_job_definition",
})
STORES_DATA = frozenset({
    "aws_s3_bucket", "aws_db_instance", "aws_rds_cluster", "aws_dynamodb_table", "aws_sqs_queue", "aws_sns_topic",
    "aws_elasticache_cluster", "aws_elasticache_replication_group", "aws_kinesis_stream", "aws_efs_file_system",
    "aws_opensearch_domain", "aws_redshift_cluster", "aws_docdb_cluster", "aws_msk_cluster",
})
CONTAINER_TYPES = RUNS_CODE | STORES_DATA


@dataclass(frozen=True)
class TerraformFiles:
    """What the shell read for the Terraform adapter."""

    sources: Mapping[RecordPath, FileText]  # every .tf file under the source folders
    root: RecordPath  # the folder of the root module, which the plan was rendered from
    plan: FileText | None  # what `terraform show -json` wrote; None when it has not been rendered
    plan_path: RecordPath  # where the plan is looked for
    containers: frozenset[Identifier] = frozenset()  # resource types the project says are containers too
    tests: Mapping[RecordPath, FileText] = field(default_factory=dict)  # every test file under the source folders
    report: FileText | None = None  # what `terraform test` wrote of its latest run, as JUnit XML
    report_path: RecordPath = RecordPath("")
    mode: Mode = Mode.PLAN  # whether the tests may apply
    tools: tuple[ToolOutput, ...] = ()  # the linter and the security checker the shell ran


def _folder(path: RecordPath) -> RecordPath:
    return RecordPath(path.rpartition("/")[0])


def _located(sources: Mapping[RecordPath, FileText]) -> dict[tuple[RecordPath, BlockKind, Identifier | None,
                                                                   Identifier], tuple[RecordPath, Block]]:
    """Each block the source writes, by its folder and what it declares, with the file it is in."""
    return {(_folder(path), b.kind, b.type, b.name): (path, b)
            for path, text in sorted(sources.items(), reverse=True) for b in blocks(text)}


def _span(path: RecordPath, block: Block) -> Span:
    return Span(path, block.line, Column(1))


def _place(resource: Resource, files: TerraformFiles, located: Mapping) -> tuple[Span, LineCount]:
    """Where a resource is written and how long its block is. One in a module whose source is not here is placed at
    the call of that module, and one whose block cannot be found at all, at the plan."""
    own = located.get((resource.folder, BlockKind.RESOURCE, resource.type, resource.name)) if resource.folder else None
    if own is not None:
        return _span(*own), own[1].size
    if resource.modules:
        call = located.get((files.root, BlockKind.MODULE, None, resource.modules[0]))
        if call is not None:
            return _span(*call), _UNLOCATED_SIZE
    return Span(files.plan_path, Line(1), Column(1)), _UNLOCATED_SIZE


def _made_from(resource: Resource) -> tuple:
    """The resources one is made from: what it references, less what a security group refers to only in its network
    rules. Those say what may reach it, which relates two containers and makes neither part of the other."""
    if resource.type != access.SECURITY_GROUP:
        return resource.references
    otherwise = {r for argument, reached in resource.arguments.items() if argument not in access.CONNECTING
                 for r in reached.resources}
    connecting = {r for argument in access.CONNECTING if argument in resource.arguments
                  for r in resource.arguments[argument].resources}
    return tuple(r for r in resource.references if r in otherwise or r not in connecting)


@dataclass(frozen=True)
class _Read:
    """What is read of a plan with its source."""

    units: Mapping
    dependencies: tuple[Dependency, ...]
    settings: tuple[Setting, ...]
    grants: tuple[Grant, ...]
    unread: tuple[access.Unread, ...]


def _lines(files: TerraformFiles, path: RecordPath, block: Block) -> list[str]:
    return files.sources[path].splitlines()[block.line - 1:block.line - 1 + block.size]


def _read(plan: Plan, files: TerraformFiles) -> _Read:
    located = _located(files.sources)
    containers = CONTAINER_TYPES | files.containers
    units, dependencies, settings = {}, [], []
    written: dict = {}  # each resource whose block was found, with the lines of the block
    for resource in plan.resources:
        span, size = _place(resource, files, located)
        kind = UnitKind.RESOURCE if resource.type in containers else UnitKind.SUPPORT
        units[resource.address] = Unit(resource.address, TERRAFORM, kind, True, span, size, Level.CONTAINER)
        dependencies += [Dependency(Place(resource.address, None), Qualified(target), DependencyKind.REFERENCE, span)
                         for target in _made_from(resource)]
        own = located.get((resource.folder, BlockKind.RESOURCE, resource.type, resource.name))
        if own is not None:
            written[resource.address] = _lines(files, *own)
            beside = frozenset((r.type, r.name) for r in plan.resources if r.modules == resource.modules)
            settings += access.settings(resource, written[resource.address], beside, span)
    spans = {address: unit.span for address, unit in units.items()}
    grants = access.grants(plan, spans, written)
    dependencies += [Dependency(Place(a, None), Qualified(b), DependencyKind.CONNECTION, spans[a])
                     for a, b in access.connections(plan)]
    dependencies += [Dependency(Place(to, None), Qualified(on), DependencyKind.GRANT, spans[to])
                     for to, on in dict.fromkeys((g.to, g.on) for g in grants)]
    return _Read(units, tuple(dependencies), tuple(settings), grants, access.unread(plan, written))


def _unread(read: _Read) -> list[Finding]:
    """A question for each grant on resources written as constants, such as "*". It names no resource here, so
    zigdag cannot say whose access it is, and it must not pass as no access (principle 6)."""
    return [finding(Result.QUESTION, ADAPTER_RULE, Subject(u.by), None, Say(
                f"{u.by} grants {', '.join(u.actions)} on resources it names as text, not by reference: zigdag "
                f"cannot tell which resources here that is"), Content(" ".join(u.actions)))
            for u in read.unread]


def _untraced(plan: Plan, units: Mapping, files: TerraformFiles) -> list[Finding]:
    """A question for each resource that refers to a local value that may refer on. The plan does not spell local
    values out, so what such a resource references through one is not known, and must not pass as nothing
    (principle 6). A local the source gives a plain constant refers to nothing, and is no question."""
    constant: dict[RecordPath, set] = {}
    for path, text in files.sources.items():
        constant.setdefault(_folder(path), set()).update(f"local.{name}" for name in constant_locals(text))
    problems = []
    for r in plan.resources:
        open_ = [u for u in r.untraced if r.folder is None or u not in constant.get(r.folder, ())]
        if open_:
            problems.append(finding(Result.QUESTION, ADAPTER_RULE, Subject(r.address), units[r.address].span, Say(
                f"{r.address} refers to {', '.join(open_)}, which the plan does not spell out: what it "
                f"references through {'it' if len(open_) == 1 else 'them'} was not read")))
    return problems


def _older(plan: Plan, files: TerraformFiles) -> list[Finding]:
    """A thing to do for each folder whose source declares what the plan does not, or the other way round: the plan
    was rendered before the source was changed, so what is read from it is not what is written.

    Only what is declared is compared, a resource or a module call, which is what zigdag reads of the plan. A change
    inside a block that declares nothing new goes unnoticed: zigdag reads text, never the time a file was written,
    so that two runs on the same files find the same."""
    written: dict[RecordPath, tuple[set, set]] = {}
    for path, text in files.sources.items():
        resources, calls = written.setdefault(_folder(path), (set(), set()))
        for block in blocks(text):
            if block.kind is BlockKind.RESOURCE:
                resources.add((block.type, block.name))
            elif block.kind is BlockKind.MODULE:
                calls.add(block.name)
    problems = []
    for declared in plan.declared:
        if declared.folder not in written:
            continue  # no source of it was read, so there is nothing to compare the plan with
        resources, calls = written[declared.folder]
        only_source = sorted(f"{t}.{n}" for t, n in resources - declared.resources) + sorted(
            f"module.{c}" for c in calls - declared.calls)
        only_plan = sorted(f"{t}.{n}" for t, n in declared.resources - resources) + sorted(
            f"module.{c}" for c in declared.calls - calls)
        if only_source or only_plan:
            differs = "; ".join(part for part in (
                f"the source declares {', '.join(only_source)}, which the plan lacks" if only_source else "",
                f"the plan has {', '.join(only_plan)}, which the source no longer declares" if only_plan else "") if part)
            problems.append(finding(Result.TODO, ADAPTER_RULE, Subject(files.plan_path), None, Say(
                f"the plan at {files.plan_path} is older than the source in {declared.folder or 'the project'}: "
                f"{differs}. Render it again"), Content(differs)))
    return problems


def _tests(files: TerraformFiles, units: Mapping) -> tuple[tuple, dict, list[Finding]]:
    """The runs of the test files, their latest results, and what is wrong with them."""
    problems = [finding(Result.BREAKS, ADAPTER_RULE, Subject(tf_tests.test_id(path, run)),
                        Span(path, run.line, Column(1)), Say(
                            f"{tf_tests.test_id(path, run)} would apply: Terraform applies a run unless it says "
                            f"command = plan. Say so in the run, or let the tests apply with test = "
                            f"\"{Mode.APPLY.value}\" in [adapters.terraform]; until then zigdag test leaves the file "
                            f"out"))
                for path, run in tf_tests.applying(files.tests, files.mode)]
    results = tf_tests.read_report(files.report, files.tests) if files.report is not None else {}
    if results is None:
        at = Span(files.report_path, Line(1), Column(1))
        problems.append(finding(Result.QUESTION, ADAPTER_RULE, Subject(files.report_path), at, Say(
            "could not be read, so the tests in it count as no evidence")))
    return tf_tests.read_tests(files.tests, (Qualified(u) for u in units)), results or {}, problems


def _diagnosed(files: TerraformFiles) -> tuple[list[Diagnostic], set[Part], list[Finding]]:
    """What the tools reported, which parts of the model that supplies, and each tool that could not report."""
    reported: list[Diagnostic] = []
    supplied: set[Part] = set()
    failures: list[Finding] = []
    for output in files.tools:
        found, failure = diagnostics(output, files.sources, files.root)
        reported += found
        if failure is None:
            supplied.add(output.tool.diagnosis.part)
        else:
            failures.append(failure)
    return reported, supplied, failures


@deal.ensure(lambda files, result: all(u.adapter == TERRAFORM and u.level is Level.CONTAINER
                                       for u in result.units.values()))
@deal.ensure(lambda files, result: all(d.source.unit in result.units and d.target in result.units
                                       for d in result.dependencies))
@deal.ensure(lambda files, result: bool(result.units) or bool(result.problems) or files.plan is not None)
def read_terraform(files: TerraformFiles) -> CodeModel:
    reported, diagnosed, failures = _diagnosed(files)
    if files.plan is None:
        about = Subject(files.plan_path)
        tests, results, test_problems = _tests(files, {})
        return CodeModel(tests=tests, results=results, reports_read=files.report is not None,
                         diagnostics=tuple(reported), supplied=frozenset(diagnosed),
                         problems=(finding(Result.TODO, ADAPTER_RULE, about, None, Say(
                             f"there is Terraform source in {files.root or 'the project'}, and no rendered plan at "
                             f"{about}: render it (terraform show -json of a plan), so that what is deployed can be "
                             f"read")), *test_problems, *failures))
    plan = read_plan(files.plan, files.root)
    if isinstance(plan, Unreadable):
        at = Span(files.plan_path, Line(1), Column(1))
        return CodeModel(problems=(finding(Result.QUESTION, ADAPTER_RULE, Subject(files.plan_path), at, Say(
            f"could not be read ({plan.say}), so nothing deployed was checked")), *failures))
    read = _read(plan, files)
    tests, results, test_problems = _tests(files, read.units)
    return CodeModel(units=read.units, dependencies=read.dependencies, tests=tests, results=results,
                     reports_read=files.report is not None, diagnostics=tuple(reported),
                     settings=read.settings, grants=read.grants,
                     supplied=frozenset({Part.RECORD, Part.UNITS, Part.DEPENDENCIES, Part.TESTS, Part.PERMISSIONS}
                                        | diagnosed),
                     problems=(*_untraced(plan, read.units, files), *_older(plan, files), *_unread(read),
                               *test_problems, *failures))
