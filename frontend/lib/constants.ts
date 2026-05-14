/**
 * Supported AWS resource types — synced with backend common/__init__.py SUPPORTED_RESOURCE_TYPES
 */
export const SUPPORTED_RESOURCE_TYPES = [
  "EC2", "RDS", "ALB", "NLB", "TG", "AuroraRDS", "DocDB", "ElastiCache", "NAT",
  "Lambda", "VPN", "APIGW", "ACM", "Backup", "MQ", "CLB", "OpenSearch",
  "SQS", "ECS", "MSK", "DynamoDB", "CloudFront", "WAF",
  "Route53", "DX", "EFS", "S3", "SageMaker", "SNS",
] as const;

export type ResourceType = (typeof SUPPORTED_RESOURCE_TYPES)[number];

/**
 * Frontend integration MVP scope.
 *
 * The backend registry supports all `SUPPORTED_RESOURCE_TYPES`, but the current
 * frontend/backend integration path is intentionally narrowed to these types
 * until the workflows are complete end to end.
 */
export const FRONTEND_INTEGRATION_RESOURCE_TYPES = [
  "EC2",
  "RDS",
  "S3",
  "Lambda",
  "ALB",
] as const;
