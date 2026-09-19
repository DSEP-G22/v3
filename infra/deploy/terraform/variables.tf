variable "name" {
  description = "Name tag for everything this stack creates"
  type        = string
  default     = "lanka-link-v3"
}

variable "region" {
  description = "Singapore, so the host sits beside the Neon project"
  type        = string
  default     = "ap-southeast-1"
}

variable "instance_type" {
  description = "The models need memory more than cores: NLLB, Whisper and the embedding models are all resident"
  type        = string
  default     = "m6i.xlarge" # 4 vCPU, 16 GB, not burstable: the models use CPU on every message
}

variable "disk_gb" {
  description = "Model images and their layers"
  type        = number
  default     = 80
}

variable "key_name" {
  description = "An existing EC2 key pair; Ansible connects with its private half"
  type        = string
}

variable "ssh_cidrs" {
  description = "Who may reach port 22. Narrow this to the deploy runner and your own address"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
