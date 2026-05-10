import type { Account, Resource } from "@/types";
import type { MetricRow } from "@/components/resources/MetricConfigSection";

export type Track = 1 | 2;

export function filterAccounts(accounts: Account[], customerId: string): Account[] {
  return accounts.filter((a) => a.customer_id === customerId);
}

export function filterResources(resources: Resource[], accountId: string, track: Track): Resource[] {
  return resources.filter(
    (r) => r.account === accountId && (track === 1 ? r.monitoring === true : r.monitoring === false)
  );
}

export function isSubmitEnabled(track: Track, metrics: MetricRow[], customMetrics: MetricRow[]): boolean {
  if (track === 1) {
    return customMetrics.length >= 1;
  }
  return metrics.some((m) => m.enabled) || customMetrics.length >= 1;
}
