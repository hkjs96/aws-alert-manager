"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw, Plus } from "lucide-react";
import type { DashboardStats, Alarm } from "@/types";
import { Button } from "@/components/shared/Button";
import { StatCardGrid } from "./StatCardGrid";
import { RecentAlarmsTable } from "./RecentAlarmsTable";
import { CreateAlarmModal } from "./create-alarm/CreateAlarmModal";
import { FilterBar } from "@/components/resources/FilterBar";
import { SUPPORTED_RESOURCE_TYPES } from "@/lib/constants";

interface CustomerDto { id: string; name: string }
interface AccountDto { id: string; name: string; customerId: string }



interface DashboardContentProps {
  stats: DashboardStats;
  alarms: Alarm[];
  customers: CustomerDto[];
  accounts: AccountDto[];
}

export function DashboardContent({ stats, alarms, customers, accounts }: DashboardContentProps) {
  const router = useRouter();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [customerFilter, setCustomerFilter] = useState("");
  const [accountFilter, setAccountFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  const filteredAccounts = useMemo(
    () => customerFilter ? accounts.filter((a) => a.customerId === customerFilter) : accounts,
    [accounts, customerFilter],
  );

  const handleCustomerChange = (v: string) => {
    setCustomerFilter(v);
    setAccountFilter("");
  };

  const filteredAlarms = useMemo(() => {
    return alarms.filter((a) => {
      if (accountFilter && !a.arn.includes(accountFilter)) return false;
      if (typeFilter && a.type !== typeFilter) return false;
      if (customerFilter) {
        const accountIds = accounts.filter((acc) => acc.customerId === customerFilter).map((acc) => acc.id);
        if (!accountIds.some((id) => a.arn.includes(id))) return false;
      }
      return true;
    });
  }, [alarms, customerFilter, accountFilter, typeFilter, accounts]);

  const filteredStats: DashboardStats = useMemo(() => {
    if (!customerFilter && !accountFilter && !typeFilter) return stats;
    return {
      monitored_count: stats.monitored_count,
      active_alarms: filteredAlarms.filter((a) => a.state === "ALARM").length,
      unmonitored_count: stats.unmonitored_count,
      account_count: customerFilter ? filteredAccounts.length : stats.account_count,
    };
  }, [stats, filteredAlarms, customerFilter, accountFilter, typeFilter, filteredAccounts]);

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800 font-headline">System Overview</h1>
          <p className="text-sm text-slate-500 mt-1">Real-time health monitoring for AWS infrastructure.</p>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="secondary" onClick={() => router.refresh()} icon={<RefreshCw size={16} />}>
            Refresh
          </Button>
          <Button variant="primary" onClick={() => setIsModalOpen(true)} icon={<Plus size={18} />}>
            Create Alarm
          </Button>
        </div>
      </header>

      <StatCardGrid stats={filteredStats} />

      {/* Filter bar */}
      <FilterBar
        search=""
        onSearchChange={() => {}}
        customerFilter={customerFilter}
        onCustomerChange={handleCustomerChange}
        accountFilter={accountFilter}
        onAccountChange={setAccountFilter}
        typeFilter={typeFilter}
        onTypeChange={setTypeFilter}
        customers={customers}
        accounts={filteredAccounts}
        hideSearch
      />

      <RecentAlarmsTable alarms={filteredAlarms} />

      <CreateAlarmModal open={isModalOpen} onClose={() => setIsModalOpen(false)} onSuccess={() => router.refresh()} />
    </div>
  );
}
