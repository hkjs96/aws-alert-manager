"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw, Plus } from "lucide-react";
import type { DashboardStats, Alarm } from "@/types";
import { StatCardGrid } from "./StatCardGrid";
import { RecentAlarmsTable } from "./RecentAlarmsTable";
import { CreateAlarmModal } from "./create-alarm/CreateAlarmModal";
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

  const selCls = "bg-slate-50 border border-slate-200 rounded-lg text-sm px-3 py-2 focus:ring-2 focus:ring-primary/20 focus:border-primary outline-none transition-colors";

  return (
    <div className="space-y-8">
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-headline font-extrabold tracking-tight text-slate-900">
            System Overview
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            Real-time health monitoring for AWS infrastructure.
          </p>
        </div>
        <div className="flex gap-3">
          <button onClick={() => router.refresh()}
            className="px-4 py-2 bg-white text-slate-700 text-sm font-semibold rounded-lg shadow-sm border border-slate-200 hover:bg-slate-50 flex items-center gap-2">
            <RefreshCw size={16} /> Refresh
          </button>
          <button onClick={() => setIsModalOpen(true)}
            className="px-4 py-2 bg-primary text-white text-sm font-semibold rounded-lg shadow-lg shadow-primary/20 flex items-center gap-2">
            <Plus size={18} /> Create Alarm
          </button>
        </div>
      </div>

      <StatCardGrid stats={filteredStats} />

      {/* Filter bar */}
      <section className="bg-white/80 backdrop-blur rounded-xl p-4 grid grid-cols-1 md:grid-cols-3 gap-4 items-center border border-slate-200 shadow-sm">
        <div className="space-y-1">
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 ml-1">Customer</label>
          <select value={customerFilter} onChange={(e) => handleCustomerChange(e.target.value)} className={`w-full ${selCls}`}>
            <option value="">All Customers</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 ml-1">Account</label>
          <select value={accountFilter} onChange={(e) => setAccountFilter(e.target.value)} className={`w-full ${selCls}`}>
            <option value="">All Accounts</option>
            {filteredAccounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-[10px] font-bold uppercase tracking-wider text-slate-500 ml-1">Resource Type</label>
          <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className={`w-full ${selCls}`}>
            <option value="">All Types</option>
            {SUPPORTED_RESOURCE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
      </section>

      <RecentAlarmsTable alarms={filteredAlarms} />

      <CreateAlarmModal open={isModalOpen} onClose={() => setIsModalOpen(false)} onSuccess={() => router.refresh()} />
    </div>
  );
}
