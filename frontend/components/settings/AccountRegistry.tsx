"use client";

import { useState } from "react";
import type { Account } from "@/types";

interface AccountRegistryProps {
  accounts: Account[];
  customers: { id: string; name: string }[];
  onAdd: (account: { account_id: string; name: string; role_arn: string; customer_id: string }) => void;
  onTestConnection: (id: string) => void;
  onDelete: (id: string) => void;
}

export function AccountRegistry({ accounts, customers, onAdd, onTestConnection, onDelete }: AccountRegistryProps) {
  const [accountId, setAccountId] = useState("");
  const [name, setName] = useState("");
  const [roleArn, setRoleArn] = useState("");
  const [customerId, setCustomerId] = useState("");

  const handleAdd = () => {
    if (!accountId || !name || !roleArn || !customerId) return;
    onAdd({ account_id: accountId, name, role_arn: roleArn, customer_id: customerId });
    setAccountId(""); setName(""); setRoleArn(""); setCustomerId("");
  };

  const statusDot = (s: string) => {
    if (s === "connected") return <span className="h-2 w-2 rounded-full bg-green-500 inline-block" title="Connected" />;
    if (s === "failed") return <span className="h-2 w-2 rounded-full bg-red-500 inline-block" title="Failed" />;
    return <span className="h-2 w-2 rounded-full bg-slate-300 inline-block" title="Untested" />;
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <h3 className="mb-4 text-sm font-medium text-slate-700">어카운트 등록</h3>

      <table className="mb-4 w-full text-sm">
        <thead className="text-left text-xs font-medium uppercase text-slate-500">
          <tr>
            <th className="pb-2">Account ID</th>
            <th className="pb-2">이름</th>
            <th className="pb-2">고객사</th>
            <th className="pb-2">상태</th>
            <th className="pb-2 w-32"></th>
          </tr>
        </thead>
        <tbody>
          {accounts.map((a) => (
            <tr key={a.account_id} className="border-t border-slate-100">
              <td className="py-2 font-mono text-xs text-blue-600">{a.account_id}</td>
              <td className="py-2">{a.name}</td>
              <td className="py-2 text-slate-500">{a.customer_id}</td>
              <td className="py-2">{statusDot(a.connection_status)}</td>
              <td className="py-2 flex gap-2">
                <button onClick={() => onTestConnection(a.account_id)} className="text-xs text-accent hover:underline">테스트</button>
                <button onClick={() => onDelete(a.account_id)} className="text-xs text-red-500 hover:text-red-700">삭제</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="border-t border-slate-100 pt-4">
        <h4 className="mb-2 text-xs font-medium uppercase text-slate-500">어카운트 추가</h4>
        <div className="grid grid-cols-2 gap-2">
          <input value={accountId} onChange={(e) => setAccountId(e.target.value)} placeholder="AWS Account ID" className="rounded-md border border-slate-200 px-3 py-1.5 text-sm font-mono" />
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="이름" className="rounded-md border border-slate-200 px-3 py-1.5 text-sm" />
          <input value={roleArn} onChange={(e) => setRoleArn(e.target.value)} placeholder="arn:aws:iam::123456789012:role/..." className="rounded-md border border-slate-200 px-3 py-1.5 text-sm font-mono" />
          <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} className="rounded-md border border-slate-200 px-3 py-1.5 text-sm">
            <option value="">고객사 선택</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <button onClick={handleAdd} className="mt-2 rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700">연결</button>
      </div>
    </div>
  );
}
