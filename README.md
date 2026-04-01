# 🏗️ IDP Platform

> **Internal Developer Platform** — self-service de infraestructura para equipos de desarrollo.
> Un equipo pide un proyecto → la plataforma crea el repo GitHub, configura CI/CD, aprovisiona namespaces K8s con RBAC y NetworkPolicy, y registra en ArgoCD. Todo en segundos.

[![CI](https://github.com/asier-caballero/idp-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/asier-caballero/idp-platform/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-30%20passing-brightgreen.svg)](tests/)
[![Architecture](https://img.shields.io/badge/architecture-hexagonal-purple.svg)](#arquitectura)

---

## ¿Qué hace?

```bash
# Un comando → GitHub repo + K8s namespace + RBAC + NetworkPolicy + ArgoCD
idp project create "Payment Service" --team backend --envs dev,staging,prod
```

En cuestión de segundos el equipo tiene:
- 📦 **GitHub repo** privado con branch protection y Actions workflows
- ☸️ **K8s namespace** con ResourceQuota, LimitRange, RBAC y NetworkPolicy deny-all
- 🔄 **ArgoCD Application** para GitOps continuo
- 🔑 **Secrets store** conectado (Azure Key Vault / HashiCorp Vault)
- 📋 **Audit log** completo de todas las operaciones

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│                    Hexagonal Architecture               │
│                                                         │
│  CLI (Typer)  ──►  FastAPI  ──►  Core Services          │
│                                    │                    │
│                              ┌─────┴──────┐             │
│                              ▼            ▼             │
│                         GitHub Port   K8s Port          │
│                              │            │             │
│                         GitHub Adapter  K8s Adapter     │
│                         (real/mock)    (real/mock)      │
└─────────────────────────────────────────────────────────┘
```

**Capas:**
- `idp/core/domain/` — modelos puros Python, sin frameworks
- `idp/core/ports/` — interfaces (ABC/Protocol) + in-memory para tests
- `idp/core/services/` — lógica de negocio: TeamService, ProjectService, ProvisioningService
- `idp/adapters/` — GitHub (httpx) y Kubernetes (kubernetes_asyncio)
- `idp/api/` — FastAPI con routers, schemas Pydantic v2
- `idp/cli/` — Typer CLI con Rich output
- `operator/` — K8s Operator (kopf) con CRD `Project.idp.company.io`
- `terraform/` — AKS + PostgreSQL + Redis (módulos reutilizables)

---

## Quick Start

```bash
# 1. Instalar
pip install -r requirements.txt

# 2. Config mínima (sin GitHub/K8s real usa mock automáticamente)
export GITHUB_TOKEN=ghp_xxx
export GITHUB_ORG=myorg

# 3. Arrancar API
uvicorn idp.api.main:app --reload

# 4. Usar CLI
idp team create "Backend" --email backend@company.com --github-team backend
idp project create "Payment Service" --team <team-id> --envs dev,staging,prod
idp project status <project-id>
idp project list
```

---

## API

```
POST   /api/v1/teams                   # Crear equipo
GET    /api/v1/teams                   # Listar equipos
POST   /api/v1/projects                # Crear proyecto (provisioning async)
GET    /api/v1/projects                # Listar proyectos
GET    /api/v1/projects/{id}           # Detalle
GET    /api/v1/projects/{id}/status    # Estado provisioning
POST   /api/v1/projects/{id}/reprovision
DELETE /api/v1/projects/{id}           # Deprovision + soft delete
GET    /api/v1/projects/{id}/audit     # Historial
GET    /health
```

Swagger UI: `http://localhost:8000/api/v1/docs`

---

## K8s Operator

```bash
# Instalar CRD
kubectl apply -f operator/crds/project-crd.yaml

# Crear proyecto via CRD (el operator aprovisiona todo)
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

---

## Deploy con Terraform

```bash
cd terraform/environments/dev
terraform init && terraform apply
```

Aprovisiona: AKS (system + workloads nodepools) + Log Analytics + identidades.

---

## Tests

```bash
python -m unittest tests.test_idp -v
# 30 tests — 0 dependencias externas
```

---

## Variables de entorno

| Variable | Descripción | Default |
|---|---|---|
| `GITHUB_TOKEN` | PAT con permisos `repo` + `admin:org` | Mock mode |
| `GITHUB_ORG` | Organización GitHub | `myorg` |
| `K8S_IN_CLUSTER` | Usar service account del pod | `false` |
| `KUBECONFIG` | Path al kubeconfig | `~/.kube/config` |
| `ARGOCD_SERVER` | URL del servidor ArgoCD | Desactivado |
| `IDP_API_URL` | URL de la API (para el CLI) | `http://localhost:8000/api/v1` |

---

## Stack

`Python 3.11` · `FastAPI` · `SQLAlchemy 2.0` · `Pydantic v2` · `Typer` · `Rich` · `kopf` · `kubernetes_asyncio` · `httpx` · `Terraform` · `AKS` · `ArgoCD`

---

## Autor

**Asier Caballero** — Senior DevOps Engineer & Cloud Architect  
📧 asier.caballero1@gmail.com · 🔗 [linkedin.com/in/asier-caballero](https://linkedin.com/in/asier-caballero)
