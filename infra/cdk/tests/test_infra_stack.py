"""What the synthesised stack must contain, and what it must not need.

Targeted assertions rather than a template snapshot: a snapshot churns on every
library bump and tells you nothing about which line mattered.
"""

import json
import pathlib

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from infra.cdk.app import ROOT, build
from infra.cdk.config import (
    TAG_DEFAULTS,
    TOOLSET_TAG,
    listener_priorities,
    load_toolsets,
)
from infra.cdk.toolsets_stack import INDEX_COMPONENT

#: Read from the repo rather than written down: adding a toolset must not mean
#: editing a test, and every example can be removed at bootstrap.
TOOLSETS = tuple(toolset.name for toolset in load_toolsets(ROOT))
BASE = {
    "instance": "mcp-toolsets",
    "imagePrefix": "ghcr.io/owner/repo",
}

#: A deployment that has a chat. It takes both: a hostname to route to, and a
#: model to answer on — the second is what a deployment opts in to, because
#: every visitor's questions are billed to the account it deploys into.
WITH_CHAT = {
    "host": "mcp.example.com",
    "hostedZoneId": "Z1",
    "chatModel": "openai:gpt-4o-mini",
}


def assembly(**context):
    tags = json.dumps({name: "sha1" for name in (*TOOLSETS, INDEX_COMPONENT, "chat")})
    return build(cdk.App(context={**BASE, "imageTags": tags, **context})).synth()


def template(**context) -> Template:
    return Template.from_json(
        assembly(**context).get_stack_by_name("mcp-toolsets").template
    )


def test_synthesis_needs_no_account():
    """The whole point of taking identifiers rather than looking things up: a
    pull request checks this stack with no credentials attached.

    A lookup leaves an entry under `missing` in the cloud assembly manifest and
    sends the CLI to the account to fill it in, so an empty list here is the
    assertion that none was reached for.
    """
    manifest = json.loads(
        (pathlib.Path(assembly().directory) / "manifest.json").read_text()
    )
    assert manifest.get("missing", []) == []


def test_one_service_per_toolset_plus_the_index_and_chat():
    template(**WITH_CHAT).resource_count_is("AWS::ECS::Service", len(TOOLSETS) + 2)


def test_every_toolset_service_carries_the_tag_the_index_selects_on():
    """Untagged is invisible: the toolset runs and the directory omits it."""
    services = template().find_resources("AWS::ECS::Service")
    tagged = {
        tag["Value"]
        for service in services.values()
        for tag in service["Properties"].get("Tags", [])
        if tag["Key"] == TOOLSET_TAG
    }
    assert tagged == set(TOOLSETS)


def test_each_toolset_is_told_the_path_it_is_published_at():
    """An ALB forwards the path unrewritten, so the toolset has to serve it."""
    definitions = template().find_resources("AWS::ECS::TaskDefinition")
    prefixes = {
        variable["Value"]
        for definition in definitions.values()
        for container in definition["Properties"]["ContainerDefinitions"]
        for variable in container.get("Environment", [])
        if variable["Name"] == "MCP_PATH_PREFIX"
    }
    assert prefixes == {f"/{name}" for name in TOOLSETS}


def test_each_toolset_claims_its_own_path():
    rules = template().find_resources("AWS::ElasticLoadBalancingV2::ListenerRule")
    patterns = {
        tuple(value["PathPatternConfig"]["Values"])
        for rule in rules.values()
        for value in rule["Properties"]["Conditions"]
        if "PathPatternConfig" in value
    }
    assert patterns == {(f"/{name}", f"/{name}/*") for name in TOOLSETS}


def test_health_checks_use_the_root_route():
    """Below the routing that adds the prefix, which is why the runtime keeps
    answering there as well as at the prefixed path."""
    groups = template(**WITH_CHAT).find_resources(
        "AWS::ElasticLoadBalancingV2::TargetGroup"
    )
    paths = {
        group["Properties"]["HealthCheckPath"]
        for group in groups.values()
        if group["Properties"].get("HealthCheckPath")
    }
    # The chat's is readiness rather than its page: it serves the page as soon
    # as the process is up, and cannot answer until it has connected to every
    # toolset. Checking the page would put it in service answering 503.
    assert paths == {"/health", "/health/readiness"}


def test_the_index_can_read_what_is_running():
    """Get this role wrong and the directory quietly comes back short."""
    template().has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {"Action": "ecs:ListServices", "Effect": "Allow"}
                        )
                    ]
                )
            }
        },
    )


def test_a_failed_update_rolls_the_instance_back():
    for service in template().find_resources("AWS::ECS::Service").values():
        assert service["Properties"]["DeploymentConfiguration"][
            "DeploymentCircuitBreaker"
        ] == {"Enable": True, "Rollback": True}


def test_the_chat_is_pointed_at_the_index_by_its_registered_name():
    """The chat reaches the index over Cloud Map, so the name in its
    environment and the name the index registers under are the same fact.
    Written out by hand, a rename breaks the link and the chat fails at the
    first request with a DNS error rather than at deploy."""
    definitions = template(**WITH_CHAT).find_resources("AWS::ECS::TaskDefinition")
    urls = [
        variable["Value"]
        for definition in definitions.values()
        for container in definition["Properties"]["ContainerDefinitions"]
        for variable in container.get("Environment", [])
        if variable["Name"] == "MCP_URL"
    ]
    assert urls == [f"http://mcp-{INDEX_COMPONENT}.mcp-toolsets.internal:8000/"]


def test_the_index_and_chat_can_reach_what_they_talk_to():
    """Each service has its own security group and only the load balancer is
    let in by default. In a cluster pods talk freely and this rule has no
    equivalent; here, without it, the index lists toolsets it cannot reach and
    reports every one of them unreachable."""
    ingress = template(**WITH_CHAT).find_resources("AWS::EC2::SecurityGroupIngress")
    reasons = [rule["Properties"].get("Description", "") for rule in ingress.values()]
    # One per toolset for the index, plus the chat reaching the index.
    assert sum("the index asks each toolset" in r for r in reasons) == len(TOOLSETS)
    assert sum("the chat reads the directory" in r for r in reasons) == 1
    assert all(
        rule["Properties"]["FromPort"] == 8000
        for rule in ingress.values()
        if "index asks" in rule["Properties"].get("Description", "")
    )


def test_a_managed_domain_writes_its_own_records_and_certificate():
    managed = template(**WITH_CHAT)
    managed.resource_count_is("AWS::Route53::RecordSet", 2)
    managed.has_resource_properties(
        "AWS::CertificateManager::Certificate",
        {"SubjectAlternativeNames": ["chat.mcp.example.com"]},
    )


def test_a_hostname_alone_deploys_no_chat_and_no_record_for_one():
    """The record is the part worth a test. A name that resolves to the load
    balancer with no rule behind it does not fail — it lands on the index, so
    the chat host answers with the directory and looks like a broken chat."""
    without = template(host="mcp.example.com", hostedZoneId="Z1")
    without.resource_count_is("AWS::ECS::Service", len(TOOLSETS) + 1)
    without.resource_count_is("AWS::Route53::RecordSet", 1)
    certificates = without.find_resources("AWS::CertificateManager::Certificate")
    assert all(
        "SubjectAlternativeNames" not in certificate["Properties"]
        for certificate in certificates.values()
    )


def test_the_provider_key_is_a_reference_and_never_a_value():
    """It is read at task start from Parameter Store. Passed as context it
    would sit in the template, readable by anyone who can describe the stack."""
    rendered = json.dumps(
        assembly(**WITH_CHAT, chatApiKeyParameter="/somewhere/else")
        .get_stack_by_name("mcp-toolsets")
        .template
    )
    assert "/somewhere/else" in rendered
    definitions = template(**WITH_CHAT).find_resources("AWS::ECS::TaskDefinition")
    secrets = [
        secret
        for definition in definitions.values()
        for container in definition["Properties"]["ContainerDefinitions"]
        for secret in container.get("Secrets", [])
    ]
    assert [secret["Name"] for secret in secrets] == ["PROVIDER_API_KEY"]
    assert "ValueFrom" in secrets[0]


def test_the_page_is_configured_from_the_deployments_own_text():
    """`Chat`'s defaults are committed prose about this deployment, and they
    reach the client as the variables the runtime reads."""
    definitions = template(**WITH_CHAT).find_resources("AWS::ECS::TaskDefinition")
    variables = {
        variable["Name"]: variable["Value"]
        for definition in definitions.values()
        for container in definition["Properties"]["ContainerDefinitions"]
        for variable in container.get("Environment", [])
    }
    assert variables["PROVIDER_MODEL"] == "openai:gpt-4o-mini"
    assert variables["MCP_AGENT_UI_TITLE"]
    # Unset text is left out rather than set empty: the client falls back to
    # its own default on an absent variable, and to nothing on an empty one.
    assert "MCP_AGENT_UI_GREETING" not in variables


def test_bringing_your_own_certificate_writes_no_dns():
    byo = template(
        host="mcp.example.com",
        certificateArn="arn:aws:acm:eu-west-1:111122223333:certificate/abc",
    )
    byo.resource_count_is("AWS::Route53::RecordSet", 0)
    byo.resource_count_is("AWS::CertificateManager::Certificate", 0)


def test_without_a_domain_the_listener_is_plain_http_and_the_chat_is_absent():
    """A first deploy is testable before a domain exists; the chat is not,
    because a hostname is the only way to route to it."""
    plain = template()
    plain.resource_count_is("AWS::ECS::Service", len(TOOLSETS) + 1)
    listeners = plain.find_resources("AWS::ElasticLoadBalancingV2::Listener")
    assert {listener["Properties"]["Protocol"] for listener in listeners.values()} == {
        "HTTP"
    }


def test_port_80_is_one_construct_in_both_shapes():
    """Adding a domain to a running instance must not ask for a second
    listener on a port the first one still holds — CloudFormation creates
    before it deletes, and the update dies on a conflict that reads like a
    name clash rather than a change of shape."""

    def port_80_id(template: Template) -> str:
        listeners = template.find_resources("AWS::ElasticLoadBalancingV2::Listener")
        return next(
            key
            for key, listener in listeners.items()
            if listener["Properties"]["Port"] == 80
        )

    plain = port_80_id(template())
    with_domain = port_80_id(template(host="mcp.example.com", hostedZoneId="Z1"))
    assert plain == with_domain


def test_a_certificate_adds_a_redirect_from_plain_http():
    listeners = template(host="mcp.example.com", hostedZoneId="Z1").find_resources(
        "AWS::ElasticLoadBalancingV2::Listener"
    )
    actions = [
        action["Type"]
        for listener in listeners.values()
        for action in listener["Properties"]["DefaultActions"]
    ]
    assert "redirect" in actions


def test_a_missing_image_tag_fails_synthesis():
    partial = json.dumps({TOOLSETS[0]: "sha1"}) if TOOLSETS else json.dumps({})
    with pytest.raises(Exception, match="no image tag"):
        build(cdk.App(context={**BASE, "imageTags": partial}))


def test_adding_a_toolset_leaves_every_other_rule_where_it_was():
    """Numbering by position would shift the rules of toolsets a deploy never
    touched, and a load balancer refuses a priority another rule still holds —
    so the deploy that adds one toolset fails on the others."""
    before = listener_priorities(TOOLSETS)
    after = listener_priorities([*TOOLSETS, "aaa-sorts-first", "zzz-sorts-last"])
    assert all(after[name] == priority for name, priority in before.items())


def test_two_toolsets_never_share_a_rule_priority():
    priorities = listener_priorities([*TOOLSETS, "one", "two", "three", "four"])
    assert len(set(priorities.values())) == len(priorities)


def taggable(template: Template) -> dict[str, list[dict[str, str]]]:
    """Every resource the synthesised template gives a tag list."""
    return {
        name: resource["Properties"]["Tags"]
        for name, resource in template.to_json()["Resources"].items()
        if isinstance(resource.get("Properties"), dict)
        and isinstance(resource["Properties"].get("Tags"), list)
    }


def test_every_taggable_resource_carries_all_four():
    """Cost and ownership questions are asked of an account long after a
    deploy, by people who were not there for it."""
    resources = taggable(template(host="mcp.example.com", hostedZoneId="Z1"))
    assert resources
    for name, tag_list in resources.items():
        applied = {tag["Key"]: tag["Value"] for tag in tag_list}
        missing = set(TAG_DEFAULTS) - set(applied)
        assert not missing, f"{name} is missing {sorted(missing)}"


def test_the_toolset_selector_survives_the_tagging():
    """The index finds toolsets by tag, so a tagging aspect that replaced
    rather than added would make every toolset invisible."""
    resources = taggable(template())
    selectors = {
        tag["Value"]
        for tag_list in resources.values()
        for tag in tag_list
        if tag["Key"] == TOOLSET_TAG
    }
    assert selectors == set(TOOLSETS)


def test_tags_are_overridable_at_deploy_time():
    resources = taggable(template(owner="ada", stack="prod"))
    applied = {tag["Key"]: tag["Value"] for tag in next(iter(resources.values()))}
    assert applied["Owner"] == "ada"
    assert applied["Stack"] == "prod"
    assert applied["Project"] == TAG_DEFAULTS["Project"]


def test_tags_reach_the_running_tasks():
    """A task inherits nothing from its service by default, so the one thing
    that actually runs — and shows up in a cost report — would be the only
    untagged part of the deployment."""
    for service in template().find_resources("AWS::ECS::Service").values():
        assert service["Properties"]["PropagateTags"] == "SERVICE"
        assert service["Properties"]["EnableECSManagedTags"] is True
