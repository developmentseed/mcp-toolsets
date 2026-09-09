"""The CDK entry point: build the stacks from context, then synthesise.

Run it from the repo root, which is where the toolsets are read from. Either
through the CDK CLI, which is what deploys::

    npx aws-cdk@2 deploy <instance> \
        --app "uv run --group infra python -m infra.cdk.app" \
        -c instance=<instance> ...

or directly, which is all a check needs::

    uv run --group infra python -m infra.cdk.app -c instance=<instance> ...

The second form is why this parses ``-c`` itself rather than leaving it to the
CLI: synthesising is a pure function of this repository, so verifying it should
not need a JavaScript CLI downloaded first. Under the CLI the same values
arrive through the environment instead, and both end up as CDK context.

Tags come from context too, one at a time: ``-c owner=ada``. Everything else
falls back to the defaults in :data:`infra.cdk.config.TAG_DEFAULTS`.

Every value comes from context or from a file in this repo, so this synthesises
with no AWS credentials — which is what lets a pull request check the stack the
way ``helm lint`` checks the charts.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import aws_cdk as cdk

from infra.cdk.config import (
    Chat,
    ConfigError,
    Deployment,
    Domain,
    Network,
    load_toolsets,
    tags,
)
from infra.cdk.setup_stack import SetupStack
from infra.cdk.toolsets_stack import ToolsetsStack

ROOT = Path(__file__).resolve().parents[2]


def _optional(app: cdk.App, key: str) -> str | None:
    value = app.node.try_get_context(key)
    return str(value) if value not in (None, "") else None


def _required(app: cdk.App, key: str) -> str:
    value = _optional(app, key)
    if value is None:
        raise ConfigError(f"missing required context: -c {key}=<value>")
    return value


def _list(app: cdk.App, key: str) -> tuple[str, ...]:
    """A comma-separated context value, which is all the CLI can pass."""
    value = _optional(app, key)
    return (
        tuple(part.strip() for part in value.split(",") if part.strip())
        if value
        else ()
    )


def _tags(app: cdk.App) -> dict[str, str]:
    """The image tag per component, as JSON.

    The deploy reads the current tags from Parameter Store, overrides the ones
    this push rebuilt, and passes the whole map back — because a stack has no
    memory of what a service is running and would otherwise reset every
    untouched one to whatever this push happened to build.
    """
    raw = _optional(app, "imageTags")
    if not raw:
        return {}
    tags: Any = json.loads(raw)
    if not isinstance(tags, dict):
        raise ConfigError("imageTags context must be a JSON object of component -> tag")
    return {str(key): str(value) for key, value in tags.items()}


def build(app: cdk.App) -> cdk.App:
    """Add the stacks this repo's context asks for.

    The stacks are deliberately environment-agnostic: no account or region is
    pinned, so they deploy wherever the assumed role points and synthesis never
    asks the environment anything. Naming an environment would undo that —
    CDK resolves a concrete region's availability zones by looking them up,
    which is a credentialled call in the middle of what should be a pure
    function of this repository.
    """
    # Applied to the app, so both stacks and every taggable resource in them
    # carry the same four. Overridable one at a time: -c owner=ada.
    for name, value in tags(
        project=_optional(app, "project"),
        owner=_optional(app, "owner"),
        client=_optional(app, "client"),
        stack=_optional(app, "stack"),
    ).items():
        cdk.Tags.of(app).add(name, value)

    # The setup stack stands alone: it is deployed once, by a person, before
    # the deploy role it creates exists to deploy anything else.
    repository = _optional(app, "repository")
    if repository:
        SetupStack(
            app,
            f"{_required(app, 'instance')}-setup",
            repository=repository,
            provider_arn=_optional(app, "oidcProviderArn"),
        )

    if _optional(app, "setupOnly"):
        return app

    instance = _required(app, "instance")
    deployment = Deployment(
        instance=instance,
        toolsets=load_toolsets(ROOT),
        image_tags=_tags(app),
        image_prefix=_required(app, "imagePrefix"),
        registry_secret_arn=_optional(app, "registrySecretArn"),
        domain=Domain(
            host=_optional(app, "host"),
            chat_host=_optional(app, "chatHost"),
            hosted_zone_id=_optional(app, "hostedZoneId"),
            certificate_arn=_optional(app, "certificateArn"),
        ),
        network=Network(
            vpc_id=_optional(app, "vpcId"),
            subnet_ids=_list(app, "subnetIds"),
            availability_zones=_list(app, "availabilityZones"),
        ),
        # Only the model comes from context, and it is what turns the chat on.
        # The key is a Parameter Store path read at task start, and the page's
        # own text is committed in `Chat`'s defaults — see the class.
        chat=Chat(
            model=_optional(app, "chatModel") or "",
            api_key_parameter=_optional(app, "chatApiKeyParameter") or "",
        ),
    )
    ToolsetsStack(app, instance, deployment=deployment)
    return app


def context_from_argv(argv: list[str]) -> dict[str, str]:
    """Read ``-c key=value`` / ``--context key=value`` pairs, as the CLI does."""
    context: dict[str, str] = {}
    pending = False
    for argument in argv:
        if pending:
            key, _, value = argument.partition("=")
            context[key] = value
            pending = False
        elif argument in ("-c", "--context"):
            pending = True
        elif argument.startswith("--context="):
            key, _, value = argument.removeprefix("--context=").partition("=")
            context[key] = value
    if pending:
        raise ConfigError("-c takes a key=value pair")
    return context


def main() -> None:
    # Under the CLI the output directory arrives in the environment; run
    # directly it would otherwise land in a temp dir nobody can inspect, so
    # default it to the same place the CLI uses.
    outdir = os.environ.get("CDK_OUTDIR") or "cdk.out"
    app = cdk.App(outdir=outdir, context=context_from_argv(sys.argv[1:]))
    build(app).synth()


if __name__ == "__main__":
    main()
