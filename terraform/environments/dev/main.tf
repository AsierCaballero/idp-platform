# terraform/environments/dev/main.tf
# IDP Platform — entorno desarrollo

terraform {
  required_version = ">= 1.5"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 3.80" }
  }
  backend "azurerm" {
    resource_group_name  = "rg-tfstate-dev"
    storage_account_name = "stidptfstatedev"
    container_name       = "tfstate"
    key                  = "idp-platform/dev/terraform.tfstate"
  }
}

provider "azurerm" {
  features {}
}

locals {
  env  = "dev"
  tags = {
    environment  = local.env
    managed-by   = "terraform"
    project      = "idp-platform"
    cost-center  = "platform"
  }
}

module "aks" {
  source              = "../../modules/aks"
  cluster_name        = "aks-idp-${local.env}"
  location            = "westeurope"
  resource_group_name = "rg-idp-${local.env}"
  sku_tier            = "Free"
  system_node_count   = 1
  workload_min_nodes  = 1
  workload_max_nodes  = 3
  log_analytics_workspace_id = azurerm_log_analytics_workspace.idp.id
  tags                = local.tags
}

resource "azurerm_log_analytics_workspace" "idp" {
  name                = "law-idp-${local.env}"
  location            = "westeurope"
  resource_group_name = "rg-idp-${local.env}"
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}
