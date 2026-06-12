# mcp-toolsets

A monorepo of **toolsets** — small packages of [LangChain](https://python.langchain.com)
tools — each auto-deployed as its own [MCP](https://modelcontextprotocol.io)
service on Kubernetes. Toolset implementors write a single Python module; a
shared runtime, one parameterized Dockerfile and one generic Helm chart handle
everything else.

```
toolsets/<name>/tools.py  ──▶  ghcr.io/<owner>/<repo>/mcp-<name>  ──▶  k8s Service mcp-<name>
   (LangChain @tool fns)        (Dockerfile --build-arg TOOLSET=...)     (charts/mcp-toolset)
```

Terminology: a **tool** is a single LangChain `@tool` function; a **toolset**
is a directory under `toolsets/` exporting a `TOOLS` list, deployed as one MCP
server.

- **`packages/mcp-runtime`** — discovers a toolset's `TOOLS` and serves them
  as a stateless streamable-HTTP MCP server (`mcp-serve`), with a `/health`
  route for k8s probes.
- **`packages/mcp-cli`** — Typer/rich client (`mcp-cli`) to list and call
  tools on a running service.
- **`packages/mcp-agent`** — example chat agent (`mcp-agent`) that discovers
  every server behind an index URL and drives their tools with a Mistral
  model.
- **`toolsets/*`** — one directory per toolset; each becomes an MCP service.
- **`charts/mcp-toolset`** — generic Helm chart all toolsets deploy through.

## Quickstart

```sh
uv sync                # installs every workspace member into one .venv
./scripts/test         # run all tests
./scripts/lint         # ruff + mypy (./scripts/format to autofix)

# Serve a toolset locally
TOOLSET=aoi-generator uv run mcp-serve

# Serve more toolsets alongside it, each on its own port
TOOLSET=credential-demo PORT=8001 uv run mcp-serve

# Talk to them from another shell
uv run mcp-cli list
uv run mcp-cli call aoi_from_place place=alps buffer_km=25
uv run mcp-cli repl
uv run mcp-cli call whoami --url http://localhost:8001/mcp -H "X-Demo-Token: s3cret"
```

`mcp-cli` defaults to `http://localhost:8000/mcp`; pass `--url` to point
elsewhere. Each `mcp-serve` process serves exactly one toolset — the same
shape as production, where every toolset is its own pod and Service.
Toolsets are also importable directly (e.g.
`from aoi_generator.tools import TOOLS`) for in-process use in tests,
notebooks or an agent repo.

## Adding a toolset

No Docker, Kubernetes or MCP knowledge needed — write ordinary LangChain
tools and merge.

1. Scaffold (registers the package in the uv workspace too):

   ```sh
   ./scripts/new-toolset my-toolset
   ```

2. Write your tools in `toolsets/my-toolset/src/my_toolset/tools.py`:

   ```python
   from langchain_core.tools import tool

   @tool
   def do_something(query: str, limit: int = 10) -> list[dict]:
       """One-line description — docstrings and type hints ARE the MCP schema."""
       ...

   TOOLS = [do_something]
   ```

   `TOOLS` is the only required export. Non-empty docstrings are enforced by a
   contract test. If a tool does I/O (HTTP, database), write it as
   `async def` — `@tool` supports coroutines natively; sync tools are fine
   for pure computation (the runtime runs them in a thread pool). If a tool
   needs the *user's* credentials, read them from the request headers — see
   [Per-user credentials](#per-user-credentials).

3. Add tests in `toolsets/my-toolset/tests/test_my_toolset.py` and run
   `./scripts/test`.

4. (Optional) `toolsets/my-toolset/toolset.yaml` holds Helm value overrides —
   secrets to mount via `envFrom`, env vars, resources, replicas. See
   `charts/mcp-toolset/values.yaml` for the available keys.

5. Merge to `main`. CI builds `ghcr.io/<owner>/<repo>/mcp-my-toolset` and
   deploys the `mcp-my-toolset` service automatically.

Conventions: directory `toolsets/<name>` (kebab-case) → module
`<name_snake_case>.tools` → service `mcp-<name>`.

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
`toolset.yaml` (`kubectl -n mcp-toolsets delete secret <name>`) and its
images in GHCR (delete the package from the repo settings if you care).

## Deployment

- **ci.yml** (PRs + main): lint, tests, `helm lint`, and a no-push Docker
  build of every image affected by the change.
- **deploy.yml** (main): detects changed toolsets (`scripts/changed-toolsets`)
  — changes to shared code (`packages/`, `charts/`, `Dockerfile`, `uv.lock`,
  root `pyproject.toml`) rebuild *all* toolsets — then per toolset: build and
  push `ghcr.io/<owner>/<repo>/mcp-<name>:<sha>` and
  `helm upgrade --install mcp-<name> charts/mcp-toolset -n mcp-toolsets`.
  A reconcile job also uninstalls releases whose `toolsets/<name>` directory
  is gone — see [Removing a toolset](#removing-a-toolset).
- **Required secret**: `KUBE_CONFIG` — a kubeconfig with rights to manage the
  `mcp-toolsets` namespace. Images push to GHCR with the built-in
  `GITHUB_TOKEN`.
- **Optional secret**: `MCP_INGRESS_HOST` — a shared hostname. When set, every
  toolset also gets an Ingress on that host at `/<name>`, and an `mcp-index`
  service (built from `packages/mcp-runtime`, deployed via `charts/mcp-index`)
  serves a directory of all toolsets at the domain root — see
  [Kubernetes cluster setup](#kubernetes-cluster-setup). When unset, services
  stay ClusterIP-only and the only access is `kubectl port-forward` via
  cluster RBAC:

```sh
kubectl -n mcp-toolsets port-forward svc/mcp-aoi-generator 8000:8000
uv run mcp-cli list
```

Build an image locally with `docker build --build-arg TOOLSET=aoi-generator .`.

## Kubernetes cluster setup

The deploy workflow assumes an existing cluster. Minimum requirements: a
conformant cluster (v1.24+) with outbound access to `ghcr.io`, plus the
one-time setup below.

1. **Namespace and a scoped deploy service account** — the kubeconfig behind
   the `KUBE_CONFIG` GitHub secret. Don't use cluster-admin:

   ```sh
   kubectl create namespace mcp-toolsets
   kubectl -n mcp-toolsets create serviceaccount deployer
   kubectl -n mcp-toolsets create role deployer --verb='*' \
     --resource=deployments.apps,services,secrets,serviceaccounts,ingresses.networking.k8s.io,roles.rbac.authorization.k8s.io,rolebindings.rbac.authorization.k8s.io
   kubectl -n mcp-toolsets create rolebinding deployer \
     --role=deployer --serviceaccount=mcp-toolsets:deployer
   ```

   (`secrets` is Helm's release storage; `serviceaccounts`/`roles`/
   `rolebindings` are needed to install `charts/mcp-index`.)

   `KUBE_CONFIG` is a complete kubeconfig file with a deployer token inside —
   not the token alone. The API server URL must be reachable from GitHub's
   runners, and the token expires (~90 days here), after which deploys fail
   until the secret is refreshed:

   ```sh
   TOKEN=$(kubectl -n mcp-toolsets create token deployer --duration=2160h)
   SERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
   CA=$(kubectl config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')

   KC=--kubeconfig=deployer.kubeconfig
   kubectl config $KC set-cluster cluster --server="$SERVER"
   kubectl config $KC set clusters.cluster.certificate-authority-data "$CA"
   kubectl config $KC set-credentials deployer --token="$TOKEN"
   kubectl config $KC set-context deployer --cluster=cluster --user=deployer --namespace=mcp-toolsets
   kubectl config $KC use-context deployer

   gh secret set KUBE_CONFIG < deployer.kubeconfig && rm deployer.kubeconfig
   ```

2. **GHCR pull secret** — the repo is private, so its images are too. Both
   charts reference a `ghcr-pull` Secret by default; create it from a GitHub
   personal access token (classic) with the `read:packages` scope:

   ```sh
   kubectl -n mcp-toolsets create secret docker-registry ghcr-pull \
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
   renews the `mcp-toolsets-tls` Secret that all the Ingresses share. If your
   issuer is named differently, override `ingress.clusterIssuer` in
   `charts/mcp-index`.

6. **Per-toolset Secrets**, created out-of-band (`kubectl create secret ...`),
   for any names a toolset lists under `secrets:` in its `toolset.yaml`.

Finally set the one GitHub secret step 1 didn't already push (`KUBE_CONFIG`):

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
uv run mcp-cli list --url https://<host>/aoi-generator/mcp
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

`packages/mcp-agent` does exactly that as an interactive chat (Mistral as the
LLM; `MISTRAL_API_KEY` is read from the environment or a `.env` file in the
working directory):

```sh
uv run mcp-agent https://<host>/                # all deployed toolsets
uv run mcp-agent http://localhost:8000/mcp      # or one local mcp-serve
uv run mcp-agent https://<host>/ --model mistral-large-latest
```

The same agent is available as a Chainlit chat UI: `uv run mcp-agent-web`
serves it at `http://localhost:8080`, configured entirely from the
environment/.env — `MCP_URL` (which index or server to chat with),
`MISTRAL_MODEL` and `CHAINLIT_PORT`.

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
def whoami() -> dict[str, Any]:
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
./scripts/test          # pytest (args forwarded, e.g. ./scripts/test -k aoi)
```

The root `pyproject.toml` defines the uv workspace (`packages/*`,
`toolsets/*`), shared tool configuration and the dev dependency group;
`uv.lock` pins the whole workspace consistently.
