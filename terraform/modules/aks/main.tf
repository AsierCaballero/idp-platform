/**
 * terraform/modules/aks/main.tf
 * AKS cluster para el IDP Platform.
 * Sistema nodepools: system + idp-workloads.
 */

terraform {
  required_version = ">= 1.5"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 3.80" }
  }
}

resource "azurerm_kubernetes_cluster" "idp" {
  name                = var.cluster_name
  location            = var.location
  resource_group_name = var.resource_group_name
  dns_prefix          = var.cluster_name
  kubernetes_version  = var.kubernetes_version
  sku_tier            = var.sku_tier

  default_node_pool {
    name                = "system"
    node_count          = var.system_node_count
    vm_size             = var.system_vm_size
    os_disk_size_gb     = 50
    type                = "VirtualMachineScaleSets"
    zones               = ["1", "2", "3"]
    only_critical_addons_enabled = true
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin    = "azure"
    network_policy    = "calico"
    load_balancer_sku = "standard"
    outbound_type     = "loadBalancer"
  }

  azure_active_directory_role_based_access_control {
    managed            = true
    azure_rbac_enabled = true
  }

  oms_agent {
    log_analytics_workspace_id = var.log_analytics_workspace_id
  }

  key_vault_secrets_provider {
    secret_rotation_enabled = true
  }

  tags = var.tags
}

# Nodepool dedicado para workloads IDP
resource "azurerm_kubernetes_cluster_node_pool" "idp_workloads" {
  name                  = "idpwork"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.idp.id
  vm_size               = var.workload_vm_size
  min_count             = var.workload_min_nodes
  max_count             = var.workload_max_nodes
  enable_auto_scaling   = true
  os_disk_size_gb       = 100
  zones                 = ["1", "2", "3"]

  node_labels = {
    "idp.company.io/nodepool" = "workloads"
  }

  node_taints = [
    "idp.company.io/workload=true:NoSchedule"
  ]

  tags = var.tags
}
