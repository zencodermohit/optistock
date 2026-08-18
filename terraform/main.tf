terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# VPC and Networking
resource "aws_vpc" "optistock_vpc" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "optistock-vpc"
  }
}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.optistock_vpc.id

  tags = {
    Name = "optistock-igw"
  }
}

resource "aws_subnet" "public_subnet" {
  vpc_id                  = aws_vpc.optistock_vpc.id
  cidr_block              = "10.0.1.0/24"
  map_public_ip_on_launch = true
  availability_zone       = "${var.aws_region}a"

  tags = {
    Name = "optistock-public-subnet"
  }
}

resource "aws_route_table" "public_rt" {
  vpc_id = aws_vpc.optistock_vpc.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }

  tags = {
    Name = "optistock-public-rt"
  }
}

resource "aws_route_table_association" "public_rta" {
  subnet_id      = aws_subnet.public_subnet.id
  route_table_id = aws_route_table.public_rt.id
}

# Security Groups
resource "aws_security_group" "web_sg" {
  name        = "optistock-web-sg"
  description = "Allow HTTP/HTTPS and SSH inbound traffic"
  vpc_id      = aws_vpc.optistock_vpc.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH from the operator network only"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    # Restricted to var.ssh_allowed_cidr, which has no default and rejects
    # 0.0.0.0/0 via a validation rule. Port 8000 is deliberately absent from this
    # security group: the API is only reachable through Nginx on 80/443.
    cidr_blocks = [var.ssh_allowed_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "optistock-web-sg"
  }
}

# EC2 Instance for Docker Compose Deployment
# NOTE: This modular approach allows migrating Postgres to AWS RDS later by 
# simply updating the .env file injected via Github Actions, and removing 
# the 'db' service from docker-compose.yml.
resource "aws_instance" "app_server" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = var.instance_type
  subnet_id     = aws_subnet.public_subnet.id

  vpc_security_group_ids = [aws_security_group.web_sg.id]
  key_name               = var.key_name

  # Pinned, not left to the AMI's default. The free tier covers 30 GB of
  # General Purpose SSD across the whole account; an AMI that ships a larger
  # root volume, or a second instance later, silently crosses that line and
  # the overage is charged per GB-month. 20 GB leaves room for the Docker
  # images, the Postgres volume and the Parquet data lake, and still leaves
  # headroom under the cap.
  #
  # gp2 rather than gp3: both are General Purpose SSD and both are covered,
  # but gp2 is the type the free tier has always named explicitly, and this
  # deployment has no budget for being wrong about that.
  root_block_device {
    volume_size           = 20
    volume_type           = "gp2"
    delete_on_termination = true
    encrypted             = true
  }

  user_data = <<-EOF
              #!/bin/bash
              apt-get update
              apt-get install -y apt-transport-https ca-certificates curl software-properties-common
              curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
              add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
              apt-get update
              apt-get install -y docker-ce docker-compose-plugin git
              systemctl enable docker
              systemctl start docker
              usermod -aG docker ubuntu

              # Swap, and 4G of it rather than 2G.
              #
              # The default instance is now the 1 GB free-tier size, which runs
              # the stack comfortably (347 MiB idle) but cannot build it: the
              # React bundle and the Python scientific stack compile in the
              # same step, the kernel OOM-kills the compiler, and Docker
              # reports a generic non-zero exit that reads as broken code and
              # is not. 2G was sized for a 2 GB instance and only just cleared
              # the deploy's own preflight on a 1 GB one.
              #
              # Building on swap is slow -- expect deploys in the tens of
              # minutes -- but it is reliable, and it costs nothing beyond
              # disk. The faster fix is to build in CI and have the server
              # pull a finished image; that needs a container registry and
              # credentials on the box, so it is a deliberate later step
              # rather than something to carry from the start.
              if [ ! -f /swapfile ]; then
                fallocate -l 4G /swapfile
                chmod 600 /swapfile
                mkswap /swapfile
                swapon /swapfile
                echo '/swapfile none swap sw 0 0' >> /etc/fstab
              fi

              # deploy.yml starts with `cd /home/ubuntu/project_IV && git pull`,
              # so the directory has to exist before the first deploy can run.
              # The clone itself is a manual step: the repository URL is not
              # known at provisioning time, and a private repo needs a deploy
              # key that does not belong in user_data.
              mkdir -p /home/ubuntu/project_IV
              chown ubuntu:ubuntu /home/ubuntu/project_IV
              EOF

  tags = {
    Name = "optistock-app-server"
  }
}

# Fetch latest Ubuntu AMI
data "aws_ami" "ubuntu" {
  most_recent = true

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  owners = ["099720109477"] # Canonical
}

# Elastic IP
resource "aws_eip" "app_eip" {
  instance = aws_instance.app_server.id
  domain   = "vpc"

  tags = {
    Name = "optistock-eip"
  }
}

# ---------------------------------------------------------------------------
# Spend guard
#
# This deployment has no budget at all, so the alarm is infrastructure rather
# than a step in a checklist somebody might skip. AWS Budgets is itself free
# for the first two budgets.
#
# It does NOT stop charges -- nothing in AWS does that automatically. It tells
# you within a day of the first cent, which is the difference between noticing
# now and noticing on a monthly statement.
#
# Two notifications on purpose. ACTUAL fires once real money is billed;
# FORECASTED fires when AWS projects the month will exceed the limit, which
# usually lands days earlier and is the one that gives you time to act.
# ---------------------------------------------------------------------------
resource "aws_budgets_budget" "zero_spend_guard" {
  name         = "optistock-zero-spend-guard"
  budget_type  = "COST"
  limit_amount = "1"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # 1% of one dollar. Effectively: tell me if this account is billed anything.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 1
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 1
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
