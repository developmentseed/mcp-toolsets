"""The AWS deployment target: an ECS on Fargate stack, built with CDK.

Read `README.md` for what this deploys and how it is configured. The short
version: `config.py` turns this repo plus CDK context into a `Deployment`,
`toolsets_stack.py` turns that into services behind one load balancer, and
`setup_stack.py` is the one-time federated identity a deploy assumes.
"""
