# IDP Platform

Internal Developer Platform — self-service infrastructure for development teams. A team requests a project, and the platform creates the GitHub repo, configures CI/CD, provisions Kubernetes namespaces with RBAC and NetworkPolicy, and registers everything in ArgoCD. In seconds.

[![CI](https://img.shields.io/github/actions/workflow/status/AsierCaballero/idp-platform/ci.yml?label=CI&logo=github)](https://github.com/AsierCaballero/idp-platform/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-30%20passing-brightgreen)](tests/)
[![Architecture](https://img.shields.io/badge/architecture-hexagonal-purple)](#architecture)

---

## Quick Demo

```bash
idp project create "Payment Service" --team backend --envs dev,staging,prod
```

This single command gives the team:
- Private GitHub repo with branch protection and Actions workflows
- Kubernetes namespace with ResourceQuota, LimitRange, RBAC, and default deny-all NetworkPolicy
- ArgoCD Application for GitOps
- Secrets store integration (Azure Key Vault / HashiCorp Vault)
- Complete audit log of every operation

---

## Features

- **CLI + API**: Typer CLI and FastAPI REST API, both backed by the same core services
- **Kubernetes Operator**: Manage projects declaratively via a custom CRD
- **GitOps ready**: ArgoCD Application is registered automatically for each project
- **Multi-environment**: Per-environment configuration with different resource limits
- **Pluggable adapters**: GitHub and Kubernetes adapters with real and mock implementations for testing
- **Terraform infrastructure**: AKS, PostgreSQL, and Redis provisioning with reusable modules

---

## Architecture

```
 Hexagonal (Ports & Adapters)

 CLI (Typer)  -->  FastAPI  -->  Core Services
                                    |
                              ------+------
                              |           |
                         GitHub Port  K8s Port
                              |           |
                         GitHub Adapter  K8s Adapter
                         (real/mock)    (real/mock)
```

**Layers:**

| Layer | Path | Responsibility |
|---|---|---|
| Domain | `idp/core/domain/` | Pure Python models, no framework dependencies |
| Ports | `idp/core/ports/` | Interfaces (ABC/Protocol) with in-memory implementations for tests |
| Services | `idp/core/services/` | Business logic: TeamService, ProjectService, ProvisioningService |
| Adapters | `idp/adapters/` | GitHub (httpx) and Kubernetes (kubernetes_asyncio) |
| API | `idp/api/` | FastAPI routers with Pydantic v2 schemas |
| CLI | `idp/cli/` | Typer CLI with Rich output |
| Operator | `operator/` | Kopf-based K8s operator with CRD `Project.idp.company.io` |
| Terraform | `terraform/` | AKS, PostgreSQL, and Redis reusable modules |

---

## Usage

### API

```
POST   /api/v1/teams                   Create a team
GET    /api/v1/teams                   List teams
POST   /api/v1/projects                Create a project (async provisioning)
GET    /api/v1/projects                List projects
GET    /api/v1/projects/{id}           Project detail
GET    /api/v1/projects/{id}/status    Provisioning status
POST   /api/v1/projects/{id}/reprovision
DELETE /api/v1/projects/{id}           Deprovision + soft delete
GET    /api/v1/projects/{id}/audit     Audit history
GET    /health
```

Swagger UI at `http://localhost:8000/api/v1/docs`

### K8s Operator

```bash
kubectl apply -f operator/crds/project-crd.yaml

kubectl apply -f - <<EOF
apiVersion: idp.company.io/v1alpha1
kind: Project
metadata:
  name: payment-service
spec:
  name: Payment Service
  teamSlug: backend
  environments:
    - tier: dev
    - tier: prod
      cpuLimit: "2000m"
      memoryLimit: 2Gi
EOF
```

### Terraform

```bash
cd terraform/environments/dev
terraform init && terraform apply
```

Provisions AKS (system + workload nodepools), Log Analytics, and managed identities.

---

## Development

### Prerequisites

- Python 3.11+
- kubectl + access to a cluster (optional, mock mode works without one)
- GitHub token with `repo` and `admin:org` scopes (optional, mock mode used otherwise)

### Setup

```bash
pip install -r requirements.txt

# Minimum configuration (mock mode used if tokens are missing)
export GITHUB_TOKEN=ghp_xxx
export GITHUB_ORG=myorg

# Start the API
uvicorn idp.api.main:app --reload

# Use the CLI
idp team create "Backend" --email backend@company.com --github-team backend
idp project create "Payment Service" --team <team-id> --envs dev,staging,prod
idp project status <project-id>
idp project list
```

### Tests

All 30 tests run with zero external dependencies:

```bash
python -m unittest tests.test_idp -v
```

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `GITHUB_TOKEN` | PAT with `repo` + `admin:org` scopes | Mock mode |
| `GITHUB_ORG` | GitHub organization | `myorg` |
| `K8S_IN_CLUSTER` | Use pod service account | `false` |
| `KUBECONFIG` | Path to kubeconfig | `~/.kube/config` |
| `ARGOCD_SERVER` | ArgoCD server URL | Disabled |
| `IDP_API_URL` | API URL (for the CLI) | `http://localhost:8000/api/v1` |

### Stack

Python 3.11, FastAPI, SQLAlchemy 2.0, Pydantic v2, Typer, Rich, kopf, kubernetes_asyncio, httpx, Terraform, AKS, ArgoCD.

---

## Author

**Asier Caballero** — Senior DevOps Engineer & Cloud Architect  
asier.caballero1@gmail.com · [linkedin.com/in/asier-caballero](https://linkedin.com/in/asier-caballero)
