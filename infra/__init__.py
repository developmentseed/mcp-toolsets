"""How this repo deploys, one directory per target.

- ``k8s/`` — Helm charts and the one cluster-scoped resource they assume.
- ``cdk/`` — the AWS target: ECS on Fargate, as a CDK app in Python.

An instance keeps whichever target it chose; both are here because this is the
template. Only ``cdk`` is importable Python — ``k8s`` is charts and manifests,
sitting beside it so there is one place to look for "how does this deploy".
"""
