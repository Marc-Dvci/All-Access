# Deployment

Three planes, deployed by three different things. They are separate on purpose —
see [`../docs/adr/ADR-004-plane-separation.md`](../docs/adr/ADR-004-plane-separation.md).

| Plane | What it is | Deployed by |
|---|---|---|
| Application | FastAPI + web client + solver + twin + verification | `infra/terraform/` → Cloud Run |
| Reasoning | Gemini narration for the fifteen expert agents | `tools/deploy_agent_engine.py` → Vertex AI Agent Engine |
| Event backbone | Governed topics, Schema Registry, data contracts | Confluent Cloud, provisioned outside this repository |

**None of the three is required to run the system.** With no credentials at all,
the container runs the in-process event bus and the offline reasoning plane, and
that is the configuration every number in [`../docs/BENCHMARK.md`](../docs/BENCHMARK.md)
was measured in. The cloud planes are switched on by environment variable
without a rebuild.

## Quickest path to a running URL

```bash
PROJECT=your-project-id
REGION=us-central1

# 1. Provision. Creates the registry first, so the image has somewhere to go.
terraform -chdir=infra/terraform init
terraform -chdir=infra/terraform apply \
  -var project_id="$PROJECT" -target=google_artifact_registry_repository.images

# 2. Build and push.
REPO="$REGION-docker.pkg.dev/$PROJECT/productionpulse-images"
gcloud auth configure-docker "$REGION-docker.pkg.dev"
docker build -t "$REPO/productionpulse:latest" .
docker push "$REPO/productionpulse:latest"

# 3. Deploy.
terraform -chdir=infra/terraform apply -var project_id="$PROJECT"
terraform -chdir=infra/terraform output service_url
```

## Turning on the cloud planes

```bash
# Gemini. Grants roles/aiplatform.user and enables the Vertex API.
terraform -chdir=infra/terraform apply -var project_id="$PROJECT" -var enable_gemini=true

# Confluent. Creates six empty secrets, then populate each one:
terraform -chdir=infra/terraform apply -var project_id="$PROJECT" -var enable_confluent=true
printf %s "$CONFLUENT_API_KEY" | gcloud secrets versions add productionpulse-confluent-api-key --data-file=-
```

Credentials are never Terraform variables. A value passed as a variable is
written into the state file and printed in the plan, and both of those get
shared with people who should not have it.

## The reasoning plane

```bash
python tools/deploy_agent_engine.py --dry-run                 # validate only, no credentials
python tools/deploy_agent_engine.py --project "$PROJECT"
python tools/deploy_agent_engine.py --list
```

The hosted agent is given seven read-only tools and no tool that can approve,
execute or declare readiness. `--dry-run` enforces that boundary and runs in CI,
so the deployment path is validated on every commit rather than the once a
quarter anyone actually deploys.

## What this does not provision

The Confluent Cloud cluster, topics and Schema Registry. They are created by
Confluent's own tooling and referenced here by identifier and credential.
Terraform that claims ownership of a resource it cannot reconcile produces a
state file that lies about what exists.

## Verification

`terraform validate` and `terraform fmt -check` run in CI
(`.github/workflows/ci.yml`, job `infrastructure`), with
`init -backend=false` so validation needs no state bucket and no credentials.
The container image is built and started in the same pipeline, and its
`/healthz`, `/api/about` and `/api/control-board` endpoints are exercised before
the job passes — so the deployment path is checked on every push rather than on
the rare occasions anyone deploys.
