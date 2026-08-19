# ===========================================================================
# Backups
#
# Postgres lives in a Docker volume on a single instance. Until now, losing
# that instance lost the database -- there was no second copy of anything,
# anywhere. A backup that sits on the same disk as the thing it is backing up
# is not a backup; it is a second copy of the same failure.
#
# So the dumps go to S3, which survives the instance entirely.
#
# COST. The free tier covers 5 GB of S3 for twelve months. The database is
# 35 MB and compresses to a few, so thirty daily dumps is well under 200 MB.
# The lifecycle rule below is what keeps it that way permanently rather than
# growing until it is no longer free.
#
# CREDENTIALS. None. The instance gets an IAM role, so the AWS SDK on the box
# obtains temporary credentials from the instance metadata service and there is
# no access key on disk to leak or rotate. This is the one place where the
# right answer is also the easy one.
# ===========================================================================

data "aws_caller_identity" "current" {}

# Bucket names are globally unique across every AWS account in the world, so
# this is qualified with the account id rather than hoping "optistock-backups"
# is free.
resource "aws_s3_bucket" "backups" {
  bucket = "optistock-backups-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name = "optistock-backups"
  }
}

# Database dumps. Every row of every tenant, in plain SQL.
resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Thirty days, then gone. Two reasons, and the second matters more than it
# looks: it caps the storage so this stays inside the free tier without anyone
# remembering to prune, and it means a backup set that has silently been
# failing cannot be papered over by ancient dumps that still look like history.
resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id

  rule {
    id     = "expire-old-dumps"
    status = "Enabled"

    filter {}

    expiration {
      days = 30
    }

    # Multipart uploads that failed halfway are invisible in the console and
    # are still billed for storage. Nothing here is large enough to use
    # multipart, but an aborted-upload rule costs nothing and closes the case.
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# --- The instance's identity ----------------------------------------------

resource "aws_iam_role" "app_server" {
  name = "optistock-app-server"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

# Deliberately narrow. The server may write a backup and list what it has
# written; it may NOT delete one. If the box is ever compromised, the attacker
# gets the ability to add objects to a bucket -- not to destroy the history
# that would let you recover from them. Expiry is the lifecycle rule's job,
# and the lifecycle rule is not something the instance can reach.
resource "aws_iam_role_policy" "backups" {
  name = "optistock-backup-write"
  role = aws_iam_role.app_server.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = "${aws_s3_bucket.backups.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.backups.arn
      }
    ]
  })
}

resource "aws_iam_instance_profile" "app_server" {
  name = "optistock-app-server"
  role = aws_iam_role.app_server.name
}

output "backup_bucket" {
  description = "Where the nightly database dumps are written."
  value       = aws_s3_bucket.backups.id
}
