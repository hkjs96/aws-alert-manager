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
 * Frontend integration scope.
 *
 * Now at full parity with the backend registry: every backend-supported type is
 * exposed in the UI filters, settings threshold tabs, and primary workflows.
 * The threshold tabs are data-driven from the backend `/thresholds/{type}`
 * endpoint (which already serves all types), and the alarm-creation metric
 * catalog (`METRICS_BY_TYPE`) covers all types, so this list intentionally
 * mirrors `SUPPORTED_RESOURCE_TYPES`. Keep it as a distinct named export so the
 * UI vs backend-contract intent stays explicit at call sites.
 */
export const FRONTEND_INTEGRATION_RESOURCE_TYPES = SUPPORTED_RESOURCE_TYPES;
