"""The Terraform adapter: a rendered plan and its source, read into the code model, and placed by the record."""

from __future__ import annotations

import json

from zigdag import verifies
from zigdag.adapters.adapter import Presence
from zigdag.adapters.known import adapters
from zigdag.adapters.terraform import TerraformFiles, read_terraform
from zigdag.adapters.terraform.adapter import TerraformAdapter
from zigdag.adapters.terraform.plan import read_plan
from zigdag.adapters.sarif import read_sarif
from zigdag.adapters.python import PythonFiles, read_python
from zigdag.adapters.terraform import access, policy_text
from zigdag.adapters.terraform import tests as tf_tests
from zigdag.adapters.terraform.source import blocks
from zigdag.adapters.terraform.tests import Mode
from zigdag.adapters.terraform.tools import TFLINT, TRIVY, diagnostics
from zigdag.adapters.tools import ToolOutput, Started, not_started
from zigdag.core.code import Diagnosis, Outcome, Severity, ToolName
from zigdag.core.texts import ToolText
from zigdag.cli import plans
from zigdag.core.code import CodeModel, DependencyKind, Level, ResourceAccess, Unit, UnitKind, joined
from zigdag.core.codec import Unreadable
from zigdag.core.findings import Result, Span
from zigdag.core.names import PYTHON, TERRAFORM
from zigdag.core.settings import read_settings

SETTINGS = ('[settings]\nruleset = 1\n[adapters]\ndefault = "python"\n[adapters.python]\nsource = ["src"]\n'
            '[adapters.terraform]\nsource = "infra"\n')
MAIN_TF = '''resource "aws_s3_bucket" "receipts" {
  bucket = "shop-receipts"
}

resource "aws_iam_role" "api" {
  assume_role_policy = <<EOT
{ "Statement": [{ "Effect": "Allow" }] }
EOT
}

resource "aws_iam_role_policy" "api_receipts" {
  role   = aws_iam_role.api.id
  policy = jsonencode({ Resource = aws_s3_bucket.receipts.arn })
}

resource "aws_ecs_service" "api" {
  task_definition = aws_iam_role.api.arn  # stands in for a task definition
}

resource "aws_cloudwatch_log_group" "orphan" {
  name = "nobody"
}
'''
CUSTOMER = """
buy:
  job: Buy a product
  performer: Shopper
  outcomes:
    lost-order: Minimize the likelihood that a placed order is lost
"""
FUNCTIONAL = """
frs:
  shop:
    statements:
      sell: The shop shall take orders for products from shoppers.
  shop.api:
    serves: [buy.lost-order]
    statements:
      record: The api shall record each placed order.
  shop.receipts:
    serves: [buy.lost-order]
    statements:
      keep: The receipts shall keep a receipt for each placed order.
"""
PHYSICAL = """
shop.api: [terraform:aws_ecs_service.api, python:shop.api]
shop.receipts: [terraform:aws_s3_bucket.receipts]
"""


def resource(type_: str, name: str, **references: list[str]) -> dict:
    """A resource as a plan's configuration writes it, each argument given by what it refers to."""
    return {"address": f"{type_}.{name}", "mode": "managed", "type": type_, "name": name,
            "expressions": {argument: {"references": refs} for argument, refs in references.items()}}


def plan_of(root_module: dict) -> str:
    return json.dumps({"format_version": "1.2", "configuration": {"root_module": root_module}})


PLAN = plan_of({"resources": [
    resource("aws_s3_bucket", "receipts"),
    resource("aws_iam_role", "api"),
    resource("aws_iam_role_policy", "api_receipts", role=["aws_iam_role.api.id", "aws_iam_role.api"],
             policy=["aws_s3_bucket.receipts.arn", "aws_s3_bucket.receipts"]),
    resource("aws_ecs_service", "api", task_definition=["aws_iam_role.api.arn", "aws_iam_role.api"]),
    resource("aws_cloudwatch_log_group", "orphan"),
]})
FILES = {"zigdag.toml": SETTINGS, "design/customer.yaml": CUSTOMER, "design/functional.yaml": FUNCTIONAL,
         "design/physical.yaml": PHYSICAL, "infra/main.tf": MAIN_TF, ".zigdag/plan.json": PLAN,
         "src/shop/__init__.py": '"""The shop."""\n', "src/shop/api.py": '"""The api."""\n'}


def said(analysis, rule: str, result: Result = Result.BREAKS) -> list[str]:
    return [f.say for f in analysis.report.of_result(result) if f.rule == rule]


@verifies("zigdag.adapters.terraform#read")
def test_each_resource_of_a_plan_is_a_container_level_unit_with_what_it_references():
    model = read_terraform(TerraformFiles({"infra/main.tf": MAIN_TF}, "infra", PLAN, ".zigdag/plan.json"))
    assert {path: unit.kind for path, unit in model.units.items()} == {
        "aws_s3_bucket.receipts": UnitKind.RESOURCE, "aws_ecs_service.api": UnitKind.RESOURCE,  # run code, store data
        "aws_iam_role.api": UnitKind.SUPPORT, "aws_iam_role_policy.api_receipts": UnitKind.SUPPORT,
        "aws_cloudwatch_log_group.orphan": UnitKind.SUPPORT}
    assert all(unit.adapter == TERRAFORM and unit.level is Level.CONTAINER for unit in model.units.values())
    assert sorted((str(d.source), d.target) for d in model.dependencies if d.kind is DependencyKind.REFERENCE) == [
        ("aws_ecs_service.api", "aws_iam_role.api"), ("aws_iam_role_policy.api_receipts", "aws_iam_role.api"),
        ("aws_iam_role_policy.api_receipts", "aws_s3_bucket.receipts")]
    taught = TerraformFiles({}, "infra", PLAN, ".zigdag/plan.json", frozenset({"aws_cloudwatch_log_group"}))
    assert read_terraform(taught).units["aws_cloudwatch_log_group.orphan"].kind is UnitKind.RESOURCE


@verifies("zigdag.adapters.terraform#read")
def test_references_are_followed_through_a_modules_variables_and_outputs():
    network = {"resources": [resource("aws_security_group", "db", vpc_id=["var.vpc"])],
               "outputs": {"group": {"expression": {"references": ["aws_security_group.db.id", "aws_security_group.db"]}}}}
    text = plan_of({
        "resources": [resource("aws_vpc", "main"),
                      resource("aws_db_instance", "orders", groups=["module.net.group", "module.net"]),
                      {"address": "data.aws_region.here", "mode": "data", "type": "aws_region", "name": "here"}],
        "module_calls": {"net": {"source": "./net", "module": network,
                                 "expressions": {"vpc": {"references": ["aws_vpc.main.id", "aws_vpc.main"]}}}}})
    read = read_plan(text, "infra")
    found = {r.address: r for r in read.resources}
    assert set(found) == {"aws_vpc.main", "aws_db_instance.orders", "module.net.aws_security_group.db"}  # no data source
    assert found["aws_db_instance.orders"].references == ("module.net.aws_security_group.db",)  # in through an output
    assert found["module.net.aws_security_group.db"].references == ("aws_vpc.main",)  # out through a variable
    assert found["module.net.aws_security_group.db"].folder == "infra/net"


@verifies("zigdag.adapters.terraform#read")
def test_a_plan_that_does_not_read_as_terraform_writes_it_is_refused_whole():
    assert isinstance(read_plan("{", "infra"), Unreadable)
    assert isinstance(read_plan('{"format_version": "2.0"}', "infra"), Unreadable)
    nameless = plan_of({"resources": [{"mode": "managed", "type": "aws_s3_bucket"}]})
    assert isinstance(read_plan(nameless, "infra"), Unreadable)
    model = read_terraform(TerraformFiles({}, "infra", "{", ".zigdag/plan.json"))
    assert not model.units and [p.result for p in model.problems] == [Result.QUESTION]


@verifies("zigdag.adapters.terraform#locate")
def test_a_resource_is_placed_at_its_block_whatever_braces_its_text_holds():
    found = {(b.type, b.name): (b.line, b.size) for b in blocks(MAIN_TF)}
    assert found[("aws_s3_bucket", "receipts")] == (1, 3)
    assert found[("aws_iam_role", "api")] == (5, 5)  # the heredoc's braces are text, not the block's
    assert found[("aws_iam_role_policy", "api_receipts")] == (11, 4)
    model = read_terraform(TerraformFiles({"infra/main.tf": MAIN_TF}, "infra", PLAN, ".zigdag/plan.json"))
    role = model.units["aws_iam_role.api"]
    assert (str(role.span), role.size) == ("infra/main.tf:5:1", 5)
    unwritten = read_terraform(TerraformFiles({}, "infra", PLAN, ".zigdag/plan.json")).units["aws_iam_role.api"]
    assert unwritten.span.path == ".zigdag/plan.json"  # a resource whose block is not found is placed at the plan


@verifies("zigdag.adapters.terraform#unrendered")
def test_source_without_a_rendered_plan_is_a_thing_to_do():
    model = read_terraform(TerraformFiles({"infra/main.tf": MAIN_TF}, "infra", None, ".zigdag/plan.json"))
    assert not model.units and not model.supplied
    (problem,) = model.problems
    assert problem.result is Result.TODO and ".zigdag/plan.json" in problem.say


@verifies("zigdag.adapters.terraform#untraced")
def test_a_reference_through_a_local_value_is_a_question_not_nothing():
    text = plan_of({"resources": [resource("aws_s3_bucket", "site", bucket=["local.name"])]})
    (problem,) = read_terraform(TerraformFiles({}, "infra", text, ".zigdag/plan.json")).problems
    assert problem.result is Result.QUESTION and "local.name" in problem.say
    refers = 'locals {\n  name = aws_s3_bucket.other.bucket\n}\nresource "aws_s3_bucket" "site" {\n}\n'
    (problem,) = read_terraform(TerraformFiles({"infra/main.tf": refers}, "infra", text, ".zigdag/plan.json")).problems
    assert problem.result is Result.QUESTION  # the local refers on, and the plan does not say to what
    for constant in ('"shop-site"', "3", "true"):  # a local that is a plain constant refers to nothing
        plain = f'locals {{\n  name = {constant}\n}}\nresource "aws_s3_bucket" "site" {{\n}}\n'
        assert not read_terraform(TerraformFiles({"infra/main.tf": plain}, "infra", text, ".zigdag/plan.json")).problems
    built = 'locals {\n  name = "shop-${var.stage}"\n}\nresource "aws_s3_bucket" "site" {\n}\n'
    (problem,) = read_terraform(TerraformFiles({"infra/main.tf": built}, "infra", text, ".zigdag/plan.json")).problems
    assert problem.result is Result.QUESTION  # a text built from an expression may refer to anything


@verifies("zigdag.adapters.terraform.terraform_adapter#choose")
def test_the_adapter_is_there_only_when_configured_and_wants_its_source_and_its_plan():
    plain, _ = read_settings("[settings]\nruleset = 1\n")
    assert TerraformAdapter.of(plain) is None and [a.name for a in adapters(plain, Presence.ABSENT)] == [PYTHON]
    settings, problems = read_settings(SETTINGS + 'plan = "out/plan.json"\n')
    assert not problems
    terraform = TerraformAdapter.of(settings)
    assert [a.name for a in adapters(settings, Presence.ABSENT)] == [PYTHON, TERRAFORM]
    assert (terraform.root, terraform.plan) == ("infra", "out/plan.json") and "out/plan.json" in terraform.files
    assert terraform.wants("infra/net/main.tf") and terraform.wants("out/plan.json")
    assert terraform.wants("infra/tests/site.tftest.hcl") and not terraform.is_source("infra/tests/site.tftest.hcl")
    assert not terraform.wants("src/main.tf") and not terraform.wants("infra/readme.md")
    assert terraform.read({"src/shop/api.py": ""}) is None  # nothing of its kind here
    assert terraform.test_run({}, ()) is None and terraform.profiled_tests(()) is None


@verifies("zigdag.adapters#known", "zigdag.adapters.terraform#read")
def test_a_container_and_the_code_deployed_in_it_are_joined_by_the_record():
    analysis = plans.analysis(FILES)
    assert analysis.code.adapters == {PYTHON, TERRAFORM}
    tree = analysis.tree
    assert tree.dps["shop.api"].level is Level.CONTAINER and tree.dps["shop.receipts"].level is Level.CONTAINER
    assert tree.unit_owner["aws_ecs_service.api"] == tree.unit_owner["shop.api"] == "shop.api"
    assert not said(analysis, "placement")


@verifies("zigdag.core.analysis.resolve#supporting")
def test_a_supporting_resource_belongs_to_the_container_it_supports():
    analysis = plans.analysis(FILES)
    owner = analysis.tree.unit_owner
    assert owner["aws_iam_role.api"] == "shop.api"  # the service references it
    assert owner["aws_iam_role_policy.api_receipts"] == "shop"  # it points at two containers' resources: the system's
    assert "aws_cloudwatch_log_group.orphan" not in owner  # nothing leads to it
    assert said(analysis, "coverage") == ["aws_cloudwatch_log_group.orphan belongs to no design parameter: give it an "
                                          "FR, or place it in physical.yaml"]
    assert not said(analysis, "designed-modules")  # a supporting resource needs no name of its own in the design


@verifies("zigdag.core.analysis.resolve#own-adapter")
def test_a_code_name_names_only_its_own_adapters_code():
    physical = PHYSICAL.replace("terraform:aws_s3_bucket.receipts", "terraform:shop.api")
    analysis = plans.analysis({**FILES, "design/physical.yaml": physical})
    assert 'no resource "shop.api" in the code' in said(analysis, "placement")


@verifies("zigdag.core.code.model#joined", "zigdag.core.code.model#same-name")
def test_two_adapters_units_of_one_name_break_instead_of_being_read_as_one():
    def model(adapter: str) -> CodeModel:
        return CodeModel(units={"orders": Unit("orders", adapter, UnitKind.MODULE, True, Span("a", 1, 1), 1)})

    assert joined([model(PYTHON)]) == model(PYTHON)
    (problem,) = joined([model(PYTHON), model("sql")]).problems
    assert problem.result is Result.BREAKS and "both have code named orders" in problem.say


TESTS_TF = '''# verifies: shop.receipts#keep
run "receipts_are_kept" {
  command = plan

  assert {
    condition     = aws_s3_bucket.receipts.bucket == "shop-receipts"
    error_message = "command = apply would be wrong here"  # a text, not the run's command
  }
}

run "service_starts" {
  # verifies: shop.api#record, shop#sell
  assert {
    condition = true
  }
}
'''
JUNIT = '''<?xml version="1.0" encoding="UTF-8"?>
<testsuites><testsuite name="tests/site.tftest.hcl" tests="2" failures="1">
  <testcase name="receipts_are_kept" classname="tests/site.tftest.hcl"></testcase>
  <testcase name="service_starts" classname="tests/site.tftest.hcl"><failure message="no"></failure></testcase>
</testsuite></testsuites>'''
TEST_FILE = "infra/tests/site.tftest.hcl"


@verifies("zigdag.adapters.terraform#tests")
def test_each_run_of_a_test_file_is_a_test_linked_by_its_comment_with_its_latest_result():
    tests = {t.id: t for t in tf_tests.read_tests({TEST_FILE: TESTS_TF}, ["aws_s3_bucket.receipts"])}
    kept, starts = tests[f"{TEST_FILE}::receipts_are_kept"], tests[f"{TEST_FILE}::service_starts"]
    assert [link.target for link in kept.links] == ["shop.receipts#keep"]  # the comment directly above the run
    assert [link.target for link in starts.links] == ["shop.api#record", "shop#sell"]  # and one inside it
    assert kept.imports == ("aws_s3_bucket.receipts",) and str(starts.span) == f"{TEST_FILE}:11:1"
    results = tf_tests.read_report(JUNIT, [TEST_FILE])  # the report names the file from the root module's folder
    assert results == {f"{TEST_FILE}::receipts_are_kept": Outcome.PASSED, f"{TEST_FILE}::service_starts": Outcome.FAILED}
    assert tf_tests.read_report("<not xml", [TEST_FILE]) is None


@verifies("zigdag.adapters.terraform#plan-only")
def test_a_run_that_would_apply_breaks_and_its_file_is_left_out_unless_the_project_lets_tests_apply():
    files = {TEST_FILE: TESTS_TF, "infra/tests/plans.tftest.hcl": 'run "only_plans" {\n  command = plan\n}\n'}
    assert [(path, run.name) for path, run in tf_tests.applying(files, Mode.PLAN)] == [(TEST_FILE, "service_starts")]
    assert tf_tests.runnable(files, Mode.PLAN) == ("infra/tests/plans.tftest.hcl",)
    assert not tf_tests.applying(files, Mode.APPLY) and len(tf_tests.runnable(files, Mode.APPLY)) == 2
    model = read_terraform(TerraformFiles({}, "infra", PLAN, ".zigdag/plan.json", tests=files))
    (problem,) = model.problems
    assert problem.result is Result.BREAKS and "service_starts would apply" in problem.say
    settings, _ = read_settings(SETTINGS + 'terraform = "tofu"\n')
    run = TerraformAdapter.of(settings).test_run(files, ("-k", "ignored"))
    assert not run.watched and run.command == (
        "tofu", "-chdir=infra", "test", "-junit-xml=../.zigdag/terraform.junit", "-filter=tests/plans.tftest.hcl")
    allowed, _ = read_settings(SETTINGS + 'test = "apply"\n')
    assert len([a for a in TerraformAdapter.of(allowed).test_run(files, ()).command if a.startswith("-filter=")]) == 2
    assert TerraformAdapter.of(settings).test_run({TEST_FILE: TESTS_TF}, ()) is None  # no file may run


@verifies("zigdag.adapters.terraform#tests")
def test_a_passing_run_is_evidence_for_the_statement_it_verifies():
    files = {**FILES, "infra/tests/site.tftest.hcl": TESTS_TF.replace("shop.api#record, shop#sell", "shop.api#record")
             .replace("  assert {\n    condition = true", "  command = plan\n  assert {\n    condition = true"),
             ".zigdag/terraform.junit": JUNIT}
    analysis = plans.analysis(files)
    evidence = {f.about: f.result for f in analysis.report.findings if f.rule == "evidence"}
    assert "shop.receipts#keep" not in evidence  # verified by a run that passed
    assert evidence["shop.api#record"] is Result.BREAKS  # its run failed
    assert evidence["shop#sell"] is Result.TODO  # nothing verifies it


@verifies("zigdag.adapters.terraform#older")
def test_a_plan_that_lacks_what_the_source_declares_is_out_of_date():
    newer = MAIN_TF + '\nresource "aws_sqs_queue" "orders" {\n}\n\nmodule "net" {\n  source = "./net"\n}\n'
    model = read_terraform(TerraformFiles({"infra/main.tf": newer}, "infra", PLAN, ".zigdag/plan.json"))
    (problem,) = model.problems
    assert problem.result is Result.TODO and "aws_sqs_queue.orders, module.net, which the plan lacks" in problem.say
    fewer = MAIN_TF.replace('resource "aws_cloudwatch_log_group" "orphan" {\n  name = "nobody"\n}\n', "")
    (problem,) = read_terraform(TerraformFiles({"infra/main.tf": fewer}, "infra", PLAN, ".zigdag/plan.json")).problems
    assert "the plan has aws_cloudwatch_log_group.orphan, which the source no longer declares" in problem.say
    assert not read_terraform(TerraformFiles({"infra/main.tf": MAIN_TF}, "infra", PLAN, ".zigdag/plan.json")).problems


SARIF = json.dumps({"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "tflint"}}, "results": [
    {"ruleId": "terraform_unused_declarations", "level": "warning", "message": {"text": "variable is unused"},
     "locations": [{"physicalLocation": {"artifactLocation": {"uri": "main.tf"},
                                         "region": {"startLine": 6, "startColumn": 3}}}]},
    {"ruleId": "AVD-AWS-0086", "level": "error", "message": {"text": "bucket is public"},
     "locations": [{"physicalLocation": {"artifactLocation": {"uri": "file:///ci/checkout/infra/main.tf"}}}]}]}]})


@verifies("zigdag.adapters#sarif")
def test_a_sarif_report_is_read_whole_or_refused_whole():
    unused, public = read_sarif(ToolText(SARIF), Diagnosis.LINT, ToolName("tflint"))
    assert (unused.code, unused.say, str(unused.span), unused.severity) == (
        "terraform_unused_declarations", "variable is unused", "main.tf:6:3", Severity.WARNING)
    assert public.severity is Severity.ERROR and public.span.line == 1  # a result with no region is at the first line
    assert read_sarif(ToolText('{"runs": []}'), Diagnosis.LINT, ToolName("tflint")) == ()
    assert isinstance(read_sarif(ToolText("{"), Diagnosis.LINT, ToolName("tflint")), Unreadable)
    assert isinstance(read_sarif(ToolText("[]"), Diagnosis.LINT, ToolName("tflint")), Unreadable)
    nowhere = '{"runs": [{"results": [{"ruleId": "x", "message": {"text": "y"}}]}]}'
    assert isinstance(read_sarif(ToolText(nowhere), Diagnosis.LINT, ToolName("tflint")), Unreadable)


@verifies("zigdag.adapters.terraform#tools")
def test_tflint_and_trivy_run_on_the_root_module_and_report_at_the_source_file_they_mean():
    settings, _ = read_settings(SETTINGS + 'tflint = "docker run tflint"\n')
    terraform = TerraformAdapter.of(settings)
    source = {"infra/main.tf": MAIN_TF}
    assert terraform.tool_runs({}, (Diagnosis.LINT,)) == () and terraform.tool_runs(source, (Diagnosis.TYPES,)) == ()
    lint, security = terraform.tool_runs(source, (Diagnosis.LINT, Diagnosis.SECURITY))
    assert lint.command == ("docker", "run", "tflint", "--format=sarif", "--force", "--chdir=infra")
    assert security.command == ("trivy", "config", "--format=sarif", "--quiet", "infra")
    reported, failure = diagnostics(ToolOutput(TFLINT, Started.STARTED, out=ToolText(SARIF)), source, "infra")
    assert failure is None and [d.span.path for d in reported] == ["infra/main.tf", "infra/main.tf"]
    form = "Artifact: main.tf\\nType: terraform\\nSeverity: HIGH\\nMessage: Bucket is public.\\nLink: [x](https://x)"
    trivy = SARIF.replace("variable is unused", form).replace('"uri": "main.tf"', '"uri": "net/main.tf"')
    both = {**source, "infra/net/main.tf": ""}  # trivy names a file from the folder it was given
    (said_, _), _ = diagnostics(ToolOutput(TRIVY, Started.STARTED, out=ToolText(trivy)), both, "infra")
    assert (said_.say, said_.span.path) == ("Bucket is public.", "infra/net/main.tf")
    assert "trivy could not be started" in diagnostics(not_started(TRIVY), source, "infra")[1].say
    model = terraform.read({**source, ".zigdag/plan.json": PLAN}, (ToolOutput(TFLINT, Started.STARTED, out=ToolText(SARIF)),))
    assert len(model.diagnostics) == 2 and Diagnosis.LINT.part in model.supplied
    assert model.code_at(model.diagnostics[0].span) == "aws_iam_role.api"  # the resource whose block line 6 is in


def document(name: str, *statements: tuple[list[str], list[str]]) -> dict:
    """A policy document as a plan's configuration writes it: each statement's actions, and what its resources
    refer to."""
    return {"address": f"data.aws_iam_policy_document.{name}", "mode": "data", "type": "aws_iam_policy_document",
            "name": name, "expressions": {"statement": [
                {"actions": {"constant_value": actions},
                 "resources": {"references": on} if on else {"constant_value": ["*"]}} for actions, on in statements]}}


LAMBDA_TF = '''resource "aws_s3_bucket" "receipts" {
  bucket = "shop-receipts"
}

resource "aws_iam_role" "api" {
  name = "api"
}

resource "aws_iam_role_policy" "api" {
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

resource "aws_lambda_function" "api" {
  role = aws_iam_role.api.arn

  environment {
    variables = {
      RECEIPTS_BUCKET = aws_s3_bucket.receipts.bucket
      LOG_LEVEL       = "info"
    }
  }
}
'''


def lambda_plan(actions: list[str]) -> str:
    return plan_of({"resources": [
        resource("aws_s3_bucket", "receipts"), resource("aws_iam_role", "api"),
        resource("aws_iam_role_policy", "api", role=["aws_iam_role.api.id", "aws_iam_role.api"],
                 policy=["data.aws_iam_policy_document.api.json", "data.aws_iam_policy_document.api"]),
        resource("aws_lambda_function", "api", role=["aws_iam_role.api.arn", "aws_iam_role.api"],
                 environment=["aws_s3_bucket.receipts.bucket", "aws_s3_bucket.receipts"]),
        document("api", (actions, ["aws_s3_bucket.receipts.arn", "aws_s3_bucket.receipts"]))]})


API_PY = '''"""The api."""
import os

import boto3

s3 = boto3.client("s3")
BUCKET = os.environ["RECEIPTS_BUCKET"]


def save(body: bytes) -> None:
    """Keep a receipt."""
    s3.put_object(Bucket=BUCKET, Key="receipt", Body=body)
'''
LAMBDA_PHYSICAL = "shop.api: [terraform:aws_lambda_function.api, python:shop.api]\nshop.receipts: [terraform:aws_s3_bucket.receipts]\n"


def deployed(actions: list[str], api: str = API_PY) -> dict[str, str]:
    return {**FILES, "design/physical.yaml": LAMBDA_PHYSICAL, "infra/main.tf": LAMBDA_TF,
            ".zigdag/plan.json": lambda_plan(actions), "src/shop/api.py": api}


@verifies("zigdag.adapters.terraform#grants")
def test_a_roles_policies_grant_read_or_write_of_each_resource_their_statements_name():
    assert access.access_of("s3:GetObject") == (ResourceAccess.READ,)
    assert access.access_of("s3:PutObject") == access.access_of("s3:Put*") == (ResourceAccess.WRITE,)
    assert access.access_of("s3:*") == access.access_of("*") == (ResourceAccess.READ, ResourceAccess.WRITE)
    model = read_terraform(TerraformFiles({"infra/main.tf": LAMBDA_TF}, "infra",
                                          lambda_plan(["s3:GetObject", "s3:PutObject"]), ".zigdag/plan.json"))
    assert sorted(((g.to, g.on, g.access, g.action) for g in model.grants), key=lambda g: g[3]) == [
        ("aws_iam_role.api", "aws_s3_bucket.receipts", ResourceAccess.READ, "s3:GetObject"),
        ("aws_iam_role.api", "aws_s3_bucket.receipts", ResourceAccess.WRITE, "s3:PutObject")]
    assert ("aws_iam_role.api", "aws_s3_bucket.receipts") in {
        (str(d.source), d.target) for d in model.dependencies if d.kind is DependencyKind.GRANT}
    (inline,) = read_terraform(TerraformFiles({}, "infra", PLAN, ".zigdag/plan.json")).grants  # a policy as text
    assert (inline.to, inline.on, inline.access) == ("aws_iam_role.api", "aws_s3_bucket.receipts", None)
    attached = plan_of({"resources": [
        resource("aws_s3_bucket", "receipts"), resource("aws_iam_role", "api"),
        resource("aws_iam_policy", "write", policy=["data.aws_iam_policy_document.api.json"]),
        resource("aws_iam_role_policy_attachment", "api", role=["aws_iam_role.api.name"],
                 policy_arn=["aws_iam_policy.write.arn"]),
        document("api", (["s3:PutObject"], ["aws_s3_bucket.receipts.arn"]), (["logs:PutLogEvents"], []))]})
    model = read_terraform(TerraformFiles({}, "infra", attached, ".zigdag/plan.json"))
    assert [(g.to, g.on, g.action) for g in model.grants] == [("aws_iam_role.api", "aws_s3_bucket.receipts", "s3:PutObject")]
    (wide,) = [p for p in model.problems if p.result is Result.QUESTION]  # a grant on "*" names no resource here
    assert "logs:PutLogEvents" in wide.say


@verifies("zigdag.adapters.terraform#connections")
def test_a_network_rule_lets_one_security_group_reach_another_and_makes_neither_part_of_the_other():
    text = plan_of({"resources": [
        resource("aws_security_group", "api"), resource("aws_security_group", "web"),
        {**resource("aws_security_group", "db"),
         "expressions": {"ingress": [{"security_groups": {"references": ["aws_security_group.api.id"]}}]}},
        {**resource("aws_security_group_rule", "web_to_api", security_group_id=["aws_security_group.api.id"],
                    source_security_group_id=["aws_security_group.web.id"]),
         } ]})
    model = read_terraform(TerraformFiles({}, "infra", text, ".zigdag/plan.json"))
    kinds = {(str(d.source), d.target): d.kind for d in model.dependencies
             if "rule" not in str(d.source)}
    assert kinds == {("aws_security_group.api", "aws_security_group.db"): DependencyKind.CONNECTION,
                     ("aws_security_group.web", "aws_security_group.api"): DependencyKind.CONNECTION}


@verifies("zigdag.adapters.terraform#settings")
def test_a_setting_that_points_at_a_resource_is_read_from_the_source():
    model = read_terraform(TerraformFiles({"infra/main.tf": LAMBDA_TF}, "infra", lambda_plan([]), ".zigdag/plan.json"))
    assert [(s.at, s.name, s.target) for s in model.settings] == [
        ("aws_lambda_function.api", "RECEIPTS_BUCKET", "aws_s3_bucket.receipts")]  # LOG_LEVEL points at nothing
    pairs = '''resource "aws_ecs_task_definition" "api" {
  container_definitions = jsonencode([{
    environment = [
      { name = "RECEIPTS_BUCKET", value = aws_s3_bucket.receipts.bucket },
      {
        name  = "QUEUE_URL"
        value = aws_sqs_queue.jobs.url
      },
    ]
  }])
}
'''
    text = plan_of({"resources": [resource("aws_s3_bucket", "receipts"), resource("aws_sqs_queue", "jobs"),
                                  resource("aws_ecs_task_definition", "api")]})
    model = read_terraform(TerraformFiles({"infra/main.tf": pairs + MAIN_TF.split("\n\n")[0] + "\n\nresource \"aws_sqs_queue\" \"jobs\" {\n}\n"},
                                          "infra", text, ".zigdag/plan.json"))
    assert sorted((s.name, s.target) for s in model.settings) == [
        ("QUEUE_URL", "aws_sqs_queue.jobs"), ("RECEIPTS_BUCKET", "aws_s3_bucket.receipts")]


@verifies("zigdag.adapters.python#resource-uses")
def test_a_call_to_a_boto3_client_is_read_with_the_setting_its_resource_comes_from():
    source = API_PY + '''

def find(key: str) -> bytes:
    """A receipt."""
    return boto3.client("s3").get_object(Bucket=os.getenv("RECEIPTS_BUCKET"), Key=key)["Body"]


def drop(bucket: str) -> None:
    """Remove a receipt from a bucket the caller names."""
    s3.delete_object(Bucket=bucket, Key="receipt")
'''
    model = read_python(PythonFiles({"src/shop/api.py": source}, ("src",), (), {}, None, {}))
    assert [(str(u.at), u.access, u.via, u.setting) for u in model.resource_uses] == [
        ("shop.api.save", ResourceAccess.WRITE, "s3.put_object", "RECEIPTS_BUCKET"),
        ("shop.api.find", ResourceAccess.READ, "s3.get_object", "RECEIPTS_BUCKET"),
        ("shop.api.drop", ResourceAccess.WRITE, "s3.delete_object", None)]


@verifies("zigdag.core.analysis.checks#permitted")
def test_code_that_needs_access_the_infrastructure_does_not_grant_breaks():
    granted = plans.analysis(deployed(["s3:PutObject"]))
    assert not said(granted, "permitted-effects") and not said(granted, "permitted-effects", Result.QUESTION)
    assert [r.effect for r in granted.context.relations.resource_effects] == ["shop.receipts.write"]
    (refused,) = said(plans.analysis(deployed(["s3:GetObject"])), "permitted-effects")
    assert "shop.api.save is writing to the receipts (through s3.put_object)" in refused
    assert "grants shop.api no such access" in refused
    elsewhere = API_PY.replace('"RECEIPTS_BUCKET"', '"ARCHIVE_BUCKET"')
    (unknown,) = said(plans.analysis(deployed(["s3:PutObject"], elsewhere)), "permitted-effects", Result.QUESTION)
    assert "which one cannot be told" in unknown and "ARCHIVE_BUCKET" in unknown


@verifies("zigdag.core.analysis.checks#least")
def test_access_granted_that_no_code_uses_is_a_question():
    analysis = plans.analysis(deployed(["s3:PutObject", "s3:GetObject"]))
    assert said(analysis, "least-privilege", Result.QUESTION) == [
        "the infrastructure lets shop.api read shop.receipts (s3:GetObject), and no code of shop.api does"]
    assert not said(plans.analysis(deployed(["s3:PutObject"])), "least-privilege", Result.QUESTION)


@verifies("zigdag.core.analysis.checks#permitted")
def test_a_project_that_describes_no_infrastructure_has_no_resource_effects():
    files = {k: v for k, v in deployed(["s3:PutObject"]).items() if not k.startswith(("infra/", ".zigdag/"))}
    files["zigdag.toml"] = SETTINGS.split("[adapters.terraform]")[0]
    files["design/physical.yaml"] = "shop.api: [python:shop.api]\n"
    analysis = plans.analysis(files)
    assert not analysis.context.relations.resource_effects and not analysis.context.relations.untraced


ENCODED_TF = '''resource "aws_s3_bucket" "receipts" {
}

resource "aws_sqs_queue" "jobs" {
}

resource "aws_iam_role" "api" {
  assume_role_policy = jsonencode({
    Statement = [{ Action = "sts:AssumeRole", Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy" "api" {
  role = aws_iam_role.api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = ["${aws_s3_bucket.receipts.arn}/*", aws_s3_bucket.receipts.arn]
      },
      { Effect = "Deny", Action = "sqs:DeleteQueue", Resource = aws_sqs_queue.jobs.arn },
      { Effect = "Allow", Action = "logs:PutLogEvents", Resource = "*" },
    ]
  })
}
'''
ENCODED_KNOWN = frozenset({("aws_s3_bucket", "receipts"), ("aws_sqs_queue", "jobs"), ("aws_iam_role", "api"),
                           ("aws_iam_role_policy", "api")})


def block_of(text: str, header: str) -> list[str]:
    lines = text.splitlines()
    start = lines.index(header)
    return lines[start:lines.index("}", start) + 1]


@verifies("zigdag.adapters.terraform#written-policies")
def test_a_policy_written_as_text_is_read_from_the_source_statement_by_statement():
    policy = block_of(ENCODED_TF, 'resource "aws_iam_role_policy" "api" {')
    writes, logs = policy_text.statements(policy, ENCODED_KNOWN)  # the statement that denies grants nothing
    assert (writes.actions, writes.on, writes.everything) == (
        ("s3:PutObject", "s3:GetObject"), (("aws_s3_bucket", "receipts"),), False)
    assert (logs.actions, logs.on, logs.everything) == (("logs:PutLogEvents",), (), True)
    role = block_of(ENCODED_TF, 'resource "aws_iam_role" "api" {')
    assert policy_text.statements(role, ENCODED_KNOWN) == ()  # who may take a role names no resource
    as_json = ['policy = <<EOT', '{"Statement": [{"Effect": "Allow", "Action": "sqs:SendMessage",',
               '  "Resource": "${aws_sqs_queue.jobs.arn}"}]}', "EOT"]
    (sends,) = policy_text.statements(as_json, ENCODED_KNOWN)
    assert (sends.actions, sends.on) == (("sqs:SendMessage",), (("aws_sqs_queue", "jobs"),))


@verifies("zigdag.adapters.terraform#written-policies")
def test_a_written_policy_that_cannot_be_read_for_certain_is_not_read_at_all():
    def read(statement: str) -> object:
        return policy_text.statements(["policy = jsonencode({ Statement = [", statement, "] })"], ENCODED_KNOWN)

    assert read('{ Action = "s3:PutObject", Resource = var.bucket_arn }') is None  # a name given elsewhere
    assert read('{ Action = local.actions, Resource = aws_s3_bucket.receipts.arn }') is None
    assert read('{ NotAction = "s3:DeleteObject", Resource = aws_s3_bucket.receipts.arn }') is None  # an exclusion
    assert read('{ Action = "s3:PutObject", Resource = aws_s3_bucket.receipts.arn }') is not None


@verifies("zigdag.adapters.terraform#written-policies", "zigdag.adapters.terraform#grants")
def test_a_written_policys_statements_are_the_grants_of_the_role_it_is_given_to():
    refers = ["aws_s3_bucket.receipts.arn", "aws_s3_bucket.receipts", "aws_sqs_queue.jobs.arn", "aws_sqs_queue.jobs"]
    text = plan_of({"resources": [
        resource("aws_s3_bucket", "receipts"), resource("aws_sqs_queue", "jobs"), resource("aws_iam_role", "api"),
        resource("aws_iam_role_policy", "api", role=["aws_iam_role.api.id", "aws_iam_role.api"], policy=refers)]})
    model = read_terraform(TerraformFiles({"infra/main.tf": ENCODED_TF}, "infra", text, ".zigdag/plan.json"))
    assert sorted((g.on, g.action, g.access) for g in model.grants if g.access is not None) == [
        ("aws_s3_bucket.receipts", "s3:GetObject", ResourceAccess.READ),
        ("aws_s3_bucket.receipts", "s3:PutObject", ResourceAccess.WRITE)]
    # the queue is referred to by the policy, and no statement that allows names it: what it is granted is not known
    assert [(g.on, g.access) for g in model.grants if g.access is None] == [("aws_sqs_queue.jobs", None)]
    (wide,) = [p for p in model.problems if p.result is Result.QUESTION]
    assert "aws_iam_role_policy.api grants logs:PutLogEvents" in wide.say
    unlocated = read_terraform(TerraformFiles({}, "infra", text, ".zigdag/plan.json"))  # no source to read it from
    assert {g.access for g in unlocated.grants} == {None}
