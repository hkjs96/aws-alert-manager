"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Cloud, Link as LinkIcon } from "lucide-react";
import type { Account, Customer } from "@/types";
import { Button } from "@/components/shared/Button";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";

interface AccountSectionProps {
  accounts: Account[];
  customers: Customer[];
}

const INPUT_CLS = "w-full bg-slate-50 border-none rounded-lg px-4 py-2 text-sm focus:ring-2 focus:ring-primary/20 outline-none";

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-[11px] font-bold text-slate-500 mb-1 uppercase">{label}</label>
      {children}
    </div>
  );
}

const STATUS_STYLES: Record<string, { dot: string; text: string }> = {
  connected: { dot: "bg-emerald-500 animate-pulse", text: "text-emerald-600" },
  failed: { dot: "bg-red-500", text: "text-red-600" },
  untested: { dot: "bg-slate-400", text: "text-slate-500" },
};

export function AccountSection({ accounts, customers }: AccountSectionProps) {
  const router = useRouter();
  const { showToast } = useToast();

  const [accountId, setAccountId] = useState("");
  const [roleArn, setRoleArn] = useState("");
  const [name, setName] = useState("");
  const [customerId, setCustomerId] = useState(customers[0]?.customer_id ?? "");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [testingId, setTestingId] = useState<string | null>(null);
  const [statuses, setStatuses] = useState<Record<string, string>>({});

  const handleConnect = async () => {
    if (!accountId.trim() || !roleArn.trim() || !name.trim()) {
      setError("Please fill in all fields.");
      return;
    }
    setError("");
    setIsSubmitting(true);
    try {
      const res = await fetch("/api/accounts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: accountId.trim(), role_arn: roleArn.trim(), name: name.trim(), customer_id: customerId }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.message ?? "Failed");
      }
      showToast("success", `Account "${name}" has been connected.`);
      setAccountId("");
      setRoleArn("");
      setName("");
      router.refresh();
    } catch {
      setError("Failed to connect account.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleTest = async (id: string) => {
    setTestingId(id);
    try {
      const res = await fetch(`/api/accounts/${id}/test`, { method: "POST" });
      if (!res.ok) throw new Error("Failed");
      const data = await res.json() as { status: string };
      setStatuses((prev) => ({ ...prev, [id]: data.status }));
      showToast(
        data.status === "connected" ? "success" : "error",
        data.status === "connected" ? "Connection test passed" : "Connection test failed",
      );
    } catch {
      showToast("error", "Connection test failed.");
    } finally {
      setTestingId(null);
    }
  };

  const getStatus = (acc: Account) => statuses[acc.account_id] ?? acc.connection_status;

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-soft overflow-hidden">
      {/* Section header */}
      <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-800 flex items-center gap-2">
            <Cloud size={18} className="text-primary" /> Account Registry
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">Connected AWS accounts and their status</p>
        </div>
      </div>

      {/* Account table or empty state */}
      <div className="overflow-x-auto">
        {accounts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <span className="text-3xl mb-3">🔗</span>
            <p className="text-sm font-semibold text-slate-600">연결된 계정이 없습니다</p>
            <p className="text-xs text-slate-400 mt-1">AWS 계정을 추가해보세요</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Account ID</th>
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Name</th>
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Customer</th>
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Status</th>
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {accounts.map((acc) => {
                const status = getStatus(acc);
                const style = STATUS_STYLES[status] ?? STATUS_STYLES.untested;
                return (
                  <tr key={acc.account_id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3 font-mono text-xs text-primary">
                      {acc.account_id}
                    </td>
                    <td className="px-4 py-3 font-semibold text-slate-900">{acc.name}</td>
                    <td className="px-4 py-3">
                      <span className="bg-slate-200 px-2 py-1 rounded-full text-[10px] font-medium">
                        {customers.find((c) => c.customer_id === acc.customer_id)?.name ?? acc.customer_id}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className={`flex items-center gap-2 text-[10px] font-bold ${style.text}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
                        {status.toUpperCase()}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <LoadingButton
                        isLoading={testingId === acc.account_id}
                        onClick={() => handleTest(acc.account_id)}
                        className="text-xs font-semibold text-primary hover:underline"
                      >
                        Test Connection
                      </LoadingButton>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Connect form */}
      <div className="px-6 py-6 border-t border-slate-100 bg-slate-50">
        <h3 className="text-sm font-semibold mb-6 text-slate-700 uppercase tracking-widest">
          Onboard AWS Account
        </h3>
        <div className="grid grid-cols-2 gap-6">
          <div className="space-y-4">
            <FormField label="AWS Account ID">
              <input value={accountId} onChange={(e) => setAccountId(e.target.value)}
                className={INPUT_CLS + " font-mono"} placeholder="0000 0000 0000" />
            </FormField>
            <FormField label="IAM Role ARN">
              <input value={roleArn} onChange={(e) => setRoleArn(e.target.value)}
                className={INPUT_CLS + " font-mono text-xs"} placeholder="arn:aws:iam::..." />
            </FormField>
          </div>
          <div className="space-y-4">
            <FormField label="Friendly Name">
              <input value={name} onChange={(e) => setName(e.target.value)}
                className={INPUT_CLS} placeholder="e.g. Mobile-App-Prod" />
            </FormField>
            <FormField label="Assigned Customer">
              <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} className={INPUT_CLS}>
                {customers.map((c) => (
                  <option key={c.customer_id} value={c.customer_id}>{c.name}</option>
                ))}
              </select>
            </FormField>
          </div>
        </div>
        {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
        <div className="mt-6 flex justify-end">
          <LoadingButton
            isLoading={isSubmitting}
            onClick={handleConnect}
            className="bg-slate-900 text-white px-8 py-2.5 rounded-lg font-semibold text-sm hover:bg-slate-800 transition-all flex items-center gap-2"
          >
            <LinkIcon size={16} /> Connect Account
          </LoadingButton>
          {/* Note: Connect button kept as LoadingButton to preserve dark bg styling */}
        </div>
      </div>
    </div>
  );
}
