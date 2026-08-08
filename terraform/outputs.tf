output "server_public_ip" {
  description = "The public IP address of the EC2 instance"
  value       = aws_eip.app_eip.public_ip
}

output "server_public_dns" {
  description = "The public DNS of the EC2 instance"
  value       = aws_eip.app_eip.public_dns
}
