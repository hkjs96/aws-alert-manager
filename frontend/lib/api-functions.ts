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
  AvailableMetric,
  AlarmSummary,
  DashboardStats,
  JobStatus,
} from "@/types/api";
import type { AlarmConfig, Resource, Customer, Account, RecentAlarm, Alarm } from "@/types/index";
import { apiFetch, buildFilterParams, buildQueryString } from "./api";
import { encodeResourceId } from "./resource-id";

type ApiResource = Resource & { account_id?: string };

function normalizeResource(resource: ApiResource): Resource {
  return {
    ...resource,
    account: resource.account || resource.account_id || "",
  };
}

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
  return apiFetch<PaginatedResponse<ApiResource>>(`/api/resources${qs ? `?${qs}` : ""}`).then((data) => ({
    ...data,
    items: data.items.map(normalizeResource),
  }));
}

export function syncResources(scope: {
  customer_id?: string;
  account_id?: string;
  regions?: string[];
}): Promise<{ job_id: string; status: string; total_count: number }> {
  return apiFetch("/api/resources/sync", {
    method: "POST",
    body: JSON.stringify({ scope }),
  });
}

export function fetchResource(id: string): Promise<Resource> {
  return apiFetch<ApiResource>(`/api/resources/${encodeResourceId(id)}`).then(normalizeResource);
}

export function fetchAlarmConfigs(id: string): Promise<AlarmConfig[]> {
  return apiFetch(`/api/resources/${encodeResourceId(id)}/alarms`);
}

export function saveAlarmConfigs(
  id: string,
  configs: SaveAlarmConfigRequest,
): Promise<JobStatus> {
  return apiFetch(`/api/resources/${encodeResourceId(id)}/alarms`, {
    method: "PUT",
    body: JSON.stringify(configs),
  });
}

export function toggleMonitoring(
  id: string,
  enabled: boolean,
): Promise<JobStatus> {
  return apiFetch(`/api/resources/${encodeResourceId(id)}/monitoring`, {
    method: "PUT",
    body: JSON.stringify({ monitoring: enabled }),
  });
}

export function fetchAvailableMetrics(id: string): Promise<AvailableMetric[]> {
  return apiFetch(`/api/resources/${encodeResourceId(id)}/metrics`);
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

// --- Current user ---

export interface MeResponse {
  email: string;
  is_admin: boolean;
  owned_customer_ids: string[];
}

export function fetchMe(): Promise<MeResponse> {
  return apiFetch("/api/me");
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

export function testConnection(id: string, customerId: string): Promise<ConnectionTestResult> {
  const qs = buildQueryString({ customer_id: customerId });
  return apiFetch(`/api/accounts/${id}/test?${qs}`, { method: "POST" });
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
  customerId?: string,
): Promise<void> {
  return apiFetch(`/api/thresholds/${type}`, {
    method: "PUT",
    body: JSON.stringify({ customer_id: customerId ?? "", overrides }),
  });
}

// --- Sync ---

export function syncAlarms(scope: {
  customer_id?: string;
  account_id?: string;
  regions?: string[];
}): Promise<{ job_id: string; status: string; total_count: number }> {
  return apiFetch("/api/sync/alarms", {
    method: "POST",
    body: JSON.stringify({ scope }),
  });
}

export function fetchJobStatus(id: string): Promise<JobStatus> {
  return apiFetch(`/api/jobs/${id}`);
}
