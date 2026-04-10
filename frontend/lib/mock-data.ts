import type {
  Alarm,
  Resource,
  Customer,
  Account,
  AlarmConfig,
  RecentAlarm,
  DashboardStats,
} from "@/types";
import type {
  AlarmSummary,
  AvailableMetric,
  ThresholdOverride,
} from "@/types/api";

// --- Customers ---
export const MOCK_CUSTOMERS: Customer[] = [
  { customer_id: "cust-001", name: "Acme Corp", provider: "aws", account_count: 2 },
  { customer_id: "cust-002", name: "Globex Inc", provider: "aws", account_count: 1 },
  { customer_id: "cust-003", name: "Initech", provider: "azure", account_count: 1 },
];

// --- Accounts ---
export const MOCK_ACCOUNTS: Account[] = [
  { account_id: "882311440092", customer_id: "cust-001", name: "Acme Production", role_arn: "arn:aws:iam::882311440092:role/MonitorRole", regions: ["us-east-1", "eu-central-1"], connection_status: "connected", last_tested_at: "2024-06-01T10:00:00Z" },
  { account_id: "440911228833", customer_id: "cust-001", name: "Acme Staging", role_arn: "arn:aws:iam::440911228833:role/MonitorRole", regions: ["us-west-2"], connection_status: "connected", last_tested_at: "2024-06-01T09:00:00Z" },
  { account_id: "112233445566", customer_id: "cust-002", name: "Globex Main", role_arn: "arn:aws:iam::112233445566:role/MonitorRole", regions: ["ap-northeast-2"], connection_status: "failed", last_tested_at: "2024-05-28T15:00:00Z" },
  { account_id: "998877665544", customer_id: "cust-003", name: "Initech Azure", role_arn: "arn:aws:iam::998877665544:role/MonitorRole", regions: ["us-east-1"], connection_status: "untested" },
];

// --- Resources ---
export const MOCK_RESOURCES: Resource[] = [
  { id: "i-0a2b4c6d8e0f12", name: "payments-api-prod-01", type: "EC2", account: "882311440092", region: "us-east-1", monitoring: true, alarms: { critical: 2, warning: 0 } },
  { id: "arn:aws:s3:::user-data-store", name: "user-static-assets", type: "S3", account: "882311440092", region: "eu-central-1", monitoring: true, alarms: { critical: 0, warning: 0 } },
  { id: "db-XYZ9908821-RDS", name: "auth-db-postgres", type: "RDS", account: "440911228833", region: "us-west-2", monitoring: true, alarms: { critical: 0, warning: 1 } },
  { id: "arn:aws:lambda:u...worker", name: "image-processor-worker", type: "LAMBDA", account: "882311440092", region: "us-east-1", monitoring: false, alarms: { critical: 0, warning: 0 } },
  { id: "alb-prod-external-332", name: "main-ingress-lb", type: "ALB", account: "882311440092", region: "us-east-1", monitoring: true, alarms: { critical: 0, warning: 0 } },
  { id: "i-0f1e2d3c4b5a69", name: "web-server-prod-02", type: "EC2", account: "882311440092", region: "us-east-1", monitoring: true, alarms: { critical: 1, warning: 1 } },
  { id: "db-ABC1234567-RDS", name: "orders-db-mysql", type: "RDS", account: "440911228833", region: "us-west-2", monitoring: false, alarms: { critical: 0, warning: 0 } },
  { id: "arn:aws:lambda:u...notifier", name: "email-notifier", type: "LAMBDA", account: "112233445566", region: "ap-northeast-2", monitoring: true, alarms: { critical: 0, warning: 0 } },
  { id: "alb-staging-internal-221", name: "staging-internal-lb", type: "ALB", account: "440911228833", region: "us-west-2", monitoring: false, alarms: { critical: 0, warning: 0 } },
  { id: "arn:aws:s3:::log-archive", name: "log-archive-bucket", type: "S3", account: "112233445566", region: "ap-northeast-2", monitoring: true, alarms: { critical: 0, warning: 1 } },
  { id: "i-9a8b7c6d5e4f33", name: "batch-worker-01", type: "EC2", account: "112233445566", region: "ap-northeast-2", monitoring: true, alarms: { critical: 0, warning: 0 } },
  { id: "arn:aws:lambda:u...cron", name: "scheduled-cron-job", type: "LAMBDA", account: "882311440092", region: "us-east-1", monitoring: true, alarms: { critical: 1, warning: 0 } },
];

// --- Alarms ---
export const MOCK_ALARMS: Alarm[] = [
  { id: "alm-001", time: "14:22:05 UTC", resource: "payments-api-prod-01", arn: "arn:aws:ec2:us-east-1:882311440092:inst/i-0a2b", type: "EC2", metric: "CPUUtilization", state: "ALARM", value: "94.2% > 85.0%" },
  { id: "alm-002", time: "14:18:32 UTC", resource: "auth-db-postgres", arn: "arn:aws:rds:us-west-2:440911228833:db/auth", type: "RDS", metric: "FreeStorageSpace", state: "INSUFFICIENT", value: "5.2GB < 10GB" },
  { id: "alm-003", time: "14:15:00 UTC", resource: "user-static-assets", arn: "arn:aws:s3:::user-data-store", type: "S3", metric: "BucketSizeBytes", state: "OK", value: "128GB < 500GB" },
  { id: "alm-004", time: "14:12:44 UTC", resource: "image-processor-worker", arn: "arn:aws:lambda:us-east-1:882311440092:fn/img", type: "LAMBDA", metric: "Errors", state: "OFF", value: "0 = 0" },
  { id: "alm-005", time: "14:10:12 UTC", resource: "main-ingress-lb", arn: "arn:aws:elasticloadbalancing:us-east-1:882311440092:lb/alb", type: "ALB", metric: "HTTPCode_ELB_5XX_Count", state: "ALARM", value: "72 > 50" },
  { id: "alm-006", time: "13:55:00 UTC", resource: "web-server-prod-02", arn: "arn:aws:ec2:us-east-1:882311440092:inst/i-0f1e", type: "EC2", metric: "mem_used_percent", state: "ALARM", value: "92.1% > 80.0%" },
  { id: "alm-007", time: "13:48:22 UTC", resource: "orders-db-mysql", arn: "arn:aws:rds:us-west-2:440911228833:db/orders", type: "RDS", metric: "CPUUtilization", state: "OK", value: "45.0% < 80.0%" },
  { id: "alm-008", time: "13:30:10 UTC", resource: "email-notifier", arn: "arn:aws:lambda:ap-northeast-2:112233445566:fn/email", type: "LAMBDA", metric: "Duration", state: "OK", value: "2500ms < 10000ms" },
  { id: "alm-009", time: "13:22:05 UTC", resource: "log-archive-bucket", arn: "arn:aws:s3:::log-archive", type: "S3", metric: "BucketSizeBytes", state: "INSUFFICIENT", value: "N/A" },
  { id: "alm-010", time: "13:10:00 UTC", resource: "scheduled-cron-job", arn: "arn:aws:lambda:us-east-1:882311440092:fn/cron", type: "LAMBDA", metric: "Errors", state: "ALARM", value: "12 > 5" },
  { id: "alm-011", time: "12:55:33 UTC", resource: "batch-worker-01", arn: "arn:aws:ec2:ap-northeast-2:112233445566:inst/i-9a8b", type: "EC2", metric: "StatusCheckFailed", state: "OK", value: "0 = 0" },
  { id: "alm-012", time: "12:40:15 UTC", resource: "staging-internal-lb", arn: "arn:aws:elasticloadbalancing:us-west-2:440911228833:lb/alb", type: "ALB", metric: "TargetResponseTime", state: "OFF", value: "N/A" },
];

// --- Recent Alarms (for Dashboard) ---
export const MOCK_RECENT_ALARMS: RecentAlarm[] = [
  { timestamp: "2024-06-15T14:22:05Z", resource_id: "i-0a2b4c6d8e0f12", resource_name: "payments-api-prod-01", resource_type: "EC2", metric: "CPUUtilization", severity: "SEV-1", state_change: "OK → ALARM", value: 94.2, threshold: 85.0 },
  { timestamp: "2024-06-15T14:18:32Z", resource_id: "db-XYZ9908821-RDS", resource_name: "auth-db-postgres", resource_type: "RDS", metric: "FreeStorageSpace", severity: "SEV-2", state_change: "OK → INSUFFICIENT", value: 5.2, threshold: 10.0 },
  { timestamp: "2024-06-15T13:55:00Z", resource_id: "i-0f1e2d3c4b5a69", resource_name: "web-server-prod-02", resource_type: "EC2", metric: "mem_used_percent", severity: "SEV-2", state_change: "OK → ALARM", value: 92.1, threshold: 80.0 },
  { timestamp: "2024-06-15T13:10:00Z", resource_id: "arn:aws:lambda:u...cron", resource_name: "scheduled-cron-job", resource_type: "LAMBDA", metric: "Errors", severity: "SEV-3", state_change: "OK → ALARM", value: 12, threshold: 5 },
  { timestamp: "2024-06-15T12:55:33Z", resource_id: "i-9a8b7c6d5e4f33", resource_name: "batch-worker-01", resource_type: "EC2", metric: "StatusCheckFailed", severity: "SEV-1", state_change: "ALARM → OK", value: 0, threshold: 0 },
];

// --- Dashboard Stats ---
export const MOCK_DASHBOARD_STATS: DashboardStats = {
  monitored_count: 8,
  active_alarms: 4,
  unmonitored_count: 4,
  account_count: 4,
};

// --- Alarm Summary ---
export const MOCK_ALARM_SUMMARY: AlarmSummary = {
  total: 12,
  alarm_count: 4,
  ok_count: 4,
  insufficient_count: 2,
};

// --- Alarm Configs (per resource) ---
export function getMockAlarmConfigs(resourceId: string): AlarmConfig[] {
  const resource = MOCK_RESOURCES.find((r) => r.id === resourceId);
  if (!resource) return [];
  const typeMetrics = TYPE_DEFAULT_METRICS[resource.type] ?? [];
  return typeMetrics.map((m) => ({
    metric_key: m.key,
    metric_name: m.name,
    namespace: resource.type === "EC2" ? (m.name.startsWith("mem_") || m.name.startsWith("disk_") || m.name.startsWith("swap_") ? "CWAgent" : "AWS/EC2") : `AWS/${resource.type}`,
    threshold: m.threshold,
    unit: m.unit,
    direction: m.direction as ">" | "<",
    severity: "SEV-3" as const,
    source: "System" as const,
    state: resource.monitoring ? "OK" as const : "OFF" as const,
    current_value: resource.monitoring ? m.threshold * 0.6 : null,
    monitoring: resource.monitoring,
    period: 300,
    evaluation_periods: 1,
    datapoints_to_alarm: 1,
    treat_missing_data: "missing" as const,
    statistic: "Average" as const,
  }));
}

// --- Events (per resource) ---
export function getMockEvents(resourceId: string): RecentAlarm[] {
  return MOCK_RECENT_ALARMS.filter((a) => a.resource_id === resourceId);
}

// --- Available Metrics (per resource type) ---
export function getMockAvailableMetrics(resourceId: string): AvailableMetric[] {
  const resource = MOCK_RESOURCES.find((r) => r.id === resourceId);
  if (!resource) return [];
  return MOCK_AVAILABLE_METRICS[resource.type] ?? [];
}

// --- Threshold Overrides (per resource type) ---
export function getMockThresholdOverrides(resourceType: string): ThresholdOverride[] {
  const metrics = TYPE_DEFAULT_METRICS[resourceType] ?? [];
  return metrics.map((m) => ({
    metric_key: m.key,
    system_default: m.threshold,
    customer_override: null,
    unit: m.unit,
    direction: m.direction as ">" | "<",
  }));
}

// --- Pagination helper ---
export function paginate<T>(items: T[], page: number, pageSize: number) {
  const start = (page - 1) * pageSize;
  return {
    items: items.slice(start, start + pageSize),
    total: items.length,
    page,
    page_size: pageSize,
  };
}

// Type-specific default metrics
export const TYPE_DEFAULT_METRICS: Record<string, { key: string; name: string; threshold: number; unit: string; direction: string }[]> = {
  EC2: [
    { key: "CPU", name: "CPUUtilization", threshold: 80, unit: "%", direction: ">" },
    { key: "Memory", name: "mem_used_percent", threshold: 80, unit: "%", direction: ">" },
    { key: "Disk", name: "disk_used_percent", threshold: 80, unit: "%", direction: ">" },
    { key: "StatusCheck", name: "StatusCheckFailed", threshold: 0, unit: "", direction: ">" },
  ],
  RDS: [
    { key: "CPU", name: "CPUUtilization", threshold: 80, unit: "%", direction: ">" },
    { key: "FreeMemory", name: "FreeableMemory", threshold: 2, unit: "GB", direction: "<" },
    { key: "FreeStorage", name: "FreeStorageSpace", threshold: 10, unit: "GB", direction: "<" },
    { key: "Connections", name: "DatabaseConnections", threshold: 100, unit: "Count", direction: ">" },
    { key: "ReadLatency", name: "ReadLatency", threshold: 0.02, unit: "s", direction: ">" },
    { key: "WriteLatency", name: "WriteLatency", threshold: 0.02, unit: "s", direction: ">" },
  ],
  S3: [
    { key: "BucketSize", name: "BucketSizeBytes", threshold: 500, unit: "GB", direction: ">" },
    { key: "Objects", name: "NumberOfObjects", threshold: 1000000, unit: "Count", direction: ">" },
  ],
  LAMBDA: [
    { key: "Errors", name: "Errors", threshold: 5, unit: "Count", direction: ">" },
    { key: "Duration", name: "Duration", threshold: 10000, unit: "ms", direction: ">" },
    { key: "Throttles", name: "Throttles", threshold: 0, unit: "Count", direction: ">" },
  ],
  ALB: [
    { key: "5XX", name: "HTTPCode_ELB_5XX_Count", threshold: 50, unit: "Count", direction: ">" },
    { key: "ResponseTime", name: "TargetResponseTime", threshold: 2, unit: "s", direction: ">" },
    { key: "HealthyHosts", name: "HealthyHostCount", threshold: 2, unit: "Count", direction: "<" },
    { key: "UnhealthyHosts", name: "UnHealthyHostCount", threshold: 0, unit: "Count", direction: ">" },
  ],
};

// Mock: available CloudWatch metrics per resource type
export const MOCK_AVAILABLE_METRICS: Record<string, AvailableMetric[]> = {
  EC2: [
    { metric_name: "CPUCreditBalance", namespace: "AWS/EC2" },
    { metric_name: "NetworkIn", namespace: "AWS/EC2" },
    { metric_name: "NetworkOut", namespace: "AWS/EC2" },
    { metric_name: "DiskReadOps", namespace: "AWS/EC2" },
    { metric_name: "DiskWriteOps", namespace: "AWS/EC2" },
    { metric_name: "NetworkPacketsIn", namespace: "AWS/EC2" },
    { metric_name: "swap_used_percent", namespace: "CWAgent" },
  ],
  RDS: [
    { metric_name: "CommitLatency", namespace: "AWS/RDS" },
    { metric_name: "ReplicaLag", namespace: "AWS/RDS" },
    { metric_name: "SwapUsage", namespace: "AWS/RDS" },
    { metric_name: "BinLogDiskUsage", namespace: "AWS/RDS" },
  ],
  S3: [
    { metric_name: "4xxErrors", namespace: "AWS/S3" },
    { metric_name: "5xxErrors", namespace: "AWS/S3" },
    { metric_name: "FirstByteLatency", namespace: "AWS/S3" },
  ],
  LAMBDA: [
    { metric_name: "ConcurrentExecutions", namespace: "AWS/Lambda" },
    { metric_name: "IteratorAge", namespace: "AWS/Lambda" },
    { metric_name: "DeadLetterErrors", namespace: "AWS/Lambda" },
  ],
  ALB: [
    { metric_name: "RequestCount", namespace: "AWS/ApplicationELB" },
    { metric_name: "ActiveConnectionCount", namespace: "AWS/ApplicationELB" },
    { metric_name: "ProcessedBytes", namespace: "AWS/ApplicationELB" },
  ],
};
