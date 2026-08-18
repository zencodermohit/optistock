variable "aws_region" {
  description = "The AWS region to deploy resources in"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = <<-DESC
    The EC2 instance type.

    Defaults to the free-tier size. The whole stack -- Postgres, Redis, the
    API, the relay, the consumers and Nginx -- measures 347 MiB at idle, so a
    1 GB box runs it with roughly 450 MiB of headroom once Ubuntu has taken
    its share. What does NOT fit in 1 GB is the BUILD: the React bundle and
    the Python scientific stack compile in the same step and need several GB,
    which is what the swap in main.tf's user_data is for.

    Check which micro instance your region's free tier covers before applying
    -- it is t2.micro in some regions and t3.micro in others, and the wrong
    one is billable from the first hour. Both are 1 GB, so the sizing above
    holds either way.

    Raise this to t3.small or t3.medium if deploys feel too slow; the build is
    the only part that struggles, and it is the part that runs on swap.
  DESC
  type        = string
  default     = "t3.micro"
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
