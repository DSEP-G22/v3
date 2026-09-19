# One EC2 host in ap-southeast-1 (Singapore), next to the Neon project, because every page
# waits on the database round trip. Ansible installs Docker and runs the compose stack on it.
#
#   terraform init && terraform apply -var="key_name=your-keypair"
#
# State is local on purpose: this is one host for a student deployment. Move it to an S3
# backend before a second person runs apply.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

resource "aws_security_group" "lanka" {
  name        = "${var.name}-edge"
  description = "HTTP, HTTPS and SSH for the Lanka Link edge"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH for Ansible"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.ssh_cidrs
  }
  ingress {
    description = "HTTP, for the ACME challenge and the redirect to HTTPS"
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
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "lanka" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  subnet_id                   = data.aws_subnets.default.ids[0]
  vpc_security_group_ids      = [aws_security_group.lanka.id]
  key_name                    = var.key_name
  associate_public_ip_address = true

  # The model images (NLLB, Whisper, the ONNX router) and their layers are the disk hogs.
  root_block_device {
    volume_size = var.disk_gb
    volume_type = "gp3"
    encrypted   = true
  }

  tags = { Name = var.name }
}

resource "aws_eip" "lanka" {
  instance = aws_instance.lanka.id
  domain   = "vpc"
  tags     = { Name = var.name }
}
