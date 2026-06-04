# Demo Flow

This is the intended future demo path.

1. User submits: `Deploy a new checkout microservice`.
2. Python orchestrator runs mock agents in order.
3. Agents generate or validate placeholder artifacts.
4. Docker image is built for the FastAPI app.
5. Manifests are applied to a local kind Kubernetes cluster.
6. Validation checks confirm the deployment is healthy.
7. Release notes and rollback guidance are produced.

No LLM API integration is included in this scaffold.

