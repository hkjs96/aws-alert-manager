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
