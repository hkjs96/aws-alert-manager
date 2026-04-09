export type View = "dashboard" | "resources" | "alarms" | "settings" | "detail";

export type AlarmState = "ALARM" | "OK" | "INSUFFICIENT" | "OFF" | "MUTED";

export interface Alarm {
  id: string;
  time: string;
  resource: string;
  arn: string;
  type: string;
  metric: string;
  state: AlarmState;
  value: string;
}

export interface Resource {
  id: string;
  name: string;
  type: string;
  account: string;
  region: string;
  monitoring: boolean;
  alarms: { critical: number; warning: number };
}

export type SeverityLevel = "SEV-1" | "SEV-2" | "SEV-3" | "SEV-4" | "SEV-5";
export type SourceType = "System" | "Customer" | "Custom";
export type DirectionSimple = ">" | "<";
export type CloudProvider = "aws" | "azure" | "gcp";

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
