variable "aws_region" {
  description = <<-DESC
    The AWS region to deploy resources in.

    Mumbai, because that is where this application's users are. The seeded
    warehouses are Mumbai, Delhi, Pune and Nagpur and every figure on screen
    is formatted en-IN; serving that from Virginia or Stockholm adds well over
    a hundred milliseconds to every request for no reason.

    Region is not a setting you change later. It is baked into the VPC, the
    subnet, the instance, the elastic IP and -- easy to forget -- the SSH key
    pair, which is region-scoped and simply will not be found from another
    region. Moving means rebuilding.

    If you do change it, check var.instance_type at the same time: which micro
    instance the free tier covers varies by region, and eu-north-1 in
    particular has no t2 instances at all.
  DESC
  type        = string
  default     = "ap-south-1"
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

    Defaults to t2.micro, which is what the free tier covers in ap-south-1
    (Mumbai), this configuration's region. This pairing matters: eu-north-1
    has no t2 instances at all and needs t3.micro, and the wrong type is
    billable from the first hour. Both are 1 GB, so the sizing above holds
    either way; t2.micro has one vCPU rather than two, which makes the build
    slower still.

    Raise this to t3.small or t3.medium if deploys feel too slow; the build is
    the only part that struggles, and it is the part that runs on swap.
  DESC
  type        = string
  default     = "t2.micro"
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

variable "alert_email" {
  description = <<-DESC
    Where the spend alarm sends its warning.

    No default, because a budget nobody receives is not a budget. This
    address gets an email the moment the account is billed anything at all
    -- see aws_budgets_budget in main.tf. Confirm the SNS-style subscription
    email AWS sends, or the alerts go nowhere.
  DESC
  type        = string

  validation {
    condition     = can(regex("^[^@\s]+@[^@\s]+\.[^@\s]+$", var.alert_email))
    error_message = "alert_email must be a valid email address."
  }
}
