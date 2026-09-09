"""One stack per instance: every toolset, the index, and the chat.

The Helm target is a release per toolset, so a broken one fails its own job and
leaves the rest deployed. This is one stack, so a failed update rolls the whole
instance back to its last good state and blocks every deploy until the offending
toolset is fixed or reverted. That is the trade: a known-good instance as a
unit, rather than a set of services that can drift apart.

Removing a toolset directory removes its service here on the next deploy, which
is what replaces the Helm target's reconcile job.
"""

from __future__ import annotations

from aws_cdk import Duration, Stack, Tags
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as route53_targets
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_servicediscovery as servicediscovery
from aws_cdk import aws_ssm as ssm
from aws_cdk import CfnOutput
from constructs import Construct

from infra.cdk.config import (
    CHAT_PORT,
    TOOLSET_PORT,
    TOOLSET_TAG,
    Deployment,
    Toolset,
    listener_priorities,
)

#: Rules are evaluated in priority order, and the chat is matched by host, so
#: it is tried before any of the per-toolset path rules.
CHAT_RULE_PRIORITY = 1

#: Long enough not to cut a streamed MCP response short.
IDLE_TIMEOUT = Duration.minutes(30)

#: Names the image, the build's dependency group and the tag map's key, so the
#: three cannot drift apart.
INDEX_COMPONENT = "index-aws"


class ToolsetsStack(Stack):
    """Every service one instance of this repo runs."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment: Deployment,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]
        self.deployment = deployment

        self.vpc = self._network()
        self.cluster = self._cluster()
        self.registry_credentials = self._registry_credentials()
        self.load_balancer = elbv2.ApplicationLoadBalancer(
            self,
            "LoadBalancer",
            vpc=self.vpc,
            internet_facing=True,
            idle_timeout=IDLE_TIMEOUT,
        )
        self.zone = self._hosted_zone()
        self.listener = self._listener()

        self.index_service = self._index()
        priorities = listener_priorities(
            toolset.name for toolset in deployment.toolsets
        )
        for toolset in deployment.toolsets:
            self._toolset(toolset, priorities[toolset.name])
        self._chat()
        self._records()

        CfnOutput(
            self,
            "LoadBalancerDns",
            value=self.load_balancer.load_balancer_dns_name,
            description="Point a DNS record here when the stack does not manage DNS",
        )
        CfnOutput(self, "PublicUrl", value=self._public_url, description="Index URL")

    # --- the parts a deployment is assembled from ------------------------

    def _network(self) -> ec2.IVpc:
        """Build a network, or adopt the one we were handed.

        Both paths avoid an environment lookup, so synthesis needs no account —
        which is why the subnets arrive with their availability zones rather
        than being discovered from their ids.
        """
        network = self.deployment.network
        if network.bring_your_own:
            return ec2.Vpc.from_vpc_attributes(
                self,
                "Vpc",
                vpc_id=str(network.vpc_id),
                availability_zones=list(network.availability_zones),
                public_subnet_ids=list(network.subnet_ids),
            )
        # Public subnets and no gateway: tasks reach the registry directly and
        # the instance costs no idle gateway. Security groups are what keep
        # them unreachable except through the load balancer.
        return ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                )
            ],
        )

    def _cluster(self) -> ecs.Cluster:
        """The cluster, and the private namespace services register in.

        That registration is how the index reaches a toolset and how it builds
        each address, so it is not optional decoration.
        """
        return ecs.Cluster(
            self,
            "Cluster",
            vpc=self.vpc,
            cluster_name=self.deployment.instance,
            default_cloud_map_namespace=ecs.CloudMapNamespaceOptions(
                name=f"{self.deployment.instance}.internal",
                type=servicediscovery.NamespaceType.DNS_PRIVATE,
                use_for_service_connect=False,
            ),
        )

    def _registry_credentials(self) -> secretsmanager.ISecret | None:
        """The one long-lived credential in this target, and nothing rotates it.

        Only needed for a private repository; a public one pulls without it.
        """
        arn = self.deployment.registry_secret_arn
        if not arn:
            return None
        return secretsmanager.Secret.from_secret_complete_arn(self, "RegistryPull", arn)

    def _hosted_zone(self) -> route53.IHostedZone | None:
        domain = self.deployment.domain
        if not domain.manages_dns:
            return None
        return route53.HostedZone.from_hosted_zone_attributes(
            self,
            "Zone",
            hosted_zone_id=str(domain.hosted_zone_id),
            zone_name=str(domain.host),
        )

    @property
    def chat_host(self) -> str | None:
        """The hostname the chat answers on, or ``None`` if there is no chat.

        One predicate for three questions — the certificate's second name, the
        listener rule, and the DNS record — because they have to agree. They
        did not: a record was written for a host with no service behind it,
        which resolves and lands on the index.
        """
        if not self.deployment.chat.enabled:
            return None
        return self.deployment.domain.resolved_chat_host

    def _certificate(self) -> acm.ICertificate | None:
        """Issue one against the zone, or adopt the one we were given.

        The chat rides along as a second name rather than taking a certificate
        of its own, which is why its hostname has to be known now rather than
        later.
        """
        domain = self.deployment.domain
        if domain.certificate_arn:
            return acm.Certificate.from_certificate_arn(
                self, "Certificate", domain.certificate_arn
            )
        if self.zone is None:
            return None
        chat_host = self.chat_host
        return acm.Certificate(
            self,
            "Certificate",
            domain_name=str(domain.host),
            subject_alternative_names=[chat_host] if chat_host else None,
            validation=acm.CertificateValidation.from_dns(self.zone),
        )

    def _listener(self) -> elbv2.ApplicationListener:
        """The single entry point every service hangs off.

        Port 80 is always the same construct, whether it serves the services or
        redirects to 443. That is not tidiness: adding a domain to a running
        instance otherwise asks CloudFormation to create a second listener on a
        port the first one still holds, and the update fails on a conflict that
        reads like a name clash rather than a change of shape.

        With a certificate, plain HTTP becomes a redirect rather than a second
        way in — the load balancer does that itself, so nothing here replaces
        that part of an ingress.
        """
        certificate = self._certificate()
        http = self.load_balancer.add_listener(
            "Http",
            port=80,
            open=True,
            protocol=elbv2.ApplicationProtocol.HTTP,
            default_action=(
                elbv2.ListenerAction.redirect(
                    protocol="HTTPS", port="443", permanent=True
                )
                if certificate
                else None
            ),
        )
        if certificate is None:
            return http
        return self.load_balancer.add_listener(
            "Https",
            port=443,
            open=True,
            protocol=elbv2.ApplicationProtocol.HTTPS,
            certificates=[certificate],
        )

    # --- the services ----------------------------------------------------

    def _service(
        self,
        identifier: str,
        component: str,
        cpu: int,
        memory: int,
        port: int,
        environment: dict[str, str],
        command: list[str] | None = None,
        secrets: dict[str, str] | None = None,
        grace: Duration | None = None,
    ) -> ecs.FargateService:
        """One Fargate service, registered in Cloud Map under its own name."""
        task_definition = ecs.FargateTaskDefinition(
            self,
            f"{identifier}Task",
            cpu=cpu,
            memory_limit_mib=memory,
            # Stated rather than defaulted, because the images decide it: CI
            # builds on x86 runners. An arm64 image built by hand on a Mac
            # fails here as `exec format error`, which names the symptom and
            # not the cause.
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.X86_64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )
        task_definition.add_container(
            identifier,
            image=ecs.ContainerImage.from_registry(
                self.deployment.image(component), credentials=self.registry_credentials
            ),
            command=command,
            environment=environment,
            secrets={
                name: ecs.Secret.from_ssm_parameter(
                    ssm.StringParameter.from_secure_string_parameter_attributes(
                        self, f"{identifier}Secret{index}", parameter_name=path
                    )
                )
                for index, (name, path) in enumerate(sorted((secrets or {}).items()))
            },
            port_mappings=[ecs.PortMapping(container_port=port)],
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix=f"mcp-{component}",
                log_retention=logs.RetentionDays.ONE_MONTH,
            ),
        )
        return ecs.FargateService(
            self,
            f"{identifier}Service",
            cluster=self.cluster,
            task_definition=task_definition,
            desired_count=1,
            # No gateway, so a task needs an address of its own to pull its
            # image. The security group is what keeps it private.
            assign_public_ip=not self.deployment.network.bring_your_own,
            cloud_map_options=ecs.CloudMapOptions(name=f"mcp-{component}"),
            # How long a new task may fail its load balancer check before ECS
            # gives up on it. `None` keeps the library's 60s, which is ample
            # for a toolset that serves the moment it starts; a service that
            # connects to something else first needs longer, or its own startup
            # is read as a failed deploy.
            health_check_grace_period=grace,
            # A task inherits nothing by default, so without this the running
            # thing — the one that appears in a cost report and the one someone
            # finds when asking who owns this — is the only untagged part of
            # the deployment.
            propagate_tags=ecs.PropagatedTagSource.SERVICE,
            # Adds the cluster and service names AWS maintains itself, which is
            # what cost allocation groups by.
            enable_ecs_managed_tags=True,
            # Makes the all-or-nothing contract automatic rather than a stuck
            # update waiting for someone to notice.
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            # Start the replacement before stopping what it replaces, so one
            # task is no downtime. Stated rather than defaulted: the library
            # warns that its own default is changing, and this is the
            # behaviour the deployment contract above assumes.
            min_healthy_percent=100,
            max_healthy_percent=200,
        )

    def _toolset(self, toolset: Toolset, priority: int) -> None:
        """A toolset, answering under its own path on the shared host.

        The path prefix is why this works behind a load balancer at all: the
        request arrives unrewritten, so the toolset has to serve the path it is
        published at.
        """
        environment = {
            "TOOLSET": toolset.name,
            # Binding every interface is what a container does: the network
            # namespace is the boundary, and the chart sets the same.
            "HOST": "0.0.0.0",  # noqa: S104
            "PORT": str(TOOLSET_PORT),
            "MCP_PATH_PREFIX": toolset.path_prefix,
            **toolset.env,
        }
        service = self._service(
            _identifier(toolset.name),
            toolset.name,
            cpu=toolset.cpu,
            memory=toolset.memory,
            port=TOOLSET_PORT,
            environment=environment,
            secrets=toolset.secrets,
        )
        # What the index selects on. Without it a running toolset is invisible.
        Tags.of(service).add(TOOLSET_TAG, toolset.name)

        # Every service gets its own security group, and the load balancer is
        # the only thing allowed in by default. In a cluster, pods talk to each
        # other freely and this rule has no equivalent — here, without it, the
        # index lists a toolset it cannot reach and reports it unreachable.
        service.connections.allow_from(
            self.index_service,
            ec2.Port.tcp(TOOLSET_PORT),
            "the index asks each toolset what tools it has",
        )

        self.listener.add_targets(
            f"{_identifier(toolset.name)}Target",
            port=TOOLSET_PORT,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[service],
            priority=priority,
            conditions=[
                elbv2.ListenerCondition.path_patterns(
                    [toolset.path_prefix, f"{toolset.path_prefix}/*"]
                )
            ],
            # The root health route, which the runtime keeps answering
            # alongside the prefixed one precisely so a check below the routing
            # has somewhere to look.
            health_check=elbv2.HealthCheck(path="/health", healthy_http_codes="200"),
        )

    def _index(self) -> ecs.FargateService:
        """The directory, on the default rule: whatever no toolset claims.

        Its image is `mcp-index-aws`, not `mcp-index`: the cluster's index
        discovers over the Kubernetes API and this one needs the runtime's AWS
        extra, so they are different images. Sharing a name would mean two
        workflows pushing different content to one tag, and whichever finished
        last would decide what a deploy ran.
        """
        service = self._service(
            "Index",
            INDEX_COMPONENT,
            cpu=256,
            memory=512,
            port=TOOLSET_PORT,
            command=["mcp-index"],
            environment={
                "PUBLIC_URL": self._public_url,
                "HOST": "0.0.0.0",  # noqa: S104
                "PORT": str(TOOLSET_PORT),
                "MCP_INDEX_DISCOVERY": "ecs",
                "MCP_ECS_CLUSTER": self.cluster.cluster_name,
            },
        )
        service.task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                # ListServices takes the cluster as a parameter rather than a
                # resource, so it cannot be scoped further.
                actions=["ecs:ListServices"],
                resources=["*"],
            )
        )
        service.task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=["ecs:DescribeServices"],
                resources=[
                    self.format_arn(
                        service="ecs",
                        resource="service",
                        resource_name=f"{self.cluster.cluster_name}/*",
                    )
                ],
            )
        )
        service.task_definition.add_to_task_role_policy(
            iam.PolicyStatement(
                # How a registration becomes a name the network resolves.
                actions=[
                    "servicediscovery:GetService",
                    "servicediscovery:GetNamespace",
                ],
                resources=["*"],
            )
        )
        self.listener.add_targets(
            "IndexTarget",
            port=TOOLSET_PORT,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[service],
            health_check=elbv2.HealthCheck(path="/health", healthy_http_codes="200"),
        )
        return service

    def _chat(self) -> None:
        """The hosted chat, on a host of its own.

        Host rather than path: it is a browser app serving its own assets, and
        it holds conversations in the task's memory — hence one task and sticky
        sessions, matching the chart's single replica.

        Skipped without a domain, because a hostname is the only way to route
        to it, and skipped without a model, because the model is what it costs
        money to answer on. Neither is a misconfiguration; both are the default
        for a deployment that has not asked for a chat.
        """
        chat_host = self.chat_host
        chat = self.deployment.chat
        if not chat_host:
            return
        namespace = f"{self.deployment.instance}.internal"
        service = self._service(
            "Chat",
            "chat",
            cpu=512,
            memory=1024,
            port=CHAT_PORT,
            # Nothing answers on this port until the agent has connected to
            # every toolset — uvicorn opens the socket after the lifespan, so
            # the check is refused rather than answered 503 until then.
            grace=Duration.minutes(3),
            environment={
                # The index registers under its component name, so this has to
                # be derived rather than written out: naming it by hand is how
                # renaming the component broke this link once already.
                "MCP_URL": f"http://mcp-{INDEX_COMPONENT}.{namespace}:{TOOLSET_PORT}/",
                "PROVIDER_MODEL": chat.model,
                **chat.environment(),
            },
            # Read at task start, never in the template: a key passed as
            # context would be in CloudFormation, readable by anyone who can
            # describe the stack.
            secrets={
                "PROVIDER_API_KEY": chat.parameter(self.deployment.parameter_prefix)
            },
        )
        # The chat reads the directory over the same closed network.
        self.index_service.connections.allow_from(
            service,
            ec2.Port.tcp(TOOLSET_PORT),
            "the chat reads the directory",
        )
        self.listener.add_targets(
            "ChatTarget",
            port=CHAT_PORT,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[service],
            priority=CHAT_RULE_PRIORITY,
            conditions=[elbv2.ListenerCondition.host_headers([chat_host])],
            stickiness_cookie_duration=Duration.hours(8),
            # Readiness, not the page: both answer only once the agent is
            # built, but "/" would also answer 200 from a deployment serving a
            # page with no agent behind it, and this check exists to say the
            # task can answer questions.
            health_check=elbv2.HealthCheck(
                path="/health/readiness",
                healthy_http_codes="200",
                interval=Duration.seconds(30),
            ),
        )

    def _records(self) -> None:
        """Point both hostnames at the load balancer, when we own the zone."""
        if self.zone is None:
            return
        target = route53.RecordTarget.from_alias(
            route53_targets.LoadBalancerTarget(self.load_balancer)
        )
        route53.ARecord(self, "IndexRecord", zone=self.zone, target=target)
        chat_host = self.chat_host
        if chat_host:
            route53.ARecord(
                self,
                "ChatRecord",
                zone=self.zone,
                record_name=chat_host,
                target=target,
            )

    @property
    def _public_url(self) -> str:
        return self.deployment.domain.public_url(
            self.load_balancer.load_balancer_dns_name
        )


def _identifier(name: str) -> str:
    """A construct id from a kebab-case toolset name."""
    return "".join(part.capitalize() for part in name.split("-"))
