import type { SeverityLevel, AlarmState, SourceType } from "@/types";

// ──────────────────────────────────────────────
// Supported Resource Types (30종, Phase1 common/__init__.py 기준)
// ──────────────────────────────────────────────

export const SUPPORTED_RESOURCE_TYPES = [
  "EC2", "RDS", "AuroraRDS", "ALB", "NLB", "CLB", "TG",
  "DocDB", "ElastiCache", "NAT", "Lambda", "VPN", "APIGW",
  "ACM", "Backup", "MQ", "OpenSearch", "SQS", "ECS", "MSK",
  "DynamoDB", "CloudFront", "WAF", "Route53", "DX", "EFS",
  "S3", "SageMaker", "SNS",
] as const;

export type ResourceType = (typeof SUPPORTED_RESOURCE_TYPES)[number];

// ──────────────────────────────────────────────
// Resource Type Categories
// ──────────────────────────────────────────────

export const RESOURCE_TYPE_CATEGORIES: Record<string, ResourceType[]> = {
  Compute: ["EC2", "Lambda", "ECS", "SageMaker"],
  Database: ["RDS", "AuroraRDS", "DocDB", "ElastiCache", "DynamoDB"],
  Network: ["ALB", "NLB", "CLB", "TG", "NAT", "VPN", "Route53", "DX", "CloudFront"],
  Storage: ["S3", "EFS", "Backup"],
  Application: ["APIGW", "SQS", "MSK", "SNS", "MQ"],
  Security: ["WAF", "ACM", "OpenSearch"],
};

// ──────────────────────────────────────────────
// Severity
// ──────────────────────────────────────────────

export const SEVERITY_COLORS: Record<SeverityLevel, string> = {
  "SEV-1": "#dc2626",
  "SEV-2": "#ea580c",
  "SEV-3": "#d97706",
  "SEV-4": "#2563eb",
  "SEV-5": "#6b7280",
};

export const SEVERITY_LABELS: Record<SeverityLevel, string> = {
  "SEV-1": "Critical",
  "SEV-2": "High",
  "SEV-3": "Medium",
  "SEV-4": "Low",
  "SEV-5": "Info",
};

export const DEFAULT_SEVERITY: Record<string, SeverityLevel> = {
  StatusCheckFailed: "SEV-1",
  HealthyHostCount: "SEV-1",
  TunnelState: "SEV-1",
  ClusterStatusRed: "SEV-1",
  ConnectionState: "SEV-1",
  HealthCheckStatus: "SEV-1",
  ELB5XX: "SEV-2",
  CLB5XX: "SEV-2",
  Errors: "SEV-2",
  UnHealthyHostCount: "SEV-2",
  CPU: "SEV-3",
  Memory: "SEV-3",
  Disk: "SEV-3",
  FreeMemoryGB: "SEV-3",
  FreeStorageGB: "SEV-3",
  FreeLocalStorageGB: "SEV-3",
  EngineCPU: "SEV-3",
  ACUUtilization: "SEV-3",
  DaysToExpiry: "SEV-3",
  ReadLatency: "SEV-4",
  WriteLatency: "SEV-4",
  TargetResponseTime: "SEV-4",
  TGResponseTime: "SEV-4",
  Duration: "SEV-4",
  ApiLatency: "SEV-4",
  RequestCount: "SEV-5",
  Connections: "SEV-5",
  ProcessedBytes: "SEV-5",
  ActiveFlowCount: "SEV-5",
  NewFlowCount: "SEV-5",
  ConnectionAttempts: "SEV-5",
  BytesInPerSec: "SEV-5",
};

export function getSeverity(metricKey: string): SeverityLevel {
  return DEFAULT_SEVERITY[metricKey] ?? "SEV-5";
}

// ──────────────────────────────────────────────
// Alarm State Colors
// ──────────────────────────────────────────────

export const ALARM_STATE_COLORS: Record<AlarmState, string> = {
  OK: "#16a34a",
  ALARM: "#dc2626",
  INSUFFICIENT_DATA: "#d97706",
  OFF: "#9ca3af",
};

// ──────────────────────────────────────────────
// Source Badge Styles
// ──────────────────────────────────────────────

export const SOURCE_BADGE_STYLES: Record<SourceType, { bg: string; text: string }> = {
  System: { bg: "#f1f5f9", text: "#64748b" },
  Customer: { bg: "#eff6ff", text: "#2563eb" },
  Custom: { bg: "#f5f3ff", text: "#7c3aed" },
};

// ──────────────────────────────────────────────
// Direction Styles
// ──────────────────────────────────────────────

export const DIRECTION_STYLES = {
  ">": { icon: "▲", color: "#ea580c", label: "GreaterThan" },
  "<": { icon: "▼", color: "#2563eb", label: "LessThan" },
} as const;
