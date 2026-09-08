"""What the stack refuses to be built from."""

import pytest
import yaml

from infra.cdk.app import ROOT
from infra.cdk.config import (
    TAG_DEFAULTS,
    ConfigError,
    Deployment,
    Domain,
    Network,
    Toolset,
    load_toolset,
    load_toolsets,
    tags,
)


def deployment(**overrides) -> Deployment:
    defaults = dict(
        instance="mcp-toolsets",
        toolsets=(Toolset(name="example"),),
        image_tags={"example": "sha1"},
        image_prefix="ghcr.io/owner/repo",
    )
    return Deployment(**{**defaults, **overrides})


def test_every_toolset_directory_is_read(tmp_path):
    """The directory listing is the source of truth, as it is for Helm: a
    toolset added to the repo is a service on the next deploy, and one removed
    is a service gone. Nothing anywhere names a toolset."""
    toolsets = tmp_path / "toolsets"
    for name in ("beta", "alpha"):
        (toolsets / name).mkdir(parents=True)
        (toolsets / name / "pyproject.toml").touch()
    # A directory that is not a package is not a toolset.
    (toolsets / "notes").mkdir()

    assert [toolset.name for toolset in load_toolsets(tmp_path)] == ["alpha", "beta"]


def test_this_repos_own_toolsets_load():
    names = [toolset.name for toolset in load_toolsets(ROOT)]
    assert names == sorted(names)


def test_overrides_come_from_the_toolsets_own_file(tmp_path):
    directory = tmp_path / "sized"
    directory.mkdir()
    (directory / "toolset.aws.yaml").write_text(
        yaml.safe_dump(
            {
                "size": {"cpu": 512, "memory": 1024},
                "env": {"STAC_URL": "https://example.org"},
                "secrets": {"API_TOKEN": "/mcp-toolsets/x/sized/api-token"},
            }
        )
    )
    toolset = load_toolset(directory)
    assert (toolset.cpu, toolset.memory) == (512, 1024)
    assert toolset.env == {"STAC_URL": "https://example.org"}
    assert toolset.secrets == {"API_TOKEN": "/mcp-toolsets/x/sized/api-token"}


def test_a_toolset_without_a_file_gets_the_smallest_task(tmp_path):
    directory = tmp_path / "plain"
    directory.mkdir()
    toolset = load_toolset(directory)
    assert (toolset.cpu, toolset.memory) == (256, 512)
    assert toolset.path_prefix == "/plain"


def test_a_missing_image_tag_is_refused():
    """Better than deploying `:latest` at a service and hoping."""
    with pytest.raises(ConfigError, match="no image tag"):
        deployment(image_tags={}).image("example")


def test_the_image_is_built_from_prefix_and_tag():
    assert deployment().image("example") == "ghcr.io/owner/repo/mcp-example:sha1"


def test_a_zone_and_a_certificate_together_are_refused():
    """With a zone the stack issues and renews its own certificate, so being
    given one as well means somebody expects the other thing to happen."""
    with pytest.raises(ConfigError, match="not both"):
        Domain(host="mcp.example.com", hosted_zone_id="Z1", certificate_arn="arn:x")


def test_a_certificate_without_a_host_is_refused():
    with pytest.raises(ConfigError, match="needs a host"):
        Domain(certificate_arn="arn:x")


def test_no_domain_means_plain_http_on_the_load_balancer():
    domain = Domain()
    assert domain.secure is False
    assert domain.public_url("alb-123.elb.amazonaws.com") == (
        "http://alb-123.elb.amazonaws.com"
    )


def test_the_chat_host_defaults_under_the_shared_one():
    assert Domain(host="mcp.example.com").resolved_chat_host == "chat.mcp.example.com"
    assert Domain(host="a.com", chat_host="b.com").resolved_chat_host == "b.com"


def test_subnets_need_their_availability_zones():
    """The stack never looks anything up, so a subnet's zone has to be given
    rather than discovered from its id."""
    with pytest.raises(ConfigError, match="availability zone"):
        Network(
            vpc_id="vpc-1",
            subnet_ids=("subnet-a", "subnet-b"),
            availability_zones=("eu-west-1a",),
        )


def test_half_a_network_is_refused():
    with pytest.raises(ConfigError, match="both a vpc id and its subnet ids"):
        Network(vpc_id="vpc-1")


def test_the_instance_name_shapes_the_parameter_prefix():
    assert deployment().parameter_prefix == "/mcp-toolsets/mcp-toolsets"


def test_a_bad_instance_name_is_refused():
    with pytest.raises(ConfigError, match="kebab-case"):
        deployment(instance="Not Valid")


def test_tags_default_to_the_four():
    assert tags() == TAG_DEFAULTS


def test_an_override_replaces_only_its_own():
    assert tags(owner="ada")["Owner"] == "ada"
    assert tags(owner="ada")["Project"] == TAG_DEFAULTS["Project"]


def test_an_empty_override_keeps_the_default():
    """An unset context value arrives as None, and an empty one reads in a bill
    as though nobody set it."""
    assert tags(owner=None, client="")["Owner"] == TAG_DEFAULTS["Owner"]
    assert tags(client="")["Client"] == TAG_DEFAULTS["Client"]


def test_an_unknown_tag_is_refused():
    with pytest.raises(ConfigError, match="unknown tag"):
        tags(department="labs")
