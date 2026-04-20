import type {
  GlobalFilterParams,
  PaginationParams,
  PaginatedResponse,
  ResourceListParams,
  AlarmListParams,
  BulkMonitoringRequest,
  BulkOperationResponse,
  SaveAlarmConfigRequest,
  CreateCustomerRequest,
  CreateAccountRequest,
  ConnectionTestResult,
  ThresholdOverride,
  SyncResult,
  AvailableMetric,
  AlarmSummary,
  DashboardStats,
  JobStatus,
} from "@/types/api";
import type { AlarmConfig, Resource, Customer, Account, RecentAlarm, Alarm } from "@/types/index";
import { apiFetch, buildFilterParams, buildQueryString } from "./api";

// --- Dashboard ---

export function fetchDashboardStats(filters: GlobalFilterParams): Promise<DashboardStats> {
  const qs = buildFilterParams(filters).toString();
  return apiFetch(`/api/dashboard/stats${qs ? `?${qs}` : ""}`);
}

export function fetchRecentAlarms(
  filters: GlobalFilterParams,
  pagination: PaginationParams,
): Promise<PaginatedResponse<RecentAlarm>> {
  const qs = buildQueryString({ ...filters, ...pagination });
  return apiFetch(`/api/dashboard/recent-alarms${qs ? `?${qs}` : ""}`);
}

// --- Resources ---

export function fetchResources(
  params: ResourceListParams,
): Promise<PaginatedResponse<Resource>> {
  const qs = buildQueryString(params as unknown as Record<string, string | number | boolean | undefined>);
  return apiFetch(`/api/resources${qs ? `?${qs}` : ""}`);
}

export function syncResources(filters: GlobalFilterParams): Promise<SyncResult> {
  const qs = buildFilterParams(filters).toString();
  return apiFetch(`/api/resources/sync${qs ? `?${qs}` : ""}`, { method: "POST" });
}

export function fetchResource(id: string): Promise<Resource> {
  return apiFetch(`/api/resources/${id}`);
}

export function fetchAlarmConfigs(id: string): Promise<AlarmConfig[]> {
  return apiFetch(`/api/resources/${id}/alarms`);
}

export function saveAlarmConfigs(
  id: string,
  configs: SaveAlarmConfigRequest,
): Promise<JobStatus> {
  return apiFetch(`/api/resources/${id}/alarms`, {
    method: "PUT",
    body: JSON.stringify(configs),
  });
}

export function toggleMonitoring(
  id: string,
  enabled: boolean,
): Promise<JobStatus> {
  return apiFetch(`/api/resources/${id}/monitoring`, {
    method: "PUT",
    body: JSON.stringify({ monitoring: enabled }),
  });
}

export function fetchAvailableMetrics(id: string): Promise<AvailableMetric[]> {
  return apiFetch(`/api/resources/${id}/metrics`);
}

// --- Bulk ---

export function bulkMonitoring(
  request: BulkMonitoringRequest,
): Promise<BulkOperationResponse> {
  return apiFetch("/api/bulk/monitoring", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

// --- Alarms ---

export function fetchAlarms(
  params: AlarmListParams,
): Promise<PaginatedResponse<Alarm>> {
  const qs = buildQueryString(params as unknown as Record<string, string | number | boolean | undefined>);
  return apiFetch(`/api/alarms${qs ? `?${qs}` : ""}`);
}

export function fetchAlarmSummary(filters: GlobalFilterParams): Promise<AlarmSummary> {
  const qs = buildFilterParams(filters).toString();
  return apiFetch(`/api/alarms/summary${qs ? `?${qs}` : ""}`);
}

// --- Customers ---

export function fetchCustomers(): Promise<Customer[]> {
  return apiFetch("/api/customers");
}

export function createCustomer(data: CreateCustomerRequest): Promise<Customer> {
  return apiFetch("/api/customers", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function deleteCustomer(id: string): Promise<void> {
  return apiFetch(`/api/customers/${id}`, { method: "DELETE" });
}

// --- Accounts ---

export function fetchAccounts(): Promise<Account[]> {
  return apiFetch("/api/accounts");
}

export function createAccount(data: CreateAccountRequest): Promise<Account> {
  return apiFetch("/api/accounts", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function testConnection(id: string): Promise<ConnectionTestResult> {
  return apiFetch(`/api/accounts/${id}/test`, { method: "POST" });
}

// --- Thresholds ---

export function fetchThresholds(
  type: string,
  filters: GlobalFilterParams,
): Promise<ThresholdOverride[]> {
  const qs = buildFilterParams(filters).toString();
  return apiFetch(`/api/thresholds/${type}${qs ? `?${qs}` : ""}`);
}

export function saveThresholds(
  type: string,
  overrides: ThresholdOverride[],
): Promise<void> {
  return apiFetch(`/api/thresholds/${type}`, {
    method: "PUT",
    body: JSON.stringify(overrides),
  });
}
