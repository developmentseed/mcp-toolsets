# mcp-toolsets

A template monorepo of **toolsets** — small packages of
[LangChain](https://python.langchain.com) tools — each auto-deployed as its own
[MCP](https://modelcontextprotocol.io) service. Toolset implementors write a
single Python module; a shared runtime, one parameterized Dockerfile and one
deployment target handle everything else.

It deploys to:

  <!-- target:k8s -->
- **Kubernetes** — one generic Helm chart, a release per toolset.
  <!-- /target:k8s -->
  <!-- target:aws -->
- **AWS, without EKS** — ECS on Fargate, one CDK stack for the instance.
  <!-- /target:aws -->
<!-- target:both -->

Both are here. `./scripts/bootstrap` keeps whichever you choose and removes the
other, so an instance carries one deployment story rather than two.
<!-- /target:both -->

The runtime is not in this repo. It is
[**mcp-toolsets-runtime**](https://github.com/developmentseed/mcp-toolsets-runtime),
installed from PyPI like any other dependency — which makes this repo the
worked example of consuming it: what a toolset exports, how views are built and
served, and how the whole thing deploys. See
[The runtime dependency](#the-runtime-dependency).

<!-- target:k8s -->
```
toolsets/<name>/tools.py  ──▶  ghcr.io/<owner>/<repo>/mcp-<name>  ──▶  k8s Service mcp-<name>
   (LangChain @tool fns)        (Dockerfile --build-arg TOOLSET=...)     (infra/k8s/charts)
```
<!-- /target:k8s -->
<!-- target:aws -->
```
toolsets/<name>/tools.py  ──▶  ghcr.io/<owner>/<repo>/mcp-<name>  ──▶  Fargate service mcp-<name>
   (LangChain @tool fns)        (Dockerfile --build-arg TOOLSET=...)     (infra/cdk)
```
<!-- /target:aws -->

Terminology: a **tool** is a single LangChain `@tool` function; a **toolset**
is a directory under `toolsets/` exporting a `TOOLS` list, deployed as one MCP
server.

## Use this template

This repository is a GitHub template — click **Use this template** to create
your own. The image registry path is derived from your repo name automatically;
what you set is where the toolsets deploy:

1. **Bootstrap once — do this first.** `./scripts/bootstrap` is the intended
   first step after creating your repo. It:

   <!-- target:both -->
   - asks for the **deployment target**, Kubernetes or AWS, and removes the
     other one — its workflow, its directory under `infra/`, its dependency
     groups, its config file in every toolset, and its half of these docs. That
     is a change to the working tree for you to commit, not a setting;
   <!-- /target:both -->
   <!-- target:k8s -->
   - sets the **`MCP_NAMESPACE`** repo Actions variable (the namespace your
     toolsets deploy into) via `gh` — **deploys are skipped until this is set**;
   - **rewrites the `__MCP_NAMESPACE__` placeholders** in `README.md` and
     `CLAUDE.md` in place, so the cluster-setup commands below become
     copy-pasteable for your namespace;
   <!-- /target:k8s -->
   <!-- target:aws -->
   - sets the **`MCP_AWS_INSTANCE`** and **`MCP_AWS_REGION`** repo Actions
     variables (the stack's name, and the region it deploys into) via `gh` —
     **deploys are skipped until both of those and the `MCP_AWS_ROLE` secret
     are set**;
   <!-- /target:aws -->
   - optionally removes the shipped example toolsets.

   <!-- target:k8s -->
   ```sh
   ./scripts/bootstrap            # prompts for everything it needs
   # or non-interactively:
   ./scripts/bootstrap --target k8s my-namespace --keep-examples
   ```
   <!-- /target:k8s -->
   <!-- target:aws -->
   ```sh
   ./scripts/bootstrap            # prompts for everything it needs
   # or non-interactively:
   ./scripts/bootstrap --target aws my-instance --region eu-west-2 --keep-examples
   ```
   <!-- /target:aws -->

   Re-running is safe, and refuses to prune a target you are already on. The
   deploy settings live only in repo variables, not committed files, so they
   never carry over to repos generated from your instance. If `gh` isn't set up
   when you bootstrap, the script prints the commands to set them yourself.
   <!-- target:k8s -->
   The `__MCP_NAMESPACE__` placeholders then stay literal until you re-run
   bootstrap or edit them by hand.
   <!-- /target:k8s -->

2. **Develop** — `uv sync`, then add a toolset (`uv run mcp-toolset new`) or play
   with the shipped `hello` example (see [Quickstart](#quickstart)).

   <!-- target:k8s -->
3. **Deploy when ready** — set the `KUBE_CONFIG` secret (see
   [Kubernetes cluster setup](#kubernetes-cluster-setup)). Until you do, CI runs
   lint/tests/build on every push but **skips the deploy** — a fresh instance is
   green out of the box, with no cluster required.
   <!-- /target:k8s -->
   <!-- target:aws -->
3. **Deploy when ready** — run the setup stack and set the `MCP_AWS_ROLE` secret
   (see [AWS: ECS on Fargate](#aws-ecs-on-fargate-without-eks)). Until you do,
   CI runs lint/tests/synth on every push but **skips the deploy** — a fresh
   instance is green out of the box, with no AWS account required.
   <!-- /target:aws -->

The repo ships two example toolsets you can keep, copy or delete: `hello` (the
smallest thing that deploys) and `credential-demo` (the
[per-user credentials](#per-user-credentials) pattern).

## The runtime dependency

[![PyPI](https://img.shields.io/pypi/v/mcp-toolsets-runtime?label=mcp-toolsets-runtime)](https://pypi.org/project/mcp-toolsets-runtime/)

Everything that isn't a toolset comes from one PyPI package,
[`mcp-toolsets-runtime`](https://github.com/developmentseed/mcp-toolsets-runtime),
bounded in the root `pyproject.toml` and pinned exactly by `uv.lock`. Below is
what you reach for from *this* repo and when; the package's own README is the
authority on everything it exposes, and stays current when this doesn't:

| Module | What you use it for here |
| --- | --- |
| `mcp_runtime` | **Required.** Serves a toolset's `TOOLS` as a stateless streamable-HTTP MCP server with a `/health` route for k8s probes, and its `VIEWS` as `ui://` resources — `mcp-serve` for one toolset, `mcp-serve-local` for all of them at once. Also runs the directory service (`mcp-index`). |
| `mcp_cli` | **Development inner loop.** Typer/rich client (`mcp-cli`) to list and call tools on a running service. |
| `mcp_toolset` | **Scaffolding.** `mcp-toolset new [--with-ui] <name>` writes a conforming toolset into `toolsets/` and registers it in the workspace. |
| `mcp_agent` | **The agent.** Discovers every server behind an index URL and drives their tools — `mcp-agent` is an interactive terminal chat, and `build_agent`/`run_turn` are the same thing for a host of your own. |
| `mcp_agent_api` | **The hosted chat.** That agent over HTTP as [AG-UI](https://github.com/ag-ui-protocol/ag-ui) events, plus the web client that renders them — streamed answers, tool calls as they run, receipts beside them, and a session-state panel. The client ships inside the wheel, so `Dockerfile.chat` runs `uvicorn` and builds no frontend. Needs the `[api]` extra, which is what the root pin takes. |
| `mcp_state` | **Already working on these toolsets, untagged.** It keeps large tool values out of the model's context. Every `ToolResult` data key is declared in the tool's `_meta` and captured into session state by the bundled agent, whether or not you tag anything. Tagging a parameter `NotAuthored` is the accelerator on top — see below. |

[session-state]: https://github.com/developmentseed/mcp-toolsets-runtime/blob/main/docs/SESSION-STATE.md

Upgrade with `uv lock --upgrade-package mcp-toolsets-runtime`; because `uv.lock`
is a shared build input, merging the bump rebuilds and redeploys every toolset.
Fix runtime behaviour upstream and release it — never patch it here, since
nothing local would survive the next `uv sync`.

This repo owns `toolsets/*` — one directory per toolset, each becoming an MCP
service — `infra/*` (the deployment target's own code), the `Dockerfile`, the
workflows, and `tests/test_contract.py`.

### Session state, and what tagging `NotAuthored` adds

Nothing here opts in explicitly, and the mechanism still runs: `search_collections`
advertises `stac-explorer/search_collections/collections` in its `_meta`, and
driving it from the bundled agent moves that list into session state instead of
the transcript. Best endeavours is the default, so an untagged toolset already
gets the context saving.

A state key is three parts — `<toolset>/<tool>/<field>` — and it is the whole
contract. There is no type to agree on: the producer names the value, and a
consumer that wants it names the same key. Which also means the key is a
**public name**, changeable only the way any published identifier is.

What tagging a parameter `NotAuthored` adds is a *constraint*, not a type. It
says one thing — a model must not write this value — and an `mcp_state` client
narrows the parameter until the only thing it accepts is a reference to a value
some tool already produced. A client that has never heard of the tag still gets
the sentence appended to the parameter's description, and mostly obeys it; one
that ignores `_meta` entirely sees a normal parameter and is no worse off than
before.

What the model writes either way is an `@state:<key>` handle rather than the
value, so the chat's tool step annotates the handle with what the key resolved
to — which the bare string does not say:

```
request: @state:stac-explorer/search_collections/collections · 12 item(s) · from search_collections · query written by the model
```

That last clause is the provenance: the call that produced this value was given
`query` by the model rather than from state, and a reader deciding how much to
trust the result wants to know it.

None of this is visible in this repo yet, and the reason is not tagging. The
`@state:<key>` form is only offered on `object` and `array` parameters, whereas
every tool here takes scalars — `hello(name)`, `whoami()`,
`search_collections(query, limit)`, `show_map(collection_id)`. A tool taking a
structured parameter would light up the handle path on its own, without tagging
anything.

Two consequences worth knowing before you read a deployment. `/health` and the
index report `state.produces` as one entry per published data key — `{tool,
field, state_key}` — so `stac-explorer` lists three and `hello` lists none;
alongside it `state.not_authored` is `[]` here, which means "nothing is tagged",
not "nothing is captured". And the guarantee is about what reaches the *model*,
not about what leaves the process: LangChain hands every tool call the whole
agent state, so a tracing backend wired to the chat records stored payloads on
every subsequent call. That is upstream behaviour, unrelated to whether you use
session state at all, but it is the wrong thing to discover after turning
tracing on.

Keeping values out of the context is client-side work, so external hosts do none
of it — served to Claude.ai or ChatGPT, these toolsets behave like any other, and
tool returns still have to be a sensible size on their own. The full contract,
with sequence diagrams and a runnable demo, is in the runtime's
[SESSION-STATE.md][session-state].

## Quickstart

```sh
uv sync                # runtime from PyPI + every toolset, into one .venv
./scripts/test         # run all tests
./scripts/lint         # ruff + mypy (./scripts/format to autofix)

# Serve every toolset in one process, with the index at /
uv run mcp-serve-local

# ...or a single toolset on its own, the way production runs it
TOOLSET=hello uv run mcp-serve

# Talk to them from another shell
uv run mcp-cli list --url http://localhost:8000/hello/mcp
uv run mcp-cli call hello name=dev --url http://localhost:8000/hello/mcp
uv run mcp-cli repl --url http://localhost:8000/hello/mcp
uv run mcp-cli call whoami \
  --url http://localhost:8000/credential-demo/mcp -H "X-Demo-Token: s3cret"
```

`mcp-serve-local` mounts each toolset at `/<name>/mcp` and serves the index
document at `/` — the same URL shape the shared domain has in production, so an
`mcp-cli`, an `mcp-agent` or an MCP Inspector session can be pointed at it
unchanged. Use it for the inner loop; reach for `mcp-serve` when you want a
toolset isolated exactly as its own pod runs it (one process, one toolset,
`/mcp` at the root, `PORT` to move it).

`mcp-cli` defaults to `http://localhost:8000/mcp`, which is where a bare
`mcp-serve` puts a toolset — hence the explicit `--url` above. Toolsets are also
importable directly (e.g. `from hello.tools import TOOLS`) for in-process use in
tests, notebooks or an agent repo.

## Adding a toolset

No Docker, Kubernetes or MCP knowledge needed — write ordinary LangChain
tools and merge.

1. Scaffold with the runtime's generator (registers the package in the uv
   workspace too):

   ```sh
   uv run mcp-toolset new my-toolset
   ```

2. Write your tools in `toolsets/my-toolset/src/my_toolset/tools.py`:

   ```python
   from typing import Any, NotRequired

   from langchain_core.tools import tool

   from mcp_runtime.tool_result import ToolError, ToolResult

   class DoSomethingResult(ToolResult):
       """Matches for the query, each with an 'id' and a 'score'."""

       matches: NotRequired[list[dict[str, Any]]]

   @tool
   def do_something(query: str, limit: int = 10) -> DoSomethingResult | ToolError:
       """One-line description — docstrings and type hints ARE the MCP schema."""
       ...
       return DoSomethingResult(message=f"Found {len(matches)} match(es).", matches=matches)

   TOOLS = [do_something]
   ```

   `TOOLS` is the only required export. Non-empty docstrings and the
   [ToolResult return contract](#typed-tool-returns) are enforced by a
   contract test. If a tool does I/O (HTTP, database), write it as
   `async def` — `@tool` supports coroutines natively; sync tools are fine
   for pure computation (the runtime runs them in a thread pool). If a tool
   needs the *user's* credentials, read them from the request headers — see
   [Per-user credentials](#per-user-credentials). The shipped `hello` toolset
   is a minimal starting point you can copy.

3. Add tests in `toolsets/my-toolset/tests/test_my_toolset.py` and run
   `./scripts/test`.

   <!-- target:k8s -->
4. (Optional) `toolsets/my-toolset/toolset.yaml` holds Helm value overrides —
   secrets to mount via `envFrom`, env vars, resources, replicas. See
   `infra/k8s/charts/mcp-toolset/values.yaml` for the available keys.
   <!-- /target:k8s -->
   <!-- target:aws -->
4. (Optional) `toolsets/my-toolset/toolset.aws.yaml` holds the service's
   overrides — task size, env vars, and secrets named one Parameter Store path
   at a time. See
   [Per-toolset configuration](#per-toolset-configuration).
   <!-- /target:aws -->

5. Merge to `main`. CI builds `ghcr.io/<owner>/<repo>/mcp-my-toolset` and
   deploys the `mcp-my-toolset` service automatically.

Conventions: directory `toolsets/<name>` (kebab-case) → module
`<name_snake_case>.tools` → service `mcp-<name>`.

## Typed tool returns

Every tool returns one dict per call, in one of two shapes from
`mcp_runtime.tool_result`:

- **`ToolResult`** — success: a required str `message` (the human-readable
  answer a model or UI reads first) plus any data keys your tool declares.
- **`ToolError`** — a structured error: a short machine-readable `error`
  kind and a `detail` saying what happened or what to do next.

The runtime derives each tool's MCP `outputSchema` from its return
annotation, advertises it in `tools/list`, validates every result against it
before sending, and delivers results as typed `structuredContent` (alongside
the usual text block). A tool whose annotation doesn't follow the contract
**fails at startup** (`build_server` aborts, naming the tool) and fails the
contract test in CI — never silently at chat time.

How to annotate:

- Minimum: `-> ToolResult | ToolError` for tools whose message is the whole
  answer (drop the `ToolError` arm if the tool raises instead of returning
  errors — exceptions become MCP `isError` results, which skip schema
  validation).
- Recommended: one `ToolResult` subclass per tool, adding each data key as
  `NotRequired[...]`, annotated `-> MyResult | ToolError`. Give the subclass
  a one-line docstring — it becomes the schema's `description`. Nested
  payloads can be TypedDicts or pydantic models all the way down.
- Construct returns with TypedDict call syntax —
  `ToolResult(message=...)`, `ToolError(error="not_found", detail=...)` —
  mypy-checked, still a plain dict at runtime. `is_error()` (a `TypeIs`
  guard) narrows helper results typed `dict[str, Any] | ToolError` in both
  branches.

Rules and gotchas:

- Keys not declared in the annotation are silently dropped from
  `structuredContent` — the annotation is the complete list of keys a client
  can see, and mypy flags undeclared keys in return literals.
- Arguments are the mirror image: since runtime 0.8.1 a parameter the tool
  doesn't declare is a validation error naming it, not a silently ignored
  argument, and the published input schema says so with
  `additionalProperties: false`.
- Union arms must all be TypedDicts/pydantic models; bare `str`/`list`
  returns and `dict[str, Any]` are rejected at startup (FastMCP would wrap
  the former in `{"result": ...}`, changing your payload shape; the latter
  guarantees nothing). Put data under a named key instead.
- The annotation must be on the function `@tool` wraps; the runtime reads it
  via `tool.coroutine`/`tool.func`.

Verify locally: `TOOLSET=my-toolset uv run mcp-serve`, then `tools/list`
(via MCP Inspector or `mcp-cli`) shows each tool's `outputSchema`, and
`tools/call` responses carry `structuredContent`.


## Toolset UI views

A tool can ship a **view**: a small frontend component (a map, a gallery, a
chart) that an MCP Apps host — Claude, ChatGPT, or this repo's own hosted chat —
renders in a sandboxed iframe and feeds the tool's `structuredContent`. The runtime stays pure-Python: a view is a build-time HTML
bundle served as an MCP resource; nothing new executes at call time. Views are
**progressive enhancement** — the tool's `message` and structured data still
stand alone in a plain client, so a view never changes what a tool returns.

Scaffold a toolset with an example view, then build it (needs node):

```sh
uv run mcp-toolset new --with-ui my-toolset
cd toolsets/my-toolset/ui && npm install && npm run build
```

### The contract

A toolset opts in with three things, validated at startup — a missing bundle,
or a view naming an unknown tool, aborts `build_server`:

1. **`VIEWS`** — a `{tool_name: view_id}` export in the tools module.
2. **A built bundle** at `<package>/views/<view_id>.html`, self-contained (all
   JS/CSS inlined). The shipped `ui/` builds these with Vite +
   `vite-plugin-singlefile`, one pass per view (`VIEW=<id> vite build`), writing
   into the package's `views/` dir. Built bundles are git-ignored; the
   Dockerfile's node stage and `./scripts/build-views` rebuild them.
3. **The host bridge** — [`@developmentseed/mcp-view`][mcp-view], the npm half of
   the runtime. It wraps the MCP Apps `ui/*` postMessage protocol in two
   functions, so a view never hand-rolls the wire format:

   ```ts
   import { onData, sendMessage } from "@developmentseed/mcp-view";

   onData<MyResult>((data) => render(data));  // the tool's structuredContent
   button.onclick = () => sendMessage("…");   // a user turn back into the chat
   ```

   Any framework works; only this seam is fixed. Add it to your `ui/`
   dependencies — it's a public package, so no registry auth here or in CI.

Given that, the runtime does two standard-MCP things: it serves each view as a
resource `ui://<toolset>/<view_id>` and stamps the owning tool's `_meta` with
that URI. Because that follows the [MCP Apps][ext-apps] standard, any MCP Apps
host renders the same bundle unchanged — Claude, ChatGPT, Goose, VS Code — and
so does the hosted chat, whose transcript opens each view in a frame and speaks
the host end of the identical protocol.

[mcp-view]: https://www.npmjs.com/package/@developmentseed/mcp-view
[ext-apps]: https://github.com/modelcontextprotocol/ext-apps

### Credentials never reach the iframe

A view can do exactly as much as what the tool put in its `ToolResult`: pass
**pre-signed or short-lived URLs** (tiles, thumbnails), never tokens. The
[per-user credential](#per-user-credentials) invariant is unchanged — secrets
ride the MCP transport as headers, never the conversation or the iframe. For an
authenticated data source, the tool mints a signed URL server-side and returns
it in the result.

### Interactions advance the chat

A view is an input device, not just a picture: an interaction calls
`sendMessage(...)`, which arrives back as a user message, so the model reads it
and calls the next tool. `toolsets/stac-explorer` is a worked example — a
collection gallery whose "Show on map" button drives a second tool that renders
the selected data on a map.

### Viewing them in the hosted chat

Nothing to install. The client the runtime serves is an MCP Apps host itself:
when a tool that declares a view is called, the receipt for that call carries
the `ui://` URI, and the transcript fetches the bundle from the API and hands
it the tool's structured content. A view's `sendMessage(...)` starts the next
turn, exactly as it would in Claude.

## Removing a toolset

```sh
./scripts/remove-toolset my-toolset
```

Merge to `main`. Removal is GitOps like everything else: the deploy reconciles
what is running against `toolsets/`, and the index drops the entry
automatically. Mind that this means merging a deleted directory tears down the
live service.

<!-- target:k8s -->
The workflow uninstalls any `mcp-<name>` release whose directory no longer
exists — Deployment, Service and Ingress with it.

Not removed automatically: out-of-band Secrets the toolset listed in its
`toolset.yaml` (`kubectl -n __MCP_NAMESPACE__ delete secret <name>`) and its
images in GHCR (delete the package from the repo settings if you care).
<!-- /target:k8s -->
<!-- target:aws -->
The stack stops synthesising that service, so the next deploy takes it away
along with its listener rule and its Cloud Map registration.

Not removed automatically: Parameter Store values the toolset listed in its
`toolset.aws.yaml` (`aws ssm delete-parameter --name <path>`), its image-tag
parameter under `/mcp-toolsets/<instance>/<name>/`, and its images in GHCR
(delete the package from the repo settings if you care).
<!-- /target:aws -->

## Deployment

- **ci.yml** (PRs + main): lint, tests, a check of the deployment target, and a
  no-push Docker build of each image the change affects — the toolsets it
  selects, plus the index and the chat, which no toolset change selects but
  every shared input rebuilds. Always runs, against nothing deployed.
  <!-- target:k8s -->
  The target's own check is `helm lint` over both charts.
  <!-- /target:k8s -->
  <!-- target:aws -->
  The target's own check is a `cdk synth` of every shape the stack deploys in,
  and the stack's tests. Synthesis reaches for no account, which is what lets a
  pull request check the infrastructure with no credentials attached.
  <!-- /target:aws -->
  <!-- target:k8s -->
- **deploy.yml** (main): detects changed toolsets (`scripts/changed-toolsets`)
  — changes to shared build inputs (`infra/`, `Dockerfile`, `uv.lock`, root
  `pyproject.toml`) rebuild *all* toolsets, which is how a runtime version bump
  reaches every service — then per toolset: build and push
  `ghcr.io/<owner>/<repo>/mcp-<name>:<sha>` and
  `helm upgrade --install mcp-<name> infra/k8s/charts/mcp-toolset -n __MCP_NAMESPACE__`.
  A reconcile job also uninstalls releases whose `toolsets/<name>` directory
  is gone — see [Removing a toolset](#removing-a-toolset).
- **Deploy guard**: the cluster-touching jobs are skipped unless **both** the
  `KUBE_CONFIG` secret and the `MCP_NAMESPACE` variable are set, so a freshly
  instantiated template never fails CI trying to reach a cluster that doesn't
  exist yet — and never deploys into an unintended namespace.
- **Required secret**: `KUBE_CONFIG` — a kubeconfig with rights to manage the
  deploy namespace. Images push to GHCR with the built-in `GITHUB_TOKEN`.
- **Required variable**: `MCP_NAMESPACE` — the namespace every release deploys
  into, set by `./scripts/bootstrap`. As a repo variable it stays per-instance,
  so two repos sharing a cluster don't collide.
- **Optional secret**: `MCP_INGRESS_HOST` — a shared hostname. When set, every
  toolset also gets an Ingress on that host at `/<name>`, and an `mcp-index`
  service (the same `Dockerfile` built with `TOOLSET=index`, which installs the
  runtime alone; deployed via `infra/k8s/charts/mcp-index`) serves a directory of all
  toolsets at the domain root — see
  [Kubernetes cluster setup](#kubernetes-cluster-setup). When unset, services
  stay ClusterIP-only and the only access is `kubectl port-forward` via
  cluster RBAC:

```sh
kubectl -n __MCP_NAMESPACE__ port-forward svc/mcp-hello 8000:8000
uv run mcp-cli list
```

- **Optional secret**: `MCP_PROVIDER_API_KEY` — the provider key the hosted
  chat answers on (see [Hosted chat](#hosted-chat)). Setting it is what deploys
  the chat at all; without it no chat service exists. The model it names goes
  in the `MCP_CHAT_MODEL` variable, or in the chart's `provider.model`.
- **Optional secret**: `MCP_CHAT_HOST` — a hostname for the chat (default
  `chat.<MCP_INGRESS_HOST>`). It needs its own DNS record and a TLS cert
  (`<namespace>-chat-tls`, issued by cert-manager if configured).
  <!-- /target:k8s -->
  <!-- target:aws -->
- **deploy-aws.yml** (main): detects changed toolsets
  (`scripts/changed-toolsets`) — changes to shared build inputs (`infra/`,
  `Dockerfile`, `uv.lock`, root `pyproject.toml`) rebuild *all* toolsets, which
  is how a runtime version bump reaches every service — builds and pushes
  `ghcr.io/<owner>/<repo>/mcp-<name>:<sha>` for each, then deploys the whole
  instance as a single stack. A toolset whose directory is gone loses its
  service on that same deploy — see [Removing a toolset](#removing-a-toolset).
- **Deploy guard**: the account-touching job is skipped unless the
  `MCP_AWS_ROLE` secret and the `MCP_AWS_INSTANCE` and `MCP_AWS_REGION`
  variables are all set, so a freshly instantiated template never fails CI
  trying to reach an account that doesn't exist yet.
- **Required secret**: `MCP_AWS_ROLE` — the role the run assumes through OIDC.
  There is no access key anywhere: each run mints its own short-lived token.
  Images push to GHCR with the built-in `GITHUB_TOKEN`.
- **Required variables**: `MCP_AWS_INSTANCE` — the stack's name, and the prefix
  of every Parameter Store key it reads — and `MCP_AWS_REGION`. Both are set by
  `./scripts/bootstrap`, and as repo variables they stay per-instance, so two
  repos sharing an account don't collide.
- **Optional secrets**, all prefixed `MCP_AWS_` so neither target can read the
  other's: `INGRESS_HOST` with either `HOSTED_ZONE_ID` (the stack issues the
  certificate and writes the records) or `CERTIFICATE_ARN` (bring your own),
  `CHAT_HOST`, `REGISTRY_SECRET_ARN` for a private registry, and
  `VPC_ID`/`SUBNET_IDS`/`AVAILABILITY_ZONES` to deploy into a network you
  already have. With none of them the stack answers on the load balancer's own
  name over plain HTTP — see
  [AWS: ECS on Fargate](#aws-ecs-on-fargate-without-eks).
  <!-- /target:aws -->

Build an image locally with `docker build --build-arg TOOLSET=hello .`.

## Hosted chat

A web chat over the deployed toolsets, at `chat.<shared-domain>`. It is the
runtime's `mcp_agent_api` — the agent over HTTP as AG-UI events — and the web
client that ships inside that wheel, both in one image (`Dockerfile.chat`) on
one port. Nothing here builds a frontend.

What it shows is the argument for these toolsets rather than a plain chat
window: the answer streams in, each tool call appears as it runs, and beside it
sits a receipt saying what that call was given and where each argument came
from — the model, or a value another tool published. A panel lists what the
tools exchanged without the model reading it, and clicking a key fetches the
payload the conversation never carried. A tool with a view opens it in a frame
in the transcript.

**The model is the deployment's, and so is the bill.** The agent is built once
at startup from `PROVIDER_MODEL` and `PROVIDER_API_KEY`, so anyone who can open
the page spends that key. Two consequences worth stating plainly:

- **No key, no chat.** Neither target deploys the service without one. That is
  the default for a repository made from this template.
- **Put something in front of it** — an auth proxy, an ingress annotation, an
  allowlist — unless leaving the spend open is a decision you have made.

The image bundles the `anthropic`, `openai`, `google-genai` and `mistralai`
drivers, so `PROVIDER_MODEL` picks one without a rebuild and the workspace
itself stays provider-agnostic. A visitor can still supply *toolset*
credentials: a toolset that declares a credential header gets a field in the
page's keys panel, and what is typed there beats the deployment's own value for
that header.

The page's own text — its title, an optional greeting, and the example
questions offered before anyone has typed — is `MCP_AGENT_UI_*`, set
<!-- target:k8s -->
in `infra/k8s/charts/mcp-chat/values.yaml`.
<!-- /target:k8s -->
<!-- target:aws -->
in `Chat`'s defaults in `infra/cdk/config.py`.
<!-- /target:aws -->
With no greeting the page opens on what the agent is actually connected to,
which stays true as toolsets come and go.

<!-- target:k8s -->
It deploys alongside the index when `MCP_INGRESS_HOST` and the
`MCP_PROVIDER_API_KEY` secret are both set (on a shared-code change or a
`workflow_dispatch` run).
<!-- /target:k8s -->
<!-- target:aws -->
It is a service in the stack like any other, so it deploys with everything
else. `MCP_AWS_CHAT_HOST` gives it a hostname, the `MCP_AWS_CHAT_MODEL`
variable turns it on, and its key is a Parameter Store SecureString at
`/mcp-toolsets/<instance>/chat/provider-api-key`, which you create once — the
key is never passed as CDK context, which would put it in the template. The
load balancer holds sessions to one task so a conversation survives.
<!-- /target:aws -->

Conversations are checkpointed per thread, **in the serving process's memory by
default** — so a restart, a redeploy or a second replica loses them. That is
fine for demos and is why nothing extra is deployed for it, and why the chat
runs as a single instance. To keep conversations, point `MCP_AGENT_CHECKPOINT`
at a PostgreSQL URL and add the runtime's `[checkpointing-postgres]` extra to
the chat image. The same per-thread state also carries what the toolsets
published, so if you do adopt `mcp_state`, where conversations live becomes a
real decision rather than a detail.

<!-- target:k8s -->
## Kubernetes cluster setup

The deploy workflow assumes an existing cluster. Minimum requirements: a
conformant cluster (v1.24+) with outbound access to `ghcr.io`, plus the
one-time setup below. `__MCP_NAMESPACE__` is the namespace you chose at bootstrap
(the `MCP_NAMESPACE` variable's value); substitute it in the commands.

1. **Namespace and a scoped deploy service account** — the kubeconfig behind
   the `KUBE_CONFIG` GitHub secret. Don't use cluster-admin:

   ```sh
   kubectl create namespace __MCP_NAMESPACE__
   kubectl -n __MCP_NAMESPACE__ create serviceaccount deployer
   kubectl -n __MCP_NAMESPACE__ create role deployer --verb='*' \
     --resource=deployments.apps,services,secrets,serviceaccounts,ingresses.networking.k8s.io,roles.rbac.authorization.k8s.io,rolebindings.rbac.authorization.k8s.io
   kubectl -n __MCP_NAMESPACE__ create rolebinding deployer \
     --role=deployer --serviceaccount=__MCP_NAMESPACE__:deployer
   ```

   (`secrets` is Helm's release storage; `serviceaccounts`/`roles`/
   `rolebindings` are needed to install `infra/k8s/charts/mcp-index`.)

   `KUBE_CONFIG` is a complete kubeconfig file with a deployer token inside —
   not the token alone. The API server URL must be reachable from GitHub's
   runners, and the token expires (~90 days here), after which deploys fail
   until the secret is refreshed:

   ```sh
   TOKEN=$(kubectl -n __MCP_NAMESPACE__ create token deployer --duration=2160h)
   SERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
   CA=$(kubectl config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')

   KC=--kubeconfig=deployer.kubeconfig
   kubectl config $KC set-cluster cluster --server="$SERVER"
   kubectl config $KC set clusters.cluster.certificate-authority-data "$CA"
   kubectl config $KC set-credentials deployer --token="$TOKEN"
   kubectl config $KC set-context deployer --cluster=cluster --user=deployer --namespace=__MCP_NAMESPACE__
   kubectl config $KC use-context deployer

   gh secret set KUBE_CONFIG < deployer.kubeconfig && rm deployer.kubeconfig
   ```

2. **GHCR pull secret** — if the repo is private, its images are too. Both
   charts reference a `ghcr-pull` Secret by default; create it from a GitHub
   personal access token (classic) with the `read:packages` scope:

   ```sh
   kubectl -n __MCP_NAMESPACE__ create secret docker-registry ghcr-pull \
     --docker-server=ghcr.io \
     --docker-username=<github-username> \
     --docker-password=<token-with-read:packages>
   ```

3. **ingress-nginx** — the charts' ingress defaults assume it:

   ```sh
   helm upgrade --install ingress-nginx ingress-nginx \
     --repo https://kubernetes.github.io/ingress-nginx \
     --namespace ingress-nginx --create-namespace
   ```

4. **cert-manager** — issues and renews the shared domain's certificate:

   ```sh
   helm upgrade --install cert-manager cert-manager \
     --repo https://charts.jetstack.io \
     --namespace cert-manager --create-namespace \
     --set crds.enabled=true
   ```

5. **DNS + a ClusterIssuer.** Point an A/CNAME record for your chosen
   hostname at the ingress controller's load balancer
   (`kubectl -n ingress-nginx get svc ingress-nginx-controller`), and tell
   cert-manager how to reach Let's Encrypt — the one resource it can't
   create for itself. Set your email in `infra/k8s/cluster/letsencrypt-clusterissuer.yaml`
   (Let's Encrypt sends expiry warnings there), then:

   ```sh
   kubectl apply -f infra/k8s/cluster/letsencrypt-clusterissuer.yaml
   ```

   Certificates are then automatic: the `mcp-index` Ingress is annotated
   `cert-manager.io/cluster-issuer: letsencrypt`, so cert-manager issues and
   renews the `__MCP_NAMESPACE__-tls` Secret that all the Ingresses share. If
   your issuer is named differently, override `ingress.clusterIssuer` in
   `infra/k8s/charts/mcp-index`.

6. **Per-toolset Secrets**, created out-of-band (`kubectl create secret ...`),
   for any names a toolset lists under `secrets:` in its `toolset.yaml`.

Finally set the optional shared-domain secret (step 1 already pushed
`KUBE_CONFIG`):

```sh
gh secret set MCP_INGRESS_HOST --body <the-hostname>
```

### One domain for all toolsets

With `MCP_INGRESS_HOST` set (e.g. `mcp.example.com`), the domain serves:

```
https://<host>/                   # index: JSON directory of every toolset + its tools
https://<host>/docs               # the same directory, browsable (Swagger UI)
https://<host>/<toolset>/mcp      # MCP endpoint (prefix stripped by ingress)
https://<host>/<toolset>/health   # liveness, lists the toolset's tool names
```

Anyone you give the URL to can discover what's deployed from the root index —
`mcp-index` lists the toolset Services via the Kubernetes API and asks each
one's `/health` for its tool names, so it always reflects what is actually
running:

```sh
curl https://<host>/ | jq
uv run mcp-cli list --url https://<host>/hello/mcp
```

The index's `connections` key is shaped for
`langchain_mcp_adapters.client.MultiServerMCPClient`, so an agent can consume
every deployed toolset in three lines:

```python
import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient

connections = httpx.get("https://<host>/").json()["connections"]
tools = await MultiServerMCPClient(connections).get_tools()
```

The runtime's `mcp-agent` does exactly that as an interactive chat. The model is
provider-agnostic and no provider ships by default: `PROVIDER_MODEL` is a
`provider:model` string passed to LangChain's `init_chat_model` and
`PROVIDER_API_KEY` is that provider's key. Pick a provider, install its package
(`uv add langchain-openai`), and set both — in the environment or a `.env`
file (copy `.example.env`):

```sh
uv add langchain-openai                          # one-time: install a provider
export PROVIDER_MODEL=openai:gpt-4o-mini PROVIDER_API_KEY=sk-...

uv run mcp-agent https://<host>/                # all deployed toolsets
uv run mcp-agent http://localhost:8000/         # or every toolset from mcp-serve-local
uv run mcp-agent http://localhost:8000/mcp      # or one local mcp-serve
uv run mcp-agent --model anthropic:claude-3-5-haiku-latest   # override the model
uv run mcp-agent                                # url + model from .env
```

An index URL and a single server URL are both accepted, so the local loop above
and the deployed domain are the same command with a different argument.

Any `init_chat_model` provider works (`openai:`, `anthropic:`, `mistralai:`,
…) — switching is a `PROVIDER_MODEL` change plus that provider's package. The
same agent is a web chat over HTTP, which is the image this repo deploys and
also the fastest local loop once a view or a receipt is what you are looking at:

```sh
MCP_URL=http://localhost:8000/ uv run uvicorn mcp_agent_api.app:app --port 8080
```

That serves the API and the page it comes with on one port; `PROVIDER_MODEL`
and `PROVIDER_API_KEY` are read from the environment or `.env` as above. See
[Hosted chat](#hosted-chat) for running it as a public web app.

Each Helm release owns its own Ingress for the same host and the controller
merges them, so the domain's routing table tracks deploys with no central
config to edit; the index's `/` path only catches what no toolset claims.
<!-- /target:k8s -->

<!-- target:aws -->
## AWS: ECS on Fargate, without EKS

A second deployment target, for AWS accounts that want no Kubernetes. It serves
the same URLs, from the same images, with the same per-toolset scoping — the
difference is what is underneath. `infra/cdk` is a CDK app in Python. One stack per instance holds a network, an ECS
cluster, a Fargate service per toolset directory, a load balancer with a rule
per toolset, the index on the default rule, and the chat on a host of its own.
Removing a toolset directory removes its service on the next deploy, which is
what replaces the Kubernetes reconcile job.

| | Kubernetes | AWS |
| --- | --- | --- |
| Unit of deploy | a Helm release per toolset | one stack for the instance |
| A broken toolset | fails its own job; the rest deploy | rolls the whole update back |
| Reached at | `https://<host>/<toolset>/mcp` | the same |
| Path handling | the Ingress rewrites `/<toolset>` away | the toolset serves it (`MCP_PATH_PREFIX`) |
| Certificates | cert-manager, proved over HTTP | ACM, validated by DNS |
| Deploy identity | a kubeconfig token, ~90 days | a federated role, minted per run |
| Toolset config | `toolsets/<name>/toolset.yaml` | `toolsets/<name>/toolset.aws.yaml` |

### One-time account setup

1. **Bootstrap the CDK toolkit**, once per account and region, with your own
   credentials: `npx aws-cdk@2 bootstrap aws://<account>/<region>`.

2. **Deploy the setup stack**, which creates the identity provider and a deploy
   role whose trust is scoped to this repository. Its output is the role ARN:

   ```sh
   npx aws-cdk@2 deploy <instance>-setup \
     --app "uv run --group infra python -m infra.cdk.app" \
     -c instance=<instance> -c setupOnly=true -c repository=<owner>/<repo>
   ```

   The identity provider is one per **account**, not per repository. A second
   repository deploying into the same account must be given the existing one
   with `-c oidcProviderArn=<arn>`, which the first stack also outputs.

3. **Set the variables and the secret** the deploy workflow gates on. Like the
   Kubernetes guard, it skips quietly until all three exist, so a fresh
   instance is green before an account is attached:

   ```sh
   gh variable set MCP_AWS_INSTANCE --body <instance>   # resource name prefix
   gh variable set MCP_AWS_REGION --body <region>
   gh secret set MCP_AWS_ROLE --body <role-arn>         # from step 2
   ```

   Every input this workflow reads is `MCP_AWS_*`, including the ones whose
   Kubernetes counterparts are spelled without it. While a repo carries both
   targets, a shared name would point the AWS deploy at the cluster's
   hostname — which resolves, answers, and is the wrong place.

4. **For a private repository**, a Secrets Manager secret holding a GitHub
   username and a token with `read:packages`, so tasks can pull the images:
   `gh secret set MCP_AWS_REGISTRY_SECRET_ARN --body <arn>`. It is the only
   long-lived credential in this target, and nothing rotates it.

### Domain and certificates

On the cluster the domain is only a pointer: a record aims at the ingress and
Let's Encrypt proves the host over HTTP, so nothing touches your DNS provider.
ACM validates by DNS instead, so here the certificate needs the zone. Three
shapes, and the difference is who writes the records:

| Secrets set | What the stack does |
| --- | --- |
| `MCP_AWS_INGRESS_HOST` + `MCP_AWS_HOSTED_ZONE_ID` | Issues the certificate, writes its validation records, and points both hosts at the load balancer. Renewal needs nobody. |
| `MCP_AWS_INGRESS_HOST` + `MCP_AWS_CERTIFICATE_ARN` | Writes no DNS. Aim a record at the load balancer name the stack outputs. |
| neither | Plain HTTP on the name AWS assigns. Testable before a domain exists; not a posture to leave it in. |

`MCP_AWS_CHAT_HOST` overrides the chat's hostname, which otherwise defaults to
`chat.<host>`. The chat needs a hostname of its own — it is a browser app with
a websocket, not something to hang off a path — so **without a domain the chat
is not deployed at all**. Everything else is.

Four things differ from the cluster and are worth knowing before the first
deploy: the record is an alias rather than an address; the certificate must
live in the load balancer's region; the validation records are permanent, not
scaffolding, and deleting them stops renewal silently; and the chat rides on
the same certificate as a second name, so its hostname has to be known when the
certificate is requested.

### Tagging

Every taggable resource in both stacks carries four tags, so a bill or an audit
answers for itself long after the deploy:

| Tag | Default | Override |
| --- | --- | --- |
| `Project` | `mcp-toolsets` | `-c project=...` |
| `Owner` | `ciaran` | `-c owner=...` |
| `Client` | `labs` | `-c client=...` |
| `Stack` | `dev` | `-c stack=...` |

They are applied to the whole app rather than resource by resource, so anything
added later is tagged without anyone remembering to, and the services propagate
them to the running tasks — a task inherits nothing by default, which would
leave the one thing that actually runs as the only untagged part. AWS's own
cluster and service tags are enabled alongside them, since that is what cost
allocation groups by.

Everything left untagged is a resource type AWS does not tag: routes, security
group rules, route table associations, IAM policies and DNS records. The
`mcp-toolsets/toolset` tag the index selects on is separate and unaffected.

### Bring your own network

The stack builds a network by default: public subnets, no gateway, so it
deploys into an empty account and costs no idle gateway. Point it at an
existing one with `MCP_AWS_VPC_ID`, `MCP_AWS_SUBNET_IDS` and
`MCP_AWS_AVAILABILITY_ZONES`
(comma-separated, one zone per subnet, in order).

The zones are given rather than discovered on purpose: nothing here looks
anything up from an account, which is what lets CI synthesise the stack on a
pull request with no credentials. The cost of that rule is this bit of
configuration; the return is that a broken stack fails review rather than a
deploy. Whatever subnets you name must be able to reach `ghcr.io`, which is the
one thing the stack cannot check for you.

### Per-toolset configuration

`toolsets/<name>/toolset.aws.yaml`, beside the Helm one. Both are copied from
templates in this repo — `infra/cdk/toolset.template.yaml` and
`infra/k8s/toolset.template.yaml` — which the root `pyproject.toml` names under
`[tool.mcp-toolset]`, so the scaffolder writes your files rather than guessing
at them. The two are not translations of each other, which is why there are
two: a Kubernetes secret
exposes every key at once, where a task definition names variables one at a
time, and Fargate sells fixed cpu/memory combinations rather than a request and
a limit.

```yaml
size: { cpu: 512, memory: 1024 }     # omit for the smallest task
env:
  STAC_URL: https://example.org/stac
secrets:                             # Parameter Store, read at task start
  API_TOKEN: /mcp-toolsets/<instance>/<toolset>/api-token
```

Create the parameters out of band, the way cluster secrets are created:

```sh
aws ssm put-parameter --type SecureString \
  --name /mcp-toolsets/<instance>/<toolset>/api-token --value <secret>
```

Parameter Store's standard tier is free. Secrets Manager is roughly $0.40 per
secret per month and buys rotation, cross-account sharing and JSON secrets —
worth moving to when you need one of those, and three places change: the
reference in the toolset file, the execution role's grant, and this command.

### What it costs to leave up

Every toolset is its own always-on task, so cost scales with toolset count in a
way a shared namespace does not. Approximate list prices in a US region,
excluding data transfer:

| | Per month |
| --- | --- |
| Fargate task, 0.25 vCPU / 0.5 GB | ~$9 |
| Five tasks: three examples, index, chat | ~$45 |
| Load balancer | ~$16 base |
| NAT gateway | ~$32 — avoided by the default public subnets |

### Deploying it by hand

The workflow is one way in, not the only one. With your own credentials, from
the repo root (where `cdk.json` is), the region coming from your environment
because the stacks name none:

The account needs the CDK toolkit once per region. Run that from outside the
repo: `cdk bootstrap` executes whatever app `cdk.json` names, even when you
give it the environment explicitly, and this app refuses to build without its
context.

```sh
(cd /tmp && npx aws-cdk@2 bootstrap aws://<account>/eu-west-2)
```

Then, from the repo root:

```sh
uv sync --group infra
export AWS_REGION=eu-west-2                     # or AWS_PROFILE, with a region
npx aws-cdk@2 deploy <instance> \
  -c instance=<instance> \
  -c imagePrefix=ghcr.io/<owner>/<repo> \
  -c imageTags='{"hello":"<tag>","index-aws":"<tag>","chat":"<tag>"}' \
  -c host=mcp.example.com -c hostedZoneId=<zone-id>
```

Every toolset needs a tag, and so do `index-aws` and `chat` — a stack has no memory
of what a service is running, so a missing one is refused rather than guessed
at. The AWS index is `mcp-index-aws`, built from the runtime's AWS extra, because
the cluster's `mcp-index` discovers over the Kubernetes API and cannot see
anything here. The deploy workflow publishes every image on a push to main
whether or not an account is wired up, so the tags usually exist already; to
build one yourself: ```sh
docker build --platform linux/amd64 \
  --label org.opencontainers.image.source=https://github.com/<owner>/<repo> \
  --build-arg TOOLSET=<name> -t ghcr.io/<owner>/<repo>/mcp-<name>:<tag> .
docker push ghcr.io/<owner>/<repo>/mcp-<name>:<tag>
```

where `<name>` is a toolset, or `index-aws` for the directory. The platform
flag matters on Apple silicon: the tasks run x86, and an arm64 image fails at
startup with `exec format error`, which names the symptom rather than the
cause. CI builds on x86 runners, so its images never hit this.

The source label matters only when your push is the one that creates the
package. GHCR links a package to a repository either because a workflow in that
repository pushed it or because this label says so, and a package linked to
neither grants the repository's Actions no access to it — so the next deploy
fails on `denied: permission_denied: write_package` for an image that plainly
exists. Recovering means adding the repository under *Manage Actions access* in
the package's settings, which is not something a workflow can do for itself.

Add `-c setupOnly=true -c repository=<owner>/<repo>` to deploy only the
identity stack, and `-c oidcProviderArn=<arn>` when the account already has
GitHub's provider — it is one per account, so a second repository must be given
the existing one rather than creating another.

### Working on the stack

```sh
uv run --group infra python -m infra.cdk.app -c instance=dev \
  -c imagePrefix=ghcr.io/<owner>/<repo> -c imageTags='{"hello":"abc"}'
uv run --group infra pytest infra
```

Needs node, because `aws-cdk-lib` is a Python package with a JavaScript engine
underneath. Synthesis reaches for no account, so this works anywhere; CI runs
the same command over each domain shape and fails if any of them asks for
context an account would have to supply.

Image tags are explicit state. Helm keeps each release's tag in the cluster, so
deploying one changed toolset leaves the others alone; a stack has no such
memory and must be told a tag for every service it synthesises. The deploy
reads the current tags from Parameter Store, overrides the ones it just built,
hands the whole map to the synthesis, and writes them back only after the stack
accepts them.
<!-- /target:aws -->

### Per-user credentials

Tools that act on a user's behalf (with credentials that differ per calling
user) must not bake secrets into the deployment — and must not take them as
tool arguments either, or the model sees them and they land in chat history
and traces. Instead the client sends them as HTTP headers on every MCP
call, and the tool reads them at call time:

```python
from mcp_runtime.credentials import credential_from_header

@tool
def whoami() -> WhoamiResult:
    """Report which account the calling user's credential belongs to."""
    token = credential_from_header("x-demo-token")
    ...

TOOLS = [whoami]
CREDENTIAL_HEADERS = ["x-demo-token"]  # advertised; validated by the contract test
```

The `CREDENTIAL_HEADERS` export is advertised in the toolset's `/health` and
in the index's `toolsets` entries, so clients know which toolset needs which
credential — and send each one *only* to the connections that declare it,
never to unrelated toolsets. `toolsets/credential-demo` is a working
(stubbed) example. Clients attach the header per connection — agents by
decorating the index's `connections` map, `mcp-cli` with `-H`:

```python
connections = httpx.get("https://<host>/").json()["connections"]
connections["credential-demo"]["headers"] = {"X-Demo-Token": user_token}
tools = await MultiServerMCPClient(connections).get_tools()
```

`mcp-agent` goes further, in the shape a multi-user deployment needs: the
agent is built **once** and credentials are supplied per call. Each
connection gets an httpx client factory that, at request time, injects the
calling user's headers — only those the toolset's advertised declaration
names (for a direct single-server URL the agent asks the endpoint's sibling
`/health` for its declaration):

```python
from mcp_agent.main import user_credentials

with user_credentials({"x-demo-token": the_users_token}):
    result = await agent.ainvoke(...)
```

The hosted chat does the same for a browser: `GET /connections` reports every
credential header the connected toolsets declared, the page offers a field per
header, and each question carries its own — so one long-lived agent process
serves many users, each with their own credentials. The route also says whether
the deployment already holds a value for a header, and a visitor's own beats it.

```sh
uv run mcp-cli call whoami \
  --url https://<host>/credential-demo/mcp -H "X-Demo-Token: $TOKEN"
```

The secret rides the transport (TLS-encrypted in transit), never the
conversation, and the service stays stateless: every call carries its own
credential, so one pod serves all users. A missing header raises a
`MissingCredentialError` whose message tells the caller how to supply it.
Test credential-using tools without a server via
`mcp_runtime.credentials.header_context`:

```python
with header_context({"x-demo-token": "secret"}):
    whoami.invoke({})
```

## Development

```sh
./scripts/format        # ruff autofix + format
./scripts/lint          # ruff checks + mypy over tests/ and toolsets/
./scripts/test          # pytest (args forwarded, e.g. ./scripts/test -k hello)
```

The root `pyproject.toml` defines the uv workspace (`toolsets/*`), the
`mcp-toolsets-runtime` pin, shared tool configuration and the dependency
groups; `uv.lock` pins the runtime and the whole workspace consistently, and is
what the images build from.

`tests/` holds only the toolset contract sweep — every directory under
`toolsets/` must import, export a non-empty `TOOLS`, and satisfy the same
`ToolResult` and docstring gates `build_server` applies at startup. Tests for
runtime behaviour live in
[mcp-toolsets-runtime](https://github.com/developmentseed/mcp-toolsets-runtime),
not here.
