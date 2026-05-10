/**
 * Server-side data access layer.
 *
 * API_BASE_URL 환경변수 설정 시 → 실제 API Gateway 호출
 * 미설정 시 (로컬 개발) → mock-store 폴백
 *
 * 교체 방법: .env.local 또는 배포 환경에서 아래 변수를 설정
 *   API_BASE_URL=https://xxx.execute-api.ap-northeast-2.amazonaws.com/prod
 *
 * NOTE: API_BASE_URL은 서버 전용 변수 (NEXT_PUBLIC_ 없음).
 *       클라이언트 컴포넌트에서는 NEXT_PUBLIC_API_BASE_URL 사용.
 */

import type { AlarmConfig, DirectionSimple } from "@/types";
import {
  getAlarms as _getAlarms,
  getResources as _getResources,
  getCustomers as _getCustomers,
  getAccounts as _getAccounts,
  getRecentAlarms as _getRecentAlarms,
  computeDashboardStats as _computeDashboardStats,
  computeAlarmSummary as _computeAlarmSummary,
} from "@/lib/mock-store";
import { MOCK_CUSTOMERS, MOCK_ACCOUNTS } from "@/lib/mock-data";
import type { Alarm, Resource, Customer, Account, RecentAlarm } from "@/types";
import type { AlarmSummary, DashboardStats } from "@/types/api";

// ── 실제 API 클라이언트 (서버 전용) ───────────────────────────────

const API_BASE_URL =
  process.env.API_GATEWAY_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  process.env.API_BASE_URL ??
  "";

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    throw new Error(`API ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

const useRealApi = () => Boolean(API_BASE_URL);

// ── 데이터 페처 ──────────────────────────────────────────────────

export async function fetchAlarms(): Promise<Alarm[]> {
  if (useRealApi()) {
    const data = await apiFetch<{ items: Alarm[] }>("/api/alarms?page_size=100");
    return data.items;
  }
  return _getAlarms();
}

export async function fetchResources(): Promise<Resource[]> {
  if (useRealApi()) {
    const data = await apiFetch<{ items: Resource[] }>("/api/resources?page_size=100");
    return data.items;
  }
  return _getResources();
}

export async function fetchCustomers(): Promise<Customer[]> {
  if (useRealApi()) {
    return apiFetch<Customer[]>("/api/customers");
  }
  return _getCustomers();
}

export async function fetchAccounts(): Promise<Account[]> {
  if (useRealApi()) {
    return apiFetch<Account[]>("/api/accounts");
  }
  return _getAccounts();
}

export async function fetchRecentAlarms(): Promise<RecentAlarm[]> {
  if (useRealApi()) {
    const data = await apiFetch<{ items: RecentAlarm[] }>("/api/dashboard/recent-alarms");
    return data.items;
  }
  return _getRecentAlarms();
}

export async function fetchDashboardStats(): Promise<DashboardStats> {
  if (useRealApi()) {
    return apiFetch<DashboardStats>("/api/dashboard/stats");
  }
  return _computeDashboardStats();
}

export async function fetchAlarmSummary(): Promise<AlarmSummary> {
  if (useRealApi()) {
    return apiFetch<AlarmSummary>("/api/alarms/summary");
  }
  return _computeAlarmSummary();
}

/** 필터용 경량 customer 목록 */
export async function fetchCustomerOptions(): Promise<{ id: string; name: string }[]> {
  const customers = await fetchCustomers();
  return customers.map((c) => ({ id: c.customer_id, name: c.name }));
}

/** 필터용 경량 account 목록 */
export async function fetchAccountOptions(): Promise<{ id: string; name: string; customerId: string }[]> {
  const accounts = await fetchAccounts();
  return accounts.map((a) => ({ id: a.account_id, name: a.name, customerId: a.customer_id }));
}

/** 단일 리소스 조회 (없으면 null) */
export async function fetchResource(idOrName: string): Promise<Resource | null> {
  if (useRealApi()) {
    try {
      return await apiFetch<Resource>(`/api/resources/${encodeURIComponent(idOrName)}`);
    } catch {
      return null;
    }
  }
  const all = _getResources();
  return all.find((r) => r.id === idOrName || r.name === idOrName) ?? null;
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

/** 리소스 알람 설정 조회 */
export async function fetchResourceAlarms(resourceId: string): Promise<AlarmConfig[]> {
  if (useRealApi()) {
    try {
      const items = await apiFetch<ApiAlarm[]>(`/api/resources/${encodeURIComponent(resourceId)}/alarms`);
      return items.map((a) => ({
        metric_key: a.metric_name,
        metric_name: a.metric_name,
        namespace: a.namespace,
        threshold: a.threshold,
        unit: "",
        direction: comparisonToDirection(a.comparison),
        severity: (a.severity as AlarmConfig["severity"]) ?? "SEV-5",
        source: "System" as const,
        state: (a.state as AlarmConfig["state"]) ?? "OK",
        current_value: null,
        monitoring: a.monitoring,
        mount_path: a.mount_path,
        period: a.period,
        evaluation_periods: a.evaluation_periods,
        datapoints_to_alarm: a.datapoints_to_alarm,
        treat_missing_data: a.treat_missing_data as AlarmConfig["treat_missing_data"],
        statistic: a.statistic as AlarmConfig["statistic"],
      }));
    } catch {
      return [];
    }
  }
  const { getMockAlarmConfigs } = await import("@/lib/mock-data");
  return getMockAlarmConfigs(resourceId);
}
