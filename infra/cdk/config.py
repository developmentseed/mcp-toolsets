"""What the stack is told, and where each answer comes from.

Everything the stack needs arrives as CDK context or as a file in this repo.
Nothing is looked up from an AWS account, so ``cdk synth`` runs on a pull
request with no credentials attached — which is what makes the stack reviewable
the way the charts are.

That rule is why subnets arrive as identifiers and a hosted zone as its name
*and* its id: the convenience constructors for both do an environment lookup,
and a lookup needs an account.
"""

from __future__ import annotations

import re
import zlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: Selector the index reads to find toolsets, matching the chart's label.
TOOLSET_TAG = "mcp-toolsets/toolset"

#: Port every toolset serves on: the Dockerfile's EXPOSE and the chart's default.
TOOLSET_PORT = 8000

#: Port the chat serves on (Dockerfile.chat).
CHAT_PORT = 8080

#: Smallest Fargate combination, and what a toolset gets unless it asks for more.
DEFAULT_CPU = 256
DEFAULT_MEMORY = 512

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

#: Applied to every taggable resource in every stack. Cost reporting and
#: ownership questions are asked of an account long after a deploy, by people
#: who were not there for it, so the answer has to be on the resources rather
#: than in someone's memory of which stack made them.
TAG_DEFAULTS: dict[str, str] = {
    "Project": "mcp-toolsets",
    "Owner": "ciaran",
    "Client": "labs",
    "Stack": "dev",
}


def tags(**overrides: str | None) -> dict[str, str]:
    """The tags to apply, with any given value replacing its default.

    Keys are the tag names lowercased, so ``tags(owner="ada")`` sets ``Owner``.
    An unset or empty override keeps the default rather than tagging a resource
    with an empty string, which reads in a bill as though nobody set it.
    """
    unknown = set(overrides) - {name.lower() for name in TAG_DEFAULTS}
    if unknown:
        raise ConfigError(f"unknown tag(s): {', '.join(sorted(unknown))}")
    return {
        name: overrides.get(name.lower()) or default
        for name, default in TAG_DEFAULTS.items()
    }


#: Listener rule priorities. 1 is the chat's host rule; toolsets take a slice
#: of the space above it, well inside the load balancer's limit of 50000.
FIRST_PRIORITY = 100
PRIORITY_SPAN = 40000


def listener_priorities(names: Iterable[str]) -> dict[str, int]:
    """A stable rule priority per toolset, derived from its own name.

    Numbering by position looks tidier and is wrong: adding a toolset that
    sorts early shifts every rule after it, and a load balancer refuses a
    priority another rule still holds — so the deploy that adds one toolset
    fails on the rules of toolsets it never touched.

    Hashing the name instead means a toolset's priority depends on nothing but
    itself. Two names can collide, at which point the later one in sort order
    takes the next free slot; with a span this wide that is rare enough to
    accept, and deterministic when it happens.
    """
    taken: set[int] = set()
    priorities: dict[str, int] = {}
    for name in sorted(names):
        priority = FIRST_PRIORITY + zlib.crc32(name.encode()) % PRIORITY_SPAN
        while priority in taken:
            priority += 1
        taken.add(priority)
        priorities[name] = priority
    return priorities


class ConfigError(Exception):
    """Configuration that cannot produce a stack worth deploying."""


@dataclass(frozen=True)
class Toolset:
    """One toolset, and the deployment overrides its own file asks for."""

    name: str
    cpu: int = DEFAULT_CPU
    memory: int = DEFAULT_MEMORY
    env: dict[str, str] = field(default_factory=dict)
    #: Environment variable -> Parameter Store path, read at task start.
    secrets: dict[str, str] = field(default_factory=dict)

    @property
    def service_name(self) -> str:
        """Matches the Helm release name, so both targets read the same."""
        return f"mcp-{self.name}"

    @property
    def path_prefix(self) -> str:
        """Where this toolset answers under the shared host."""
        return f"/{self.name}"


@dataclass(frozen=True)
class Domain:
    """How the load balancer is reached, and who writes the DNS.

    Three shapes, and the difference is who owns the records:

    - ``managed``: a hosted zone in this account. The stack requests the
      certificate, writes its validation records and points both hosts at the
      load balancer.
    - ``bring your own``: a certificate that already exists. The stack writes no
      DNS at all and publishes the load balancer's name to aim a record at.
    - neither: plain HTTP on the name AWS assigns. A starting state, so a first
      deploy is testable before a domain is arranged — not a posture.
    """

    host: str | None = None
    chat_host: str | None = None
    hosted_zone_id: str | None = None
    certificate_arn: str | None = None

    def __post_init__(self) -> None:
        if self.hosted_zone_id and self.certificate_arn:
            raise ConfigError(
                "give a hosted zone or a certificate, not both: with a zone the "
                "stack issues and renews the certificate itself"
            )
        if (self.hosted_zone_id or self.certificate_arn) and not self.host:
            raise ConfigError("a hosted zone or certificate needs a host to go with it")

    @property
    def secure(self) -> bool:
        """Whether there is a certificate to put on a listener."""
        return bool(self.host) and (
            bool(self.hosted_zone_id) or bool(self.certificate_arn)
        )

    @property
    def manages_dns(self) -> bool:
        return bool(self.hosted_zone_id)

    @property
    def resolved_chat_host(self) -> str | None:
        """The chat's own hostname; it needs one, and cannot share a path."""
        if not self.host:
            return None
        return self.chat_host or f"chat.{self.host}"

    def public_url(self, load_balancer_dns: str) -> str:
        """Base URL the index publishes for every toolset."""
        if self.host:
            return f"{'https' if self.secure else 'http'}://{self.host}"
        return f"http://{load_balancer_dns}"


@dataclass(frozen=True)
class Chat:
    """The hosted chat: the model it answers on, and what its page says.

    Nothing is deployed without ``model``. The chat runs every visitor's
    questions on one model and bills them to this account, so a deployment
    turns it on deliberately or not at all — an empty model is not a
    misconfiguration, it is the default.

    The key is never here and never in context, which would put it in a
    CloudFormation template. It is read at task start from a Parameter Store
    SecureString, the same way a toolset's own secrets are, and creating that
    parameter is the deploying account's job.

    The rest is what the page says about itself. It is committed rather than
    passed in because it is prose about *this* deployment, reviewed like any
    other text here — the equivalent of the chart's values file on the other
    target. Leave ``greeting`` empty and the page opens on what the agent is
    actually connected to, which stays true as toolsets come and go.
    """

    model: str = ""
    #: Parameter Store path holding the provider key. Defaults under the
    #: instance's own prefix, beside every other secret it reads.
    api_key_parameter: str = ""
    title: str = "MCP Toolsets"
    tagline: str = ""
    greeting: str = ""
    examples: tuple[str, ...] = ()
    accent: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.model)

    def parameter(self, prefix: str) -> str:
        return self.api_key_parameter or f"{prefix}/chat/provider-api-key"

    def environment(self) -> dict[str, str]:
        """The ``MCP_AGENT_UI_*`` variables the runtime's client reads.

        Empty values are left out rather than set empty: the client falls back
        to its own defaults on an unset variable, and to nothing at all on one
        set to "".
        """
        values = {
            "MCP_AGENT_UI_TITLE": self.title,
            "MCP_AGENT_UI_TAGLINE": self.tagline,
            "MCP_AGENT_UI_GREETING": self.greeting,
            # One per line; the runtime reads lines or a JSON array.
            "MCP_AGENT_UI_EXAMPLES": "\n".join(self.examples),
            "MCP_AGENT_UI_ACCENT": self.accent,
        }
        return {name: value for name, value in values.items() if value}


@dataclass(frozen=True)
class Network:
    """A network the stack builds, or one it is handed.

    Built by default into public subnets with no gateway, so the stack deploys
    into an empty account. Handed existing subnets, it creates nothing — and
    those subnets must be able to reach the image registry, which is the one
    thing this cannot check for you.
    """

    vpc_id: str | None = None
    subnet_ids: tuple[str, ...] = ()
    availability_zones: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if bool(self.vpc_id) != bool(self.subnet_ids):
            raise ConfigError(
                "bring-your-own network needs both a vpc id and its subnet ids"
            )
        if self.subnet_ids and len(self.subnet_ids) != len(self.availability_zones):
            raise ConfigError(
                "each subnet id needs its availability zone: "
                f"{len(self.subnet_ids)} subnets, "
                f"{len(self.availability_zones)} zones"
            )

    @property
    def bring_your_own(self) -> bool:
        return bool(self.vpc_id)


@dataclass(frozen=True)
class Deployment:
    """Everything one instance of this repo deploys."""

    instance: str
    toolsets: tuple[Toolset, ...]
    #: Toolset (or ``index``/``chat``) -> image tag. Held in Parameter Store
    #: between deploys, because a stack has no memory of the tag a service is
    #: on and would otherwise reset an untouched one.
    image_tags: dict[str, str] = field(default_factory=dict)
    image_prefix: str = ""
    #: Secrets Manager secret holding the registry username and password.
    registry_secret_arn: str | None = None
    domain: Domain = field(default_factory=Domain)
    network: Network = field(default_factory=Network)
    chat: Chat = field(default_factory=Chat)
    #: Where per-toolset secrets live, and the prefix the task role can read.
    parameter_prefix: str = ""

    def __post_init__(self) -> None:
        if not NAME_RE.match(self.instance):
            raise ConfigError(
                "instance name must be kebab-case (lowercase letters, digits, "
                f"hyphens), got {self.instance!r}"
            )
        if not self.parameter_prefix:
            object.__setattr__(
                self, "parameter_prefix", f"/mcp-toolsets/{self.instance}"
            )

    def image(self, component: str) -> str:
        """Full image reference for a toolset, the index or the chat.

        A component with no tag is one nothing has ever deployed. Refusing here
        beats deploying ``:latest`` at a service and hoping.
        """
        tag = self.image_tags.get(component)
        if not tag:
            raise ConfigError(
                f"no image tag for {component!r}: the deploy writes one per "
                f"component to {self.parameter_prefix}/<component>/image-tag "
                "and passes them back as context"
            )
        return f"{self.image_prefix}/mcp-{component}:{tag}"


def load_toolset(directory: Path) -> Toolset:
    """Read one toolset's deployment overrides, if it has any."""
    overrides: dict[str, Any] = {}
    config = directory / "toolset.aws.yaml"
    if config.is_file():
        overrides = yaml.safe_load(config.read_text()) or {}
    if not isinstance(overrides, dict):
        raise ConfigError(f"{config} must be a mapping, got {type(overrides).__name__}")

    size = overrides.get("size") or {}
    if not isinstance(size, dict):
        raise ConfigError(f"{config}: size must be a mapping of cpu and memory")

    return Toolset(
        name=directory.name,
        cpu=int(size.get("cpu", DEFAULT_CPU)),
        memory=int(size.get("memory", DEFAULT_MEMORY)),
        env={str(k): str(v) for k, v in (overrides.get("env") or {}).items()},
        secrets={str(k): str(v) for k, v in (overrides.get("secrets") or {}).items()},
    )


def load_toolsets(root: Path) -> tuple[Toolset, ...]:
    """Every toolset in the repo, in name order.

    The directory listing is the source of truth, exactly as it is for the Helm
    target: a toolset removed from the repo is a service removed from the stack
    on the next deploy, which is what replaces a reconcile step.
    """
    toolsets_dir = root / "toolsets"
    if not toolsets_dir.is_dir():
        raise ConfigError(f"no toolsets directory at {toolsets_dir}")
    directories = sorted(
        path
        for path in toolsets_dir.iterdir()
        if path.is_dir() and (path / "pyproject.toml").is_file()
    )
    return tuple(load_toolset(directory) for directory in directories)
