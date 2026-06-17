/**
 * Server-side API Gateway data access. Runtime pages must not fall back to mock data.
 */

import type {
  Account,
  Alarm,
  AlarmConfig,
  Customer,
  DirectionSimple,
  RecentAlarm,
  Resource,
} from "@/types";
import type { AlarmSummary, DashboardStats } from "@/types/api";
import { encodeResourceId } from "@/lib/resource-id";
import { auth } from "@/auth";

const API_BASE_URL =
  process.env.API_GATEWAY_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  process.env.API_BASE_URL ??
  "";

type ApiResource = Resource & { account_id?: string };

// Server components fetch API Gateway directly (no proxy hop), so they must
// attach the Google ID token themselves when auth is enabled. The token is
// read from the request cookies server-side and never exposed to the browser.
async function authHeaders(): Promise<Record<string, string>> {
  if (!process.env.AUTH_SECRET) {
    return {};
  }
  const session = await auth();
  const idToken = session?.id_token;
  return idToken ? { Authorization: `Bearer ${idToken}` } : {};
}

async function apiFetch<T>(path: string): Promise<T> {
  if (!API_BASE_URL) {
    throw new Error("API Gateway URL is not configured");
  }
  const res = await fetch(`${API_BASE_URL}${path}`, {
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
  });
  if (!res.ok) {
    throw new Error(`API ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

function normalizeResource(resource: ApiResource): Resource {
  return {
    ...resource,
    account: resource.account || resource.account_id || "",
  };
}

export async function fetchAlarms(): Promise<Alarm[]> {
  const data = await apiFetch<{ items: Alarm[] }>("/api/alarms?page_size=100");
  return data.items;
}

export async function fetchResources(): Promise<Resource[]> {
  const data = await apiFetch<{ items: ApiResource[] }>("/api/resources?page_size=100");
  return data.items.map(normalizeResource);
}

export async function fetchCustomers(): Promise<Customer[]> {
  return apiFetch<Customer[]>("/api/customers");
}

export async function fetchAccounts(): Promise<Account[]> {
  return apiFetch<Account[]>("/api/accounts");
}

export async function fetchRecentAlarms(): Promise<RecentAlarm[]> {
  const data = await apiFetch<{ items: RecentAlarm[] }>("/api/dashboard/recent-alarms");
  return data.items;
}

export async function fetchDashboardStats(): Promise<DashboardStats> {
  return apiFetch<DashboardStats>("/api/dashboard/stats");
}

export async function fetchAlarmSummary(): Promise<AlarmSummary> {
  return apiFetch<AlarmSummary>("/api/alarms/summary");
}

export async function fetchCustomerOptions(): Promise<{ id: string; name: string }[]> {
  const customers = await fetchCustomers();
  return customers.map((c) => ({ id: c.customer_id, name: c.name }));
}

export async function fetchAccountOptions(): Promise<{ id: string; name: string; customerId: string; regions?: string[] }[]> {
  const accounts = await fetchAccounts();
  return accounts.map((a) => ({ id: a.account_id, name: a.name, customerId: a.customer_id, regions: a.regions }));
}

export async function fetchResource(idOrName: string): Promise<Resource | null> {
  try {
    const resource = await apiFetch<ApiResource>(`/api/resources/${encodeResourceId(idOrName)}`);
    return normalizeResource(resource);
  } catch {
    return null;
  }
}

interface ApiAlarm {
  alarm_name: string;
  metric_name: string;
  namespace: string;
  threshold: number;
  comparison: string;
  state: string;
  severity: string;
  monitoring: boolean;
  mount_path?: string;
  period?: number;
  evaluation_periods?: number;
  datapoints_to_alarm?: number;
  treat_missing_data?: string;
  statistic?: string;
}

function comparisonToDirection(comparison: string): DirectionSimple {
  if (comparison.includes("LessThanOrEqual")) return "<=";
  if (comparison.includes("LessThan")) return "<";
  if (comparison.includes("GreaterThanOrEqual")) return ">=";
  return ">";
}

function parseMountPath(metricName: string): { metricName: string; mountPath?: string } {
  const match = metricName.match(/^(.+?)\((.+)\)$/);
  if (match) return { metricName: match[1] ?? metricName, mountPath: match[2] };
  return { metricName };
}

export async function fetchResourceAlarms(resourceId: string): Promise<AlarmConfig[]> {
  try {
    const items = await apiFetch<ApiAlarm[]>(`/api/resources/${encodeResourceId(resourceId)}/alarms`);
    return items.map((a) => {
      const parsed = parseMountPath(a.metric_name);
      const metricName = parsed.metricName;
      const mountPath = parsed.mountPath ?? a.mount_path;
      return {
        metric_key: mountPath ? `${metricName}:${mountPath}` : metricName,
        metric_name: metricName,
        namespace: a.namespace,
        threshold: a.threshold,
        unit: "",
        direction: comparisonToDirection(a.comparison),
        severity: (a.severity as AlarmConfig["severity"]) ?? "SEV-5",
        source: "System" as const,
        state: (a.state as AlarmConfig["state"]) ?? "OK",
        current_value: null,
        monitoring: a.monitoring,
        mount_path: mountPath ?? a.mount_path,
        period: a.period,
        evaluation_periods: a.evaluation_periods,
        datapoints_to_alarm: a.datapoints_to_alarm,
        treat_missing_data: a.treat_missing_data as AlarmConfig["treat_missing_data"],
        statistic: a.statistic as AlarmConfig["statistic"],
      };
    });
  } catch {
    return [];
  }
}

export async function fetchResourceEvents(resourceId: string): Promise<RecentAlarm[]> {
  try {
    const items = await fetchRecentAlarms();
    return items.filter((item) => item.resource_id === resourceId);
  } catch {
    return [];
  }
}
