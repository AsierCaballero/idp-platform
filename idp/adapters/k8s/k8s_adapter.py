"""
idp/adapters/k8s/k8s_adapter.py
Adaptador Kubernetes. Mock local, real con kubernetes_asyncio.
"""
from __future__ import annotations

import logging
from typing import Any

from idp.core.domain.models import K8sNamespaceResult, ResourceQuota
from idp.core.exceptions import KubernetesError

logger = logging.getLogger(__name__)


class MockKubernetesAdapter:
    """K8s adapter mock. No requiere cluster."""

    def __init__(self, namespace_prefix: str = "idp"):
        self.namespace_prefix = namespace_prefix
        self._created: list[str] = []
        self._deleted: list[str] = []

    def _ns(self, project_slug: str, tier: str) -> str:
        return f"{self.namespace_prefix}-{project_slug}-{tier}"

    async def create_namespace(
        self, project_slug: str, tier: str, team_slug: str, labels: dict
    ) -> K8sNamespaceResult:
        name = self._ns(project_slug, tier)
        logger.debug(f"[MOCK] K8s create namespace: {name}")
        self._created.append(name)
        return K8sNamespaceResult(
            name=name,
            uid=f"mock-uid-{name}",
            labels={
                "app.kubernetes.io/managed-by": "idp-platform",
                "idp.company.io/project": project_slug,
                "idp.company.io/tier": tier,
                "idp.company.io/team": team_slug,
                **labels,
            },
        )

    async def create_resource_quota(
        self, namespace: str, quota: ResourceQuota
    ) -> None:
        logger.debug(f"[MOCK] K8s create ResourceQuota in {namespace}")

    async def create_rbac(
        self, namespace: str, team_slug: str, project_slug: str
    ) -> None:
        logger.debug(f"[MOCK] K8s create RBAC in {namespace}")

    async def create_network_policy(self, namespace: str) -> None:
        logger.debug(f"[MOCK] K8s create NetworkPolicy in {namespace}")

    async def delete_namespace(self, namespace: str) -> None:
        logger.debug(f"[MOCK] K8s delete namespace: {namespace}")
        self._deleted.append(namespace)

    async def check_health(self) -> bool:
        return True


class KubernetesAdapter:
    """
    K8s adapter real. Requiere kubernetes_asyncio.
    En cluster: KUBERNETES_SERVICE_HOST env var.
    Fuera: kubeconfig path.
    """

    def __init__(
        self,
        namespace_prefix: str = "idp",
        in_cluster: bool = False,
        kubeconfig: str | None = None,
    ):
        self.namespace_prefix = namespace_prefix
        self.in_cluster = in_cluster
        self.kubeconfig = kubeconfig
        self._loaded = False
        self._v1: Any = None
        self._rbac: Any = None
        self._networking: Any = None

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            from kubernetes_asyncio import client, config
            if self.in_cluster:
                config.load_incluster_config()
            else:
                await config.load_kube_config(config_file=self.kubeconfig)
            self._v1 = client.CoreV1Api()
            self._rbac = client.RbacAuthorizationV1Api()
            self._networking = client.NetworkingV1Api()
            self._loaded = True
        except ImportError:
            raise ImportError("kubernetes_asyncio es necesario para el adapter real de K8s")
        except Exception as e:
            raise KubernetesError(f"No se pudo cargar kubeconfig: {e}")

    def _ns(self, project_slug: str, tier: str) -> str:
        return f"{self.namespace_prefix}-{project_slug}-{tier}"

    async def create_namespace(
        self, project_slug: str, tier: str, team_slug: str, labels: dict
    ) -> K8sNamespaceResult:
        await self._ensure_loaded()
        from kubernetes_asyncio import client
        from kubernetes_asyncio.client.exceptions import ApiException

        name = self._ns(project_slug, tier)
        all_labels = {
            "app.kubernetes.io/managed-by": "idp-platform",
            "idp.company.io/project": project_slug,
            "idp.company.io/tier": tier,
            "idp.company.io/team": team_slug,
            **labels,
        }
        ns = client.V1Namespace(
            metadata=client.V1ObjectMeta(name=name, labels=all_labels)
        )
        try:
            result = await self._v1.create_namespace(ns)
            return K8sNamespaceResult(
                name=result.metadata.name,
                uid=result.metadata.uid,
                labels=result.metadata.labels or {},
            )
        except ApiException as e:
            if e.status == 409:
                return K8sNamespaceResult(name=name, uid="", labels=all_labels)
            raise KubernetesError(f"Error creando namespace {name}: {e}") from e

    async def create_resource_quota(
        self, namespace: str, quota: ResourceQuota
    ) -> None:
        await self._ensure_loaded()
        from kubernetes_asyncio import client
        from kubernetes_asyncio.client.exceptions import ApiException

        rq = client.V1ResourceQuota(
            metadata=client.V1ObjectMeta(name="idp-quota", namespace=namespace),
            spec=client.V1ResourceQuotaSpec(hard={
                "requests.cpu": quota.cpu_request,
                "limits.cpu": quota.cpu_limit,
                "requests.memory": quota.memory_request,
                "limits.memory": quota.memory_limit,
                "requests.storage": quota.storage_limit,
                "pods": str(quota.max_replicas * 3),
            }),
        )
        try:
            await self._v1.create_namespaced_resource_quota(namespace, rq)
        except ApiException as e:
            if e.status != 409:
                raise KubernetesError(f"Error creando ResourceQuota: {e}") from e

    async def create_rbac(
        self, namespace: str, team_slug: str, project_slug: str
    ) -> None:
        await self._ensure_loaded()
        from kubernetes_asyncio import client
        from kubernetes_asyncio.client.exceptions import ApiException

        # ServiceAccount
        sa = client.V1ServiceAccount(
            metadata=client.V1ObjectMeta(
                name=f"{project_slug}-sa", namespace=namespace
            ),
            automount_service_account_token=False,
        )
        try:
            await self._v1.create_namespaced_service_account(namespace, sa)
        except ApiException as e:
            if e.status != 409:
                raise KubernetesError(f"Error creando ServiceAccount: {e}") from e

        # Role + RoleBinding mínimos
        role = client.V1Role(
            metadata=client.V1ObjectMeta(name="idp-developer", namespace=namespace),
            rules=[
                client.V1PolicyRule(
                    api_groups=["apps"],
                    resources=["deployments", "replicasets"],
                    verbs=["get", "list", "watch"],
                ),
                client.V1PolicyRule(
                    api_groups=[""],
                    resources=["pods", "pods/log", "services", "configmaps"],
                    verbs=["get", "list", "watch"],
                ),
            ],
        )
        try:
            await self._rbac.create_namespaced_role(namespace, role)
        except ApiException as e:
            if e.status != 409:
                raise KubernetesError(f"Error creando Role: {e}") from e

        rb = client.V1RoleBinding(
            metadata=client.V1ObjectMeta(name="idp-team-binding", namespace=namespace),
            role_ref=client.V1RoleRef(
                api_group="rbac.authorization.k8s.io",
                kind="Role",
                name="idp-developer",
            ),
            subjects=[client.V1Subject(
                kind="Group",
                name=f"github:{team_slug}",
                api_group="rbac.authorization.k8s.io",
            )],
        )
        try:
            await self._rbac.create_namespaced_role_binding(namespace, rb)
        except ApiException as e:
            if e.status != 409:
                raise KubernetesError(f"Error creando RoleBinding: {e}") from e

    async def create_network_policy(self, namespace: str) -> None:
        await self._ensure_loaded()
        from kubernetes_asyncio import client
        from kubernetes_asyncio.client.exceptions import ApiException

        deny_all = client.V1NetworkPolicy(
            metadata=client.V1ObjectMeta(name="deny-all", namespace=namespace),
            spec=client.V1NetworkPolicySpec(
                pod_selector=client.V1LabelSelector(),
                policy_types=["Ingress", "Egress"],
                egress=[client.V1NetworkPolicyEgressRule(
                    ports=[
                        client.V1NetworkPolicyPort(port=53, protocol="UDP"),
                        client.V1NetworkPolicyPort(port=53, protocol="TCP"),
                    ]
                )],
            ),
        )
        try:
            await self._networking.create_namespaced_network_policy(namespace, deny_all)
        except ApiException as e:
            if e.status != 409:
                raise KubernetesError(f"Error creando NetworkPolicy: {e}") from e

    async def delete_namespace(self, namespace: str) -> None:
        await self._ensure_loaded()
        from kubernetes_asyncio.client.exceptions import ApiException
        try:
            await self._v1.delete_namespace(namespace)
        except ApiException as e:
            if e.status != 404:
                raise KubernetesError(f"Error borrando namespace {namespace}: {e}") from e

    async def check_health(self) -> bool:
        try:
            await self._ensure_loaded()
            await self._v1.list_namespace(limit=1)
            return True
        except Exception:
            return False
