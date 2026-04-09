// mock-store.ts — In-memory mutable store for mock data
// Wraps seed data from mock-data.ts so Route Handlers can add/remove/update during dev sessions

import type { Alarm, Resource, Customer, Account, RecentAlarm } from "@/types";
import type { AlarmSummary } from "@/types/api";
import {
  MOCK_ALARMS,
  MOCK_RESOURCES,
  MOCK_CUSTOMERS,
  MOCK_ACCOUNTS,
  MOCK_RECENT_ALARMS,
} from "./mock-data";

// ---------------------------------------------------------------------------
// Mutable copies (shallow clone of seed arrays)
// ---------------------------------------------------------------------------
const alarms: Alarm[] = [...MOCK_ALARMS];
const resources: Resource[] = [...MOCK_RESOURCES];
const customers: Customer[] = [...MOCK_CUSTOMERS];
const accounts: Account[] = [...MOCK_ACCOUNTS];
const recentAlarms: RecentAlarm[] = [...MOCK_RECENT_ALARMS];

// ---------------------------------------------------------------------------
// Getters
// ---------------------------------------------------------------------------
export function getAlarms(): Alarm[] {
  return alarms;
}
export function getResources(): Resource[] {
  return resources;
}
export function getCustomers(): Customer[] {
  return customers;
}
export function getAccounts(): Account[] {
  return accounts;
}
export function getRecentAlarms(): RecentAlarm[] {
  return recentAlarms;
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------
export function addAlarm(alarm: Alarm): void {
  alarms.unshift(alarm);
}

export function addRecentAlarm(recent: RecentAlarm): void {
  recentAlarms.unshift(recent);
}

export function addCustomer(customer: Customer): void {
  customers.push(customer);
}

export function removeCustomer(id: string): void {
  const idx = customers.findIndex((c) => c.customer_id === id);
  if (idx >= 0) customers.splice(idx, 1);
}

export function addAccount(account: Account): void {
  accounts.push(account);
}

export function updateResourceMonitoring(id: string, monitoring: boolean): void {
  const r = resources.find((res) => res.id === id);
  if (r) r.monitoring = monitoring;
}

// ---------------------------------------------------------------------------
// Computed stats
// ---------------------------------------------------------------------------
export function computeDashboardStats() {
  const monitored = resources.filter((r) => r.monitoring);
  const unmonitored = resources.filter((r) => !r.monitoring);
  const activeAlarms = alarms.filter((a) => a.state === "ALARM").length;

  return {
    monitored_count: monitored.length,
    active_alarms: activeAlarms,
    unmonitored_count: unmonitored.length,
    account_count: accounts.length,
  };
}

export function computeAlarmSummary(): AlarmSummary {
  const total = alarms.length;
  const alarmCount = alarms.filter((a) => a.state === "ALARM").length;
  const okCount = alarms.filter((a) => a.state === "OK").length;
  const insufficientCount = alarms.filter((a) => a.state === "INSUFFICIENT").length;

  return {
    total,
    alarm_count: alarmCount,
    ok_count: okCount,
    insufficient_count: insufficientCount,
  };
}
