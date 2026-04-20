/**
 * Server-side data access layer.
 *
 * 현재: mock-store를 래핑하는 형태로 동작.
 * 실제 AWS SDK 연동 시: 이 파일에서만 교체하면 page.tsx / route.ts 변경 불필요.
 *
 * TODO (AWS SDK 연동 시 교체 목록):
 *   - getResources()     → EC2/RDS/ELB describe + DynamoDB 조회
 *   - getAlarms()        → CloudWatch describe_alarms
 *   - getCustomers()     → DynamoDB Customer 테이블
 *   - getAccounts()      → DynamoDB Account 테이블
 *   - getDashboardStats() → 위 데이터 집계
 */

import {
  getAlarms as _getAlarms,
  getResources as _getResources,
  getCustomers as _getCustomers,
  getAccounts as _getAccounts,
  getRecentAlarms as _getRecentAlarms,
  computeDashboardStats as _computeDashboardStats,
  computeAlarmSummary as _computeAlarmSummary,
} from "@/lib/mock-store";
import { MOCK_ALARM_SUMMARY, MOCK_CUSTOMERS, MOCK_ACCOUNTS } from "@/lib/mock-data";
import type { Alarm, Resource, Customer, Account, RecentAlarm } from "@/types";
import type { AlarmSummary, DashboardStats } from "@/types/api";

export async function fetchAlarms(): Promise<Alarm[]> {
  return _getAlarms();
}

export async function fetchResources(): Promise<Resource[]> {
  return _getResources();
}

export async function fetchCustomers(): Promise<Customer[]> {
  return _getCustomers();
}

export async function fetchAccounts(): Promise<Account[]> {
  return _getAccounts();
}

export async function fetchRecentAlarms(): Promise<RecentAlarm[]> {
  return _getRecentAlarms();
}

export async function fetchDashboardStats(): Promise<DashboardStats> {
  return _computeDashboardStats();
}

export async function fetchAlarmSummary(): Promise<AlarmSummary> {
  return _computeAlarmSummary();
}

/** 필터용 경량 customer 목록 */
export async function fetchCustomerOptions(): Promise<{ id: string; name: string }[]> {
  return MOCK_CUSTOMERS.map((c) => ({ id: c.customer_id, name: c.name }));
}

/** 필터용 경량 account 목록 */
export async function fetchAccountOptions(): Promise<{ id: string; name: string; customerId: string }[]> {
  return MOCK_ACCOUNTS.map((a) => ({ id: a.account_id, name: a.name, customerId: a.customer_id }));
}

/** 단일 리소스 조회 (없으면 null) */
export async function fetchResource(idOrName: string): Promise<Resource | null> {
  const all = _getResources();
  return all.find((r) => r.id === idOrName || r.name === idOrName) ?? null;
}
