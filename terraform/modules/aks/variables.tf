variable "cluster_name"              { type = string }
variable "location"                   { type = string; default = "westeurope" }
variable "resource_group_name"        { type = string }
variable "kubernetes_version"         { type = string; default = "1.28" }
variable "sku_tier"                   { type = string; default = "Standard" }
variable "system_node_count"          { type = number; default = 3 }
variable "system_vm_size"             { type = string; default = "Standard_D2s_v3" }
variable "workload_vm_size"           { type = string; default = "Standard_D4s_v3" }
variable "workload_min_nodes"         { type = number; default = 2 }
variable "workload_max_nodes"         { type = number; default = 10 }
variable "log_analytics_workspace_id" { type = string }
variable "tags"                       { type = map(string); default = {} }
