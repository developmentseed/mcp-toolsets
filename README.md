# mcp-toolsets

A template monorepo of **toolsets** — small packages of
[LangChain](https://python.langchain.com) tools — each auto-deployed as its own
[MCP](https://modelcontextprotocol.io) service on Kubernetes. Toolset
implementors write a single Python module; a shared runtime, one parameterized
Dockerfile and one generic Helm chart handle everything else.

```
toolsets/<name>/tools.py  ──▶  ghcr.io/<owner>/<repo>/mcp-<name>  ──▶  k8s Service mcp-<name>
   (LangChain @tool fns)        (Dockerfile --build-arg TOOLSET=...)     (charts/mcp-toolset)
```

Terminology: a **tool** is a single LangChain `@tool` function; a **toolset**
is a directory under `toolsets/` exporting a `TOOLS` list, deployed as one MCP
server.

## Use this template

This repository is a GitHub template — click **Use this template** to create
your own. The image registry path is derived from your repo name automatically;
the only thing to set is the Kubernetes namespace:

1. **Bootstrap once — do this first.** `./scripts/bootstrap` is the intended
   first step after creating your repo. It does three things:

   - sets the **`MCP_NAMESPACE`** repo Actions variable (the namespace your
     toolsets deploy into) via `gh` — **deploys are skipped until this is set**;
   - **rewrites the `__MCP_NAMESPACE__` placeholders** in `README.md` and
     `CLAUDE.md` in place, so the cluster-setup commands below become
     copy-pasteable for your namespace;
   - optionally removes the shipped example toolsets.

   ```sh
   ./scripts/bootstrap            # prompts for a namespace + which examples to keep
   # or non-interactively:
   ./scripts/bootstrap my-namespace --keep-examples
   ```

   Re-running is safe. The namespace lives only in the repo variable, not a
   committed file, so it never carries over to repos generated from your
   instance. If `gh` isn't set up when you bootstrap, the script prints the one
   command to set the variable yourself
   (`gh variable set MCP_NAMESPACE --body <namespace>`); the `__MCP_NAMESPACE__`
   placeholders then stay literal until you re-run bootstrap or edit them by hand.

2. **Develop** — `uv sync`, then add a toolset (`./scripts/new-toolset`) or play
   with the shipped `hello` example (see [Quickstart](#quickstart)).

3. **Deploy when ready** — set the `KUBE_CONFIG` secret (see
   [Kubernetes cluster setup](#kubernetes-cluster-setup)). Until you do, CI runs
   lint/tests/build on every push but **skips the deploy** — a fresh instance is
   green out of the box, with no cluster required.

The repo ships two example toolsets you can keep, copy or delete: `hello` (the
smallest thing that deploys) and `credential-demo` (the
[per-user credentials](#per-user-credentials) pattern).

## Packages

| Package | Role |
| --- | --- |
| **`packages/mcp-runtime`** | **Required.** Discovers a toolset's `TOOLS` and serves them as a stateless streamable-HTTP MCP server (`mcp-serve`), with a `/health` route for k8s probes. Also builds the `mcp-index`. |
| **`packages/mcp-cli`** | **Recommended for development.** Typer/rich client (`mcp-cli`) to list and call tools on a running service — the day-to-day inner loop. |
| **`packages/mcp-agent`** | **Optional example.** A chat agent (`mcp-agent` / `mcp-agent-web`) that discovers every server behind an index URL and drives their tools with a configurable chat model. Delete it if you don't need an agent. |

Plus `toolsets/*` — one directory per toolset, each becoming an MCP service —
and `charts/mcp-toolset`, the generic Helm chart all toolsets deploy through.

## Quickstart

```sh
uv sync                # installs every workspace member into one .venv
./scripts/test         # run all tests
./scripts/lint         # ruff + mypy (./scripts/format to autofix)

# Serve a toolset locally
TOOLSET=hello uv run mcp-serve

# Serve more toolsets alongside it, each on its own port
TOOLSET=credential-demo PORT=8001 uv run mcp-serve

# Talk to them from another shell
uv run mcp-cli list
uv run mcp-cli call hello name=dev
uv run mcp-cli repl
uv run mcp-cli call whoami --url http://localhost:8001/mcp -H "X-Demo-Token: s3cret"
```

`mcp-cli` defaults to `http://localhost:8000/mcp`; pass `--url` to point
elsewhere. Each `mcp-serve` process serves exactly one toolset — the same
shape as production, where every toolset is its own pod and Service.
Toolsets are also importable directly (e.g.
`from hello.tools import TOOLS`) for in-process use in tests, notebooks or an
agent repo.

## Adding a toolset

No Docker, Kubernetes or MCP knowledge needed — write ordinary LangChain
tools and merge.

1. Scaffold (registers the package in the uv workspace too):

   ```sh
   ./scripts/new-toolset my-toolset
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

4. (Optional) `toolsets/my-toolset/toolset.yaml` holds Helm value overrides —
   secrets to mount via `envFrom`, env vars, resources, replicas. See
   `charts/mcp-toolset/values.yaml` for the available keys.

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
chart) that a UI-capable MCP host — Claude web, an mcp-ui client, or the bundled
Chainlit agent — renders in a sandboxed iframe and feeds the tool's
`structuredContent`. The runtime stays pure-Python: a view is a build-time HTML
bundle served as an MCP resource; nothing new executes at call time. Views are
**progressive enhancement** — the tool's `message` and structured data still
stand alone in a plain client, so a view never changes what a tool returns.

Scaffold a toolset with an example view, then build it (needs node):

```sh
./scripts/new-toolset --with-ui my-toolset
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
3. **The host bridge** — the bundle speaks a three-message postMessage protocol
   (`ui/src/host.ts`): `mcp:ready` up when it mounts, `mcp:data` down carrying
   the tool's `structuredContent`, `mcp:sendMessage` up to advance the chat. Any
   framework works; only this seam is fixed.

Given that, the runtime does two standard-MCP things: it serves each view as a
resource `ui://<toolset>/<view_id>` and stamps the owning tool's `_meta` with
that URI (the mcp-ui / Apps-SDK `_meta` convention). A UI-capable host reads the
`_meta` to know a tool has a view and reads the resource for its HTML — that is
all the Chainlit agent does (`get_resources` + the tool's `_meta`), and it is
what Claude web / mcp-ui clients consume too.

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

## Removing a toolset

```sh
./scripts/remove-toolset my-toolset
```

Merge to `main`. Removal is GitOps like everything else: the deploy
workflow reconciles the cluster against `toolsets/`, uninstalling any
`mcp-<name>` release whose directory no longer exists — Deployment, Service
and Ingress with it; the index drops the entry automatically. Mind that
this means merging a deleted directory tears down the live service.

Not removed automatically: out-of-band Secrets the toolset listed in its
`toolset.yaml` (`kubectl -n __MCP_NAMESPACE__ delete secret <name>`) and its
images in GHCR (delete the package from the repo settings if you care).

## Deployment

- **ci.yml** (PRs + main): lint, tests, `helm lint`, and a no-push Docker
  build of every image affected by the change. Always runs — no cluster needed.
- **deploy.yml** (main): detects changed toolsets (`scripts/changed-toolsets`)
  — changes to shared code (`packages/`, `charts/`, `Dockerfile`, `uv.lock`,
  root `pyproject.toml`) rebuild *all* toolsets — then per toolset: build and
  push `ghcr.io/<owner>/<repo>/mcp-<name>:<sha>` and
  `helm upgrade --install mcp-<name> charts/mcp-toolset -n __MCP_NAMESPACE__`.
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
  service (built from `packages/mcp-runtime`, deployed via `charts/mcp-index`)
  serves a directory of all toolsets at the domain root — see
  [Kubernetes cluster setup](#kubernetes-cluster-setup). When unset, services
  stay ClusterIP-only and the only access is `kubectl port-forward` via
  cluster RBAC:

```sh
kubectl -n __MCP_NAMESPACE__ port-forward svc/mcp-hello 8000:8000
uv run mcp-cli list
```

Build an image locally with `docker build --build-arg TOOLSET=hello .`.

- **Optional secret**: `MCP_CHAT_HOST` — a hostname for the hosted chat UI (see
  [Hosted chat](#hosted-chat-bring-your-own-model)). When `MCP_INGRESS_HOST` is
  set, the deploy builds `Dockerfile.chat` and installs `charts/mcp-chat` on
  this host (default `chat.<MCP_INGRESS_HOST>`). It needs its own DNS record and
  a TLS cert (`<namespace>-chat-tls`, issued by cert-manager if configured).

## Hosted chat (bring your own model)

`packages/mcp-agent`'s Chainlit UI can also run as a public web app over the
deployed toolsets, at `chat.<shared-domain>`. It is **bring-your-own-model**:
the deployment holds no provider key. Each user opens ⚙ settings and enters a
`provider:model` and their own API key (and any per-toolset credential headers);
the key lives only in that browser session — never sent to the model, logged, or
stored server-side — so exposing the host exposes no server-held secret and the
model spend is the user's own. The image (`Dockerfile.chat`) bundles a set of
providers (`anthropic`, `openai`, `google-genai`, `mistralai`) so any of them
works without a rebuild; the workspace itself stays provider-agnostic.

It deploys automatically alongside the index when `MCP_INGRESS_HOST` is set (a
shared-code change or a `workflow_dispatch` run). There is no built-in auth —
BYOM removes the shared-key abuse risk, but put an auth proxy in front (or
enable Chainlit auth) if you need to restrict who can use it.

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
   `rolebindings` are needed to install `charts/mcp-index`.)

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
   create for itself. Set your email in `k8s/letsencrypt-clusterissuer.yaml`
   (Let's Encrypt sends expiry warnings there), then:

   ```sh
   kubectl apply -f k8s/letsencrypt-clusterissuer.yaml
   ```

   Certificates are then automatic: the `mcp-index` Ingress is annotated
   `cert-manager.io/cluster-issuer: letsencrypt`, so cert-manager issues and
   renews the `__MCP_NAMESPACE__-tls` Secret that all the Ingresses share. If
   your issuer is named differently, override `ingress.clusterIssuer` in
   `charts/mcp-index`.

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

`packages/mcp-agent` does exactly that as an interactive chat. The model is
provider-agnostic and no provider ships by default: `PROVIDER_MODEL` is a
`provider:model` string passed to LangChain's `init_chat_model` and
`PROVIDER_API_KEY` is that provider's key. Pick a provider, install its package
(`uv add langchain-openai`), and set both — in the environment or a `.env`
file (copy `.example.env`):

```sh
uv add langchain-openai                          # one-time: install a provider
export PROVIDER_MODEL=openai:gpt-4o-mini PROVIDER_API_KEY=sk-...

uv run mcp-agent https://<host>/                # all deployed toolsets
uv run mcp-agent http://localhost:8000/mcp      # or one local mcp-serve
uv run mcp-agent --model anthropic:claude-3-5-haiku-latest   # override the model
uv run mcp-agent                                # url + model from .env
```

Any `init_chat_model` provider works (`openai:`, `anthropic:`, `mistralai:`,
…) — switching is a `PROVIDER_MODEL` change plus that provider's package. The
same agent is available as a Chainlit chat UI: `uv run mcp-agent-web` serves it
at `http://localhost:8080`. It is **bring-your-own-model** — set the model and
API key in ⚙ settings, or pre-fill them from the environment/.env
(`PROVIDER_MODEL`, `PROVIDER_API_KEY`); `MCP_URL` (which index or server to chat
with) and `CHAINLIT_PORT` also come from there. See
[Hosted chat](#hosted-chat-bring-your-own-model) to run it as a public web app.

Each Helm release owns its own Ingress for the same host and the controller
merges them, so the domain's routing table tracks deploys with no central
config to edit; the index's `/` path only catches what no toolset claims.

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

The Chainlit UI builds a settings field (⚙ by the message box) for every
credential header the connected toolsets advertise and applies the values
per message — so one long-lived agent process serves many users, each with
their own credentials.

```sh
uv run mcp-cli call whoami \
  --url https://<host>/credential-demo/mcp -H "X-Demo-Token: $TOKEN"
```

The secret rides the transport (TLS-encrypted at the ingress), never the
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
./scripts/lint          # ruff checks + mypy over packages/ and toolsets/
./scripts/test          # pytest (args forwarded, e.g. ./scripts/test -k hello)
```

The root `pyproject.toml` defines the uv workspace (`packages/*`,
`toolsets/*`), shared tool configuration and the dev dependency group;
`uv.lock` pins the whole workspace consistently.
