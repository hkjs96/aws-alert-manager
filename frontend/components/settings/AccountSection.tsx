"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Cloud, Link as LinkIcon, XCircle } from "lucide-react";
import type { Account, Customer } from "@/types";
import { Button } from "@/components/shared/Button";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { createAccount, testConnection } from "@/lib/api-functions";

interface AccountSectionProps {
  accounts: Account[];
  customers: Customer[];
}

const INPUT_CLS = "w-full bg-slate-50 border-none rounded-lg px-4 py-2 text-sm focus:ring-2 focus:ring-primary/20 outline-none";
const REGION_OPTIONS = [
  { value: "us-east-1", label: "버지니아" },
  { value: "us-east-2", label: "오하이오" },
  { value: "us-west-1", label: "캘리포니아" },
  { value: "us-west-2", label: "오리건" },
  { value: "ca-central-1", label: "캐나다 중부" },
  { value: "ca-west-1", label: "캘거리" },
  { value: "mx-central-1", label: "멕시코" },
  { value: "sa-east-1", label: "상파울루" },
  { value: "eu-west-1", label: "아일랜드" },
  { value: "eu-west-2", label: "런던" },
  { value: "eu-west-3", label: "파리" },
  { value: "eu-central-1", label: "프랑크푸르트" },
  { value: "eu-central-2", label: "취리히" },
  { value: "eu-north-1", label: "스톡홀름" },
  { value: "eu-south-1", label: "밀라노" },
  { value: "eu-south-2", label: "스페인" },
  { value: "af-south-1", label: "케이프타운" },
  { value: "il-central-1", label: "텔아비브" },
  { value: "me-central-1", label: "UAE" },
  { value: "me-south-1", label: "바레인" },
  { value: "ap-south-1", label: "뭄바이" },
  { value: "ap-south-2", label: "하이데라바드" },
  { value: "ap-east-1", label: "홍콩" },
  { value: "ap-east-2", label: "타이베이" },
  { value: "ap-northeast-1", label: "도쿄" },
  { value: "ap-northeast-2", label: "서울" },
  { value: "ap-northeast-3", label: "오사카" },
  { value: "ap-southeast-1", label: "싱가포르" },
  { value: "ap-southeast-2", label: "시드니" },
  { value: "ap-southeast-3", label: "자카르타" },
  { value: "ap-southeast-4", label: "멜버른" },
  { value: "ap-southeast-5", label: "말레이시아" },
  { value: "ap-southeast-6", label: "뉴질랜드" },
  { value: "ap-southeast-7", label: "태국" },
] as const;
const COMMON_REGIONS = ["us-east-1", "ap-northeast-2", "ap-northeast-1", "ap-southeast-1", "us-west-2"];
const REGION_GROUPS = [
  {
    title: "Americas",
    regions: ["us-east-1", "us-east-2", "us-west-1", "us-west-2", "ca-central-1", "ca-west-1", "mx-central-1", "sa-east-1"],
  },
  {
    title: "Europe",
    regions: ["eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1", "eu-central-2", "eu-north-1", "eu-south-1", "eu-south-2"],
  },
  {
    title: "Asia Pacific",
    regions: [
      "ap-south-1",
      "ap-south-2",
      "ap-east-1",
      "ap-east-2",
      "ap-northeast-1",
      "ap-northeast-2",
      "ap-northeast-3",
      "ap-southeast-1",
      "ap-southeast-2",
      "ap-southeast-3",
      "ap-southeast-4",
      "ap-southeast-5",
      "ap-southeast-6",
      "ap-southeast-7",
    ],
  },
  {
    title: "Africa & Middle East",
    regions: ["af-south-1", "il-central-1", "me-central-1", "me-south-1"],
  },
] as const;

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
  const [customerId, setCustomerId] = useState("");
  const [regions, setRegions] = useState<string[]>(["us-east-1"]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [testingId, setTestingId] = useState<string | null>(null);
  const [statuses, setStatuses] = useState<Record<string, string>>({});
  const [testDetails, setTestDetails] = useState<Record<string, string[]>>({});

  const handleConnect = async () => {
    if (!accountId.trim() || !roleArn.trim() || !name.trim() || !customerId || regions.length === 0) {
      setError("Please fill in all fields, select a customer, and choose at least one region.");
      return;
    }
    setError("");
    setIsSubmitting(true);
    try {
      await createAccount({
        account_id: accountId.trim(),
        role_arn: roleArn.trim(),
        name: name.trim(),
        customer_id: customerId,
        regions,
      });
      showToast("success", `Account "${name}" has been connected.`);
      setAccountId("");
      setRoleArn("");
      setName("");
      setRegions(["us-east-1"]);
      router.refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to connect account.";
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleTest = async (account: Account) => {
    setTestingId(account.account_id);
    try {
      const data = await testConnection(account.account_id, account.customer_id);
      setStatuses((prev) => ({ ...prev, [account.account_id]: data.status }));
      setTestDetails((prev) => ({
        ...prev,
        [account.account_id]: (data.regions ?? []).map((region) => `${region.region}: ${region.status}`),
      }));
      showToast(
        data.status === "connected" ? "success" : "error",
        data.status === "connected" ? "Connection test passed" : "Connection test failed.",
      );
    } catch (e) {
      setStatuses((prev) => ({ ...prev, [account.account_id]: "failed" }));
      const msg = e instanceof Error ? e.message : "Connection test failed.";
      setTestDetails((prev) => ({ ...prev, [account.account_id]: [msg] }));
      showToast("error", "Connection test failed.");
    } finally {
      setTestingId(null);
    }
  };

  const getStatus = (acc: Account) => statuses[acc.account_id] ?? acc.connection_status;
  const toggleRegion = (region: string) => {
    setRegions((current) => (
      current.includes(region)
        ? current.filter((item) => item !== region)
        : [...current, region]
    ));
  };
  const selectedRegionOptions = REGION_OPTIONS.filter((region) => regions.includes(region.value));
  const regionLabel = (value: string) => REGION_OPTIONS.find((region) => region.value === value)?.label ?? value;

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
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Regions</th>
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Status</th>
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {accounts.map((acc) => {
                const status = getStatus(acc);
                const style = STATUS_STYLES[status] ?? STATUS_STYLES.untested;
                const details = testDetails[acc.account_id];
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
                      <div className="flex flex-wrap gap-1">
                        {acc.regions.map((region) => (
                          <span key={region} className="rounded-md bg-slate-100 px-2 py-1 font-mono text-[10px] text-slate-600">
                            {region}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="space-y-1">
                        <div className={`flex items-center gap-2 text-[10px] font-bold ${style.text}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
                          {status.toUpperCase()}
                        </div>
                        {details && (
                          <div className="space-y-0.5">
                            {details.map((detail) => (
                              <div key={detail} className="text-[10px] text-slate-400">{detail}</div>
                            ))}
                          </div>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <LoadingButton
                        isLoading={testingId === acc.account_id}
                        onClick={() => handleTest(acc)}
                        className="inline-flex items-center gap-1.5 text-xs font-semibold text-primary hover:underline"
                      >
                        {status === "connected" ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
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
                <option value="" disabled>— Select Customer —</option>
                {customers.map((c) => (
                  <option key={c.customer_id} value={c.customer_id}>{c.name}</option>
                ))}
              </select>
            </FormField>
          </div>
        </div>
        <div className="mt-6">
          <FormField label="Monitoring Regions">
            <div className="rounded-lg bg-white p-4 ring-1 ring-slate-200">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="mb-2 text-[11px] font-semibold text-slate-400">
                    {regions.length} selected
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {selectedRegionOptions.map((region) => (
                      <span key={region.value} className="rounded-md bg-primary/10 px-2.5 py-1 font-mono text-[11px] font-semibold text-primary">
                        {region.value}
                      </span>
                    ))}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setRegions(["us-east-1"])}
                  className="text-xs font-semibold text-primary hover:underline"
                >
                  Reset to Virginia
                </button>
              </div>

              <div className="mt-4">
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  Common Regions
                </div>
                <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                  {COMMON_REGIONS.map((region) => {
                    const selected = regions.includes(region);
                    return (
                      <button
                        key={region}
                        type="button"
                        onClick={() => toggleRegion(region)}
                        className={
                          `flex min-w-0 items-center gap-2 rounded-md px-3 py-1.5 text-left text-xs font-semibold ring-1 transition-colors ${
                            selected
                              ? "bg-primary text-white ring-primary"
                              : "bg-slate-50 text-slate-600 ring-slate-200 hover:bg-slate-100"
                          }`
                        }
                      >
                        <span className="shrink-0 font-mono">{region}</span>
                        <span className="shrink-0 font-normal opacity-80">{regionLabel(region)}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <details className="mt-4 rounded-lg border border-slate-200 bg-slate-50">
                <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-primary">
                  Show all AWS regions
                </summary>
                <div className="grid gap-4 border-t border-slate-200 p-3 lg:grid-cols-2">
                  {REGION_GROUPS.map((group) => (
                    <div key={group.title} className="rounded-lg border border-slate-200 bg-white p-3">
                      <div className="mb-3 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                        {group.title}
                      </div>
                      <div className="space-y-2">
                        {group.regions.map((region) => (
                          <label key={region} className="flex min-w-0 items-center gap-3 rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-700 ring-1 ring-slate-100">
                            <input
                              type="checkbox"
                              checked={regions.includes(region)}
                              onChange={() => toggleRegion(region)}
                              className="h-4 w-4 shrink-0 rounded border-slate-300 text-primary focus:ring-primary/20"
                            />
                            <span className="flex min-w-0 flex-1 items-center gap-3 overflow-hidden">
                              <span className="w-32 shrink-0 font-mono font-semibold text-slate-700">{region}</span>
                              <span className="shrink-0 text-[11px] text-slate-400">{regionLabel(region)}</span>
                            </span>
                          </label>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </details>
            </div>
          </FormField>
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
