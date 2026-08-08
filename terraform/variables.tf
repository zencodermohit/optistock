variable "aws_region" {
  description = "The AWS region to deploy resources in"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "The EC2 instance type"
  type        = string
  default     = "t3.medium"
}

variable "key_name" {
  description = "The SSH key pair name to access the EC2 instance"
  type        = string
  default     = "optistock-prod-key"
}

variable "ssh_allowed_cidr" {
  description = "CIDR block permitted to reach SSH (port 22) on the app server. Set this to your VPN or office egress address, e.g. \"203.0.113.4/32\". Intentionally has no default so it must be an explicit decision."
  type        = string

  validation {
    condition     = var.ssh_allowed_cidr != "0.0.0.0/0"
    error_message = "ssh_allowed_cidr must not be 0.0.0.0/0. Restrict SSH to a specific address such as 203.0.113.4/32, or front it with AWS Systems Manager Session Manager."
  }
}
