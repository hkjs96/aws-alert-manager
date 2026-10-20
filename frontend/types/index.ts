export type View = "dashboard" | "resources" | "alarms" | "settings" | "detail";

export type AlarmState = "ALARM" | "OK" | "INSUFFICIENT_DATA" | "OFF" | "MUTED";

export interface Alarm {
  id: string;
  time: string;
  resource: string;
  arn: string;
  account: string;
  type: string;
  metric: string;
  mount_path?: string | null;
  state: AlarmState;
  value?: string | null;
}

export interface Resource {
  id: string;
  name: string;
  type: string;
  account: string;
  region: string;
  monitoring: boolean;
  alarm_count: number;
  alarms: { critical: number; warning: number };
  inventory_source: "aws" | "db" | "alarms";
  persisted: boolean;
  status: "active" | "missing" | "deleted" | "orphan_candidate";
}

export type SeverityLevel = "SEV-1" | "SEV-2" | "SEV-3" | "SEV-4" | "SEV-5";
export type SourceType = "System" | "Customer" | "Custom";
export type DirectionSimple = ">" | ">=" | "<" | "<=";
export type CloudProvider = "aws" | "azure" | "gcp";

export type TreatMissingData = "missing" | "breaching" | "notBreaching" | "ignore";
export type AlarmStatistic = "Average" | "Sum" | "Maximum" | "Minimum" | "SampleCount";

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
  // Advanced settings (read-only in Phase 1, editable in Phase 2)
  period?: number;                       // seconds (default: 300)
  evaluation_periods?: number;           // default: 1
  datapoints_to_alarm?: number;          // default: 1
  treat_missing_data?: TreatMissingData; // default: "missing"
  statistic?: AlarmStatistic;            // default: "Average"
}

export interface Customer {
  customer_id: string;
  name: string;
  provider: CloudProvider;
  account_count: number;
  /** 담당자 이메일 — 접근 권한. 일반 사용자는 여기에 든 고객사만 본다(docs/specs/authz-scoping). */
  managers?: string[];
}

export interface Account {
  account_id: string;
  customer_id: string;
  name: string;
  role_arn: string;
  regions: string[];
  connection_status: "connected" | "failed" | "untested";
  last_tested_at?: string;
  /** 마지막 연결 테스트가 찾은, 리소스가 있는 리전. */
  detected_regions?: string[];
}

export interface DashboardStats {
  monitored_count: number;
  active_alarms: number;
  unmonitored_count: number;
  account_count: number;
  /** 지금 ALARM 상태 — 우리가 만든 알람 / 고객이 만든 알람. 고객 쪽 null = 실시간 조회 실패. */
  active_alarms_ours?: number;
  active_alarms_customer?: number | null;
  accounts_connected?: number;
  accounts_failed?: number;
}

export interface RecentAlarm {
  timestamp: string;
  resource_id: string;
  account: string;
  resource_name: string;
  resource_type: string;
  metric: string;
  severity: SeverityLevel;
  state_change: string;
  value: number;
  threshold: number;
}
