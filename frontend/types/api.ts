import type { DashboardStats } from "./index";

export type { DashboardStats };

// --- 글로벌 필터 ---

export interface GlobalFilterParams {
  customer_id?: string;
  account_id?: string;
  service?: string;
}

// --- 페이지네이션 ---

export interface PaginationParams {
  page: number;
  page_size: number;
  sort?: string;
  order?: "asc" | "desc";
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// --- API 에러 ---

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// --- Dashboard ---

export interface AlarmSummary {
  total: number;
  alarm_count: number;
  ok_count: number;
  insufficient_count: number;
}

// --- 필터 상태 (URL searchParams 직렬화/파싱용) ---

export interface FilterState {
  customer_id?: string;
  account_id?: string;
  service?: string;
  page?: number;
  page_size?: number;
  sort?: string;
  order?: "asc" | "desc";
  resource_type?: string;
  search?: string;
  state?: AlarmStateFilter;
  monitoring?: boolean;
}

// --- 리소스 목록 필터 ---

export interface ResourceListParams extends GlobalFilterParams, PaginationParams {
  resource_type?: string;
  search?: string;
  monitoring?: boolean;
}

// --- 알람 목록 필터 ---

export type AlarmStateFilter = "ALL" | "ALARM" | "INSUFFICIENT_DATA" | "OK" | "OFF";

export interface AlarmListParams extends GlobalFilterParams, PaginationParams {
  state?: AlarmStateFilter;
  search?: string;
}

// --- 벌크 모니터링 ---

export interface BulkMonitoringRequest {
  resource_ids: string[];
  action: "enable" | "disable";
  thresholds?: Record<string, number>;
  custom_metrics?: CustomMetricConfig[];
}

export interface BulkOperationResponse {
  job_id: string;
  total: number;
  status: "pending";
}

// --- 작업 상태 ---

export type JobStatusValue =
  | "pending"
  | "in_progress"
  | "completed"
  | "partial_failure"
  | "failed";

export interface JobResult {
  status: "success" | "failed";
  // 리소스 단위 작업(예: bulk monitoring toggle)에서 채워짐
  resource_id?: string;
  error?: string;
  // 알람 동기화 작업(_handle_alarms_sync_job)에서 채워짐
  account_id?: string;
  regions?: string[];
  imported?: number;
  deleted?: number;
  // 리소스 인벤토리 동기화 작업(_handle_resources_sync_job)에서 채워짐
  discovered?: number;
  synced?: number;
  removed?: number;
}

export type SyncTarget = "alarms" | "resources";

export interface JobStatus {
  job_id: string;
  status: JobStatusValue;
  total_count: number;
  completed_count: number;
  failed_count: number;
  results: JobResult[];
}

// --- 커스텀 메트릭 ---

export interface CustomMetricConfig {
  metric_name: string;
  namespace: string;
  threshold: number;
  unit: string;
  direction: ">" | "<";
}

// --- 알람 설정 저장 ---

export interface AlarmConfigUpdate {
  metric_key: string;
  threshold: number;
  monitoring: boolean;
  unit?: string;
  direction?: ">" | ">=" | "<" | "<=";
  severity?: string;
  mount_path?: string;
}

export interface SaveAlarmConfigRequest {
  configs: AlarmConfigUpdate[];
}

// --- 고객사/어카운트 CRUD ---

export interface CreateCustomerRequest {
  name: string;
  code: string;
}

export interface CreateAccountRequest {
  account_id: string;
  role_arn: string;
  name: string;
  customer_id: string;
  regions: string[];
}

// --- 연결 테스트 ---

export interface ConnectionTestResult {
  status: "connected" | "failed";
  message?: string;
  error?: string;
  tested_at: string;
  regions?: Array<{
    region: string;
    status: "connected" | "failed";
    error?: string;
  }>;
}

// --- 임계치 오버라이드 ---

export interface ThresholdOverride {
  metric_key: string;
  system_default: number;
  customer_override: number | null;
  unit: string;
  direction: ">" | "<";
}

// --- CloudWatch 메트릭 목록 ---

export interface AvailableMetric {
  metric_name: string;
  namespace: string;
  unit: string | null;
  direction: ">" | ">=" | "<" | "<=";
  needs_mount_path: boolean;
}

// --- 알림 처리 내역 (GET /api/alert/events, review-personas F7) ---

/** 한 이벤트의 처리 결과. 라벨·설명은 백엔드가 정본을 준다 (`common/alert_verdict.py`). */
export interface AlertEventRow {
  occurred_at: string;
  series_id: string;
  event_key: string;
  customer_id: string;
  account_id: string;
  region: string;
  alarm_name: string;
  resource_id: string;
  resource_type: string;
  metric_key: string;
  severity: string;
  state: string;
  previous_state: string;
  state_reason: string;
  group_id: string;
  finalized_at: string;
  kind: "firing" | "clearing" | "config" | "other";
  action: "notify" | "suppress" | "pending";
  action_label: string;
  reason: string;
  reason_label: string;
  explanation: string;
  suppressed: boolean;
  finalized: boolean;
  /** 진동 격리가 풀리는 시각 (격리된 건에만 있다) */
  quarantined_until?: string;
  parse_error?: string;
}

export interface AlertEventSummary {
  total: number;
  notify: number;
  suppress: number;
  pending: number;
  config: number;
  suppression_rate: number;
}

export interface AlertEventsResponse {
  events: AlertEventRow[];
  summary: AlertEventSummary;
  days: number;
  truncated: boolean;
  limit: number;
}

export interface AlertSilence {
  id: string;
  customer_id: string;
  resource_id: string;
  severity: string;
  reason: string;
  starts_at: string;
  ends_at: string;
  active: boolean;
  expired: boolean;
  created_by: string;
}

export interface AlertSilencesResponse {
  silences: AlertSilence[];
  active: number;
}

// --- 알림 채널 (tasks 2.2, design-notification-channels.md) ---

/** 채널 유형이 스스로 선언한 설정 필드. 화면은 이걸로 폼을 그린다. */
export interface ChannelField {
  name: string;
  label: string;
  required: boolean;
  /** true면 값이 응답에 오지 않는다 — 화면은 "(설정됨)"만 갖는다 */
  secret: boolean;
  max_len: number;
}

export interface ChannelType {
  type: string;
  label: string;
  rate_limit_per_sec: number;
  fields: ChannelField[];
}

export interface ChannelTypeCatalogue {
  types: ChannelType[];
  match_fields: string[];
  severities: string[];
}

export interface NotificationChannel {
  channel_id: string;
  customer_id: string;
  name: string;
  type: string;
  type_label: string;
  /** 자격증명 필드는 값이 아니라 "(설정됨)"이 온다 */
  config: Record<string, string>;
  match: Record<string, string[]>;
  enabled: boolean;
  is_global: boolean;
}

export interface ChannelListResponse {
  channels: NotificationChannel[];
  total: number;
}

export interface ChannelInput {
  name: string;
  type: string;
  customer_id: string;
  config: Record<string, string>;
  match: Record<string, string[]>;
  enabled: boolean;
}
