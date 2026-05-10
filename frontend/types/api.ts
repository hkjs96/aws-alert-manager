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

export type AlarmStateFilter = "ALL" | "ALARM" | "INSUFFICIENT" | "OK" | "OFF";

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
  resource_id: string;
  status: "success" | "failed";
  error?: string;
}

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
}

// --- 연결 테스트 ---

export interface ConnectionTestResult {
  status: "connected" | "failed";
  message: string;
  tested_at: string;
}

// --- 임계치 오버라이드 ---

export interface ThresholdOverride {
  metric_key: string;
  system_default: number;
  customer_override: number | null;
  unit: string;
  direction: ">" | "<";
}

// --- 동기화 ---

export interface SyncResult {
  discovered: number;
  updated: number;
  removed: number;
}

// --- CloudWatch 메트릭 목록 ---

export interface AvailableMetric {
  metric_name: string;
  namespace: string;
}
