// ──────────────────────────────────────────────
// Alarm States & Severity
// ──────────────────────────────────────────────

export type AlarmState = "OK" | "ALARM" | "INSUFFICIENT_DATA" | "OFF";

export type SeverityLevel = "SEV-1" | "SEV-2" | "SEV-3" | "SEV-4" | "SEV-5";

export type SourceType = "System" | "Customer" | "Custom";

export type Direction = "GreaterThanThreshold" | "GreaterThanOrEqualToThreshold"
  | "LessThanThreshold" | "LessThanOrEqualToThreshold";

export type DirectionSimple = ">" | "<";

export type CloudProvider = "aws" | "azure" | "gcp";

// ──────────────────────────────────────────────
// Resource
// ──────────────────────────────────────────────

export interface Resource {
  id: string;
  name: string;
  type: string;
  account_id: string;
  customer_id: string;
  region: string;
  provider: CloudProvider;
  monitoring: boolean;
  active_alarms: AlarmSummary[];
  tags: Record<string, string>;
}

export interface AlarmSummary {
  count: number;
  severity: SeverityLevel;
}

// ──────────────────────────────────────────────
// Alarm Configuration
// ──────────────────────────────────────────────

export interface AlarmConfig {
  metric_key: string;
  metric_name: string;
  namespace: string;
  threshold: number;
  unit: string;
  direction: DirectionSimple;
  severity: SeverityLevel;
  source: SourceType;
  state: AlarmState;
  current_value: number | null;
  monitoring: boolean;
  mount_path?: string;
}

// ──────────────────────────────────────────────
// Customer & Account
// ──────────────────────────────────────────────

export interface Customer {
  customer_id: string;
  name: string;
  provider: CloudProvider;
  account_count: number;
}

export interface Account {
  account_id: string;
  customer_id: string;
  name: string;
  role_arn: string;
  regions: string[];
  connection_status: "connected" | "failed" | "untested";
  last_tested_at?: string;
}

// ──────────────────────────────────────────────
// Threshold Override
// ──────────────────────────────────────────────

export interface ThresholdOverride {
  customer_id: string;
  resource_type: string;
  metric_key: string;
  threshold_value: number;
  updated_by?: string;
  updated_at?: string;
}

// ──────────────────────────────────────────────
// Job (async bulk operations)
// ──────────────────────────────────────────────

export type JobStatus = "pending" | "in_progress" | "completed" | "partial_failure" | "failed";

export interface Job {
  job_id: string;
  job_type: string;
  status: JobStatus;
  total_count: number;
  completed_count: number;
  failed_count: number;
  created_at: string;
  updated_at?: string;
  results?: JobResult[];
}

export interface JobResult {
  resource_id: string;
  status: "success" | "failed";
  error?: string;
}

// ──────────────────────────────────────────────
// Metric (for autocomplete)
// ──────────────────────────────────────────────

export interface MetricInfo {
  metric_name: string;
  namespace: string;
  dimensions: Record<string, string>;
  unit?: string;
}

// ──────────────────────────────────────────────
// API Responses
// ──────────────────────────────────────────────

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface DashboardStats {
  monitored_count: number;
  active_alarms: number;
  unmonitored_count: number;
  account_count: number;
}

export interface RecentAlarm {
  timestamp: string;
  resource_id: string;
  resource_name: string;
  resource_type: string;
  metric: string;
  severity: SeverityLevel;
  state_change: string;
  value: number;
  threshold: number;
}
