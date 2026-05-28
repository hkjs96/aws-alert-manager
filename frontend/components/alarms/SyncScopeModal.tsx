"use client";

import { useState, useEffect } from "react";
import { X, Check } from "lucide-react";
import { Button } from "@/components/shared/Button";

interface Customer {
  id: string;
  name: string;
}

interface Account {
  id: string;
  name: string;
  customerId: string;
  regions?: string[];
}

interface SyncScopeModalProps {
  isOpen: boolean;
  onClose: () => void;
  customers: Customer[];
  accounts: Account[];
  onStartSync: (scope: { customer_id?: string; account_id?: string; regions?: string[] }) => void;
}

const AVAILABLE_REGIONS = [
  { value: "ap-northeast-2", label: "ap-northeast-2 (Seoul)" },
  { value: "ap-northeast-1", label: "ap-northeast-1 (Tokyo)" },
  { value: "us-east-1", label: "us-east-1 (N. Virginia)" },
  { value: "us-west-2", label: "us-west-2 (Oregon)" },
  { value: "eu-west-1", label: "eu-west-1 (Ireland)" },
];

export function SyncScopeModal({
  isOpen,
  onClose,
  customers,
  accounts,
  onStartSync,
}: SyncScopeModalProps) {
  const [selectedCustomerId, setSelectedCustomerId] = useState("");
  const [selectedAccountId, setSelectedAccountId] = useState("");
  const [selectedRegions, setSelectedRegions] = useState<string[]>(["ap-northeast-2"]);

  // Reset when selected customer changes
  useEffect(() => {
    setSelectedAccountId("");
  }, [selectedCustomerId]);

  // If selected account changes, set regions default or available ones
  useEffect(() => {
    if (selectedAccountId) {
      const acc = accounts.find((a) => a.id === selectedAccountId);
      if (acc && acc.regions && acc.regions.length > 0) {
        setSelectedRegions(acc.regions);
      } else {
        setSelectedRegions(["ap-northeast-2"]);
      }
    } else {
      setSelectedRegions(["ap-northeast-2"]);
    }
  }, [selectedAccountId, accounts]);

  if (!isOpen) return null;

  const filteredAccounts = selectedCustomerId
    ? accounts.filter((a) => a.customerId === selectedCustomerId)
    : accounts;

  const handleRegionToggle = (region: string) => {
    setSelectedRegions((prev) =>
      prev.includes(region) ? prev.filter((r) => r !== region) : [...prev, region]
    );
  };

  const handleStart = () => {
    onStartSync({
      customer_id: selectedCustomerId || undefined,
      account_id: selectedAccountId || undefined,
      regions: selectedRegions.length > 0 ? selectedRegions : ["ap-northeast-2"],
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-slate-900/60 backdrop-blur-sm transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Dialog container */}
      <div className="relative z-10 w-full max-w-lg overflow-hidden rounded-2xl bg-white shadow-2xl transition-all border border-slate-100 flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-6 py-5 border-b border-slate-100 flex items-center justify-between bg-slate-50">
          <div>
            <h3 className="text-lg font-bold text-slate-800 font-headline">Sync CloudWatch Alarms</h3>
            <p className="text-xs text-slate-500 mt-0.5">Select scope to fetch current alarm states from AWS.</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form Content */}
        <div className="px-6 py-6 space-y-5 overflow-y-auto flex-1">
          {/* Customer Selection */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-600">Customer (Optional)</label>
            <select
              value={selectedCustomerId}
              onChange={(e) => setSelectedCustomerId(e.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              <option value="">All Customers</option>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          {/* Account Selection */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-600">Account (Optional)</label>
            <select
              value={selectedAccountId}
              onChange={(e) => setSelectedAccountId(e.target.value)}
              className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              <option value="">All Accounts</option>
              {filteredAccounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.id})
                </option>
              ))}
            </select>
          </div>

          {/* Region Selection */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-600 block">Target Regions</label>
            <div className="grid grid-cols-2 gap-2 max-h-40 overflow-y-auto p-1">
              {AVAILABLE_REGIONS.map((r) => {
                const isChecked = selectedRegions.includes(r.value);
                return (
                  <button
                    key={r.value}
                    type="button"
                    onClick={() => handleRegionToggle(r.value)}
                    className={`flex items-center gap-2 px-3 py-2 rounded-xl border text-left text-xs font-semibold transition-all ${
                      isChecked
                        ? "border-indigo-500 bg-indigo-50/50 text-indigo-700"
                        : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                    }`}
                  >
                    <div
                      className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors ${
                        isChecked ? "border-indigo-500 bg-indigo-500 text-white" : "border-slate-300 bg-white"
                      }`}
                    >
                      {isChecked && <Check size={10} strokeWidth={3} />}
                    </div>
                    {r.label}
                  </button>
                );
              })}
            </div>
            <p className="text-[10px] text-slate-400">
              * AWS CloudWatch will be scanned for the selected regions only. Default is ap-northeast-2.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 bg-slate-50 border-t border-slate-100 flex items-center justify-end gap-2">
          <Button variant="secondary" onClick={onClose} className="rounded-xl">
            Cancel
          </Button>
          <Button variant="primary" onClick={handleStart} className="rounded-xl bg-indigo-600 hover:bg-indigo-700">
            Start Sync
          </Button>
        </div>
      </div>
    </div>
  );
}
