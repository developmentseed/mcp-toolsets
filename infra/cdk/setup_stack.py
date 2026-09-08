"""One-time setup: how GitHub gets into the account.

Deployed once, by a person with their own credentials, before any deploy runs.
It is the counterpart of the README's Kubernetes cluster setup, with one
difference worth the trouble: these permissions are code someone can review,
rather than console steps that drift from what the docs claim.

The account also needs the CDK toolkit bootstrapped once per region
(``cdk bootstrap``). That is a prerequisite this repo cannot do for you.
"""

from __future__ import annotations

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"

#: The audience GitHub's own action requests.
GITHUB_AUDIENCE = "sts.amazonaws.com"


class SetupStack(Stack):
    """A federated identity for one repository, and nothing else.

    No long-lived key exists at any point: the workflow exchanges a token
    GitHub mints for the run, and it expires with the run. That is the part
    that improves on a kubeconfig holding a token good for ninety days.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        repository: str,
        provider_arn: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]

        # The provider is one per account, not one per repository. A second
        # repository deploying into the same account must be given the existing
        # one, or the stack fails on a name collision that reads like anything
        # but its cause.
        if provider_arn:
            provider = iam.OpenIdConnectProvider.from_open_id_connect_provider_arn(
                self, "GitHubProvider", provider_arn
            )
        else:
            provider = iam.OpenIdConnectProvider(
                self,
                "GitHubProvider",
                url=GITHUB_OIDC_URL,
                client_ids=[GITHUB_AUDIENCE],
            )

        role = iam.Role(
            self,
            "DeployRole",
            role_name=f"{construct_id}-deploy",
            description=f"Deploys {repository} into this account",
            assumed_by=iam.WebIdentityPrincipal(
                provider.open_id_connect_provider_arn,
                {
                    "StringEquals": {
                        f"{_host(GITHUB_OIDC_URL)}:aud": GITHUB_AUDIENCE,
                    },
                    # Scoped to this repository. Without the subject condition
                    # any repository on GitHub could assume this role.
                    "StringLike": {
                        f"{_host(GITHUB_OIDC_URL)}:sub": f"repo:{repository}:*",
                    },
                },
            ),
        )

        # A CDK deploy does its work through the roles `cdk bootstrap` created,
        # so this role needs to assume those and nothing more. Enumerating
        # service permissions instead would be both wider and wrong the first
        # time the stack grows a resource type.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[
                    self.format_arn(
                        service="iam", region="", resource="role", resource_name="cdk-*"
                    )
                ],
            )
        )
        # Reading the current image tags before a deploy, and writing the new
        # ones after it.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ssm:GetParameter",
                    "ssm:GetParameters",
                    "ssm:GetParametersByPath",
                    "ssm:PutParameter",
                ],
                resources=[
                    self.format_arn(
                        service="ssm",
                        resource="parameter",
                        resource_name="mcp-toolsets/*",
                    )
                ],
            )
        )

        CfnOutput(
            self,
            "DeployRoleArn",
            value=role.role_arn,
            description="Set as the MCP_AWS_ROLE secret in the repository",
        )
        CfnOutput(
            self,
            "OidcProviderArn",
            value=provider.open_id_connect_provider_arn,
            description=(
                "Pass to a second repository's setup stack rather than creating another"
            ),
        )


def _host(url: str) -> str:
    """The condition key prefix is the provider's host, without its scheme."""
    return url.removeprefix("https://")
