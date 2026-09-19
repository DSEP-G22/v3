output "public_ip" {
  description = "Point the site's A record here, then run the Ansible playbook"
  value       = aws_eip.lanka.public_ip
}

output "inventory_line" {
  description = "Paste into infra/deploy/ansible/inventory.ini"
  value       = "lanka-prod ansible_host=${aws_eip.lanka.public_ip} ansible_user=ubuntu"
}
