# Mountain WindNinja App -- Infrastructure
#
# This Terraform configuration will provision:
# - Cloud storage bucket (terrain cache + solver output)
# - Cloud compute for solver jobs (Cloud Run Jobs or AWS Batch)
# - PostgreSQL database
# - Task queue
# - Container registry
#
# Provider and resource definitions will be added in Phase 4.

terraform {
  required_version = ">= 1.5"
}
