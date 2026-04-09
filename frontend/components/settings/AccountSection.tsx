"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Cloud, Link as LinkIcon } from "lucide-react";
import type { Account, Customer } from "@/types";
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
      setError("모든 필드를 입력해주세요.");
      return;
    }
    setError("");
    setIsSubmitting(true);
    try {
      // Simulate POST /api/accounts
      await new Promise((resolve) => setTimeout(resolve, 800));
      showToast("success", `어카운트 "${name}" 연결이 완료되었습니다.`);
      setAccountId("");
      setRoleArn("");
      setName("");
      router.refresh();
    } catch {
      setError("어카운트 연결에 실패했습니다.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleTest = async (id: string) => {
    setTestingId(id);
    try {
      // Simulate POST /api/accounts/{id}/test
      await new Promise((resolve) => setTimeout(resolve, 1200));
      const result = Math.random() > 0.3 ? "connected" : "failed";
      setStatuses((prev) => ({ ...prev, [id]: result }));
      showToast(
        result === "connected" ? "success" : "error",
        result === "connected" ? "연결 테스트 성공" : "연결 테스트 실패",
      );
    } catch {
      showToast("error", "연결 테스트에 실패했습니다.");
    } finally {
      setTestingId(null);
    }
  };

  const getStatus = (acc: Account) => statuses[acc.account_id] ?? acc.connection_status;

  return (
    <div className="bg-white rounded-xl p-8 shadow-soft border border-slate-200">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-headline font-semibold flex items-center gap-2">
          <Cloud size={20} className="text-primary" /> Account Registry
        </h2>
      </div>

      {/* Account table */}
      <div className="bg-slate-50 rounded-lg overflow-hidden mb-8">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-slate-400 text-[11px] font-bold uppercase tracking-wider">
              <th className="py-3 px-6">Account ID</th>
              <th className="py-3 px-6">Name</th>
              <th className="py-3 px-6">Customer</th>
              <th className="py-3 px-6">Status</th>
              <th className="py-3 px-6">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {accounts.map((acc) => {
              const status = getStatus(acc);
              const style = STATUS_STYLES[status] ?? STATUS_STYLES.untested;
              return (
                <tr key={acc.account_id} className="hover:bg-white transition-colors">
                  <td className="py-4 px-6 font-mono text-xs text-primary">
                    {acc.account_id}
                  </td>
                  <td className="py-4 px-6 font-semibold">{acc.name}</td>
                  <td className="py-4 px-6">
                    <span className="bg-slate-200 px-2 py-1 rounded-full text-[10px] font-medium">
                      {customers.find((c) => c.customer_id === acc.customer_id)?.name ?? acc.customer_id}
                    </span>
                  </td>
                  <td className="py-4 px-6">
                    <div className={`flex items-center gap-2 text-[10px] font-bold ${style.text}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
                      {status.toUpperCase()}
                    </div>
                  </td>
                  <td className="py-4 px-6">
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
      </div>

      {/* Connect form */}
      <div className="pt-8 border-t border-slate-100">
        <h3 className="text-sm font-semibold mb-6 text-slate-500 uppercase tracking-widest">
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
        </div>
      </div>
    </div>
  );
}
