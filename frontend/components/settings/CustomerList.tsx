"use client";

import { useState } from "react";
import type { Customer } from "@/types";

interface CustomerListProps {
  customers: Customer[];
  onAdd: (customer: { name: string; code: string }) => void;
  onDelete: (id: string) => void;
}

export function CustomerList({ customers, onAdd, onDelete }: CustomerListProps) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");

  const handleAdd = () => {
    if (!name || !code) return;
    onAdd({ name, code });
    setName("");
    setCode("");
  };

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-700">고객사 목록</h3>
        <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-accent">
          {customers.length} ACTIVE
        </span>
      </div>

      <table className="mb-4 w-full text-sm">
        <thead className="text-left text-xs font-medium uppercase text-slate-500">
          <tr>
            <th className="pb-2">이름</th>
            <th className="pb-2">코드</th>
            <th className="pb-2">어카운트</th>
            <th className="pb-2 w-16"></th>
          </tr>
        </thead>
        <tbody>
          {customers.map((c) => (
            <tr key={c.customer_id} className="border-t border-slate-100">
              <td className="py-2 font-medium">{c.name}</td>
              <td className="py-2 font-mono text-xs text-slate-500">{c.customer_id}</td>
              <td className="py-2">{c.account_count}</td>
              <td className="py-2">
                <button
                  onClick={() => {
                    if (c.account_count > 0) {
                      if (!confirm(`${c.name}에 ${c.account_count}개 어카운트가 연결되어 있습니다. 삭제하시겠습니까?`)) return;
                    }
                    onDelete(c.customer_id);
                  }}
                  className="text-xs text-red-500 hover:text-red-700"
                >
                  삭제
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="border-t border-slate-100 pt-4">
        <h4 className="mb-2 text-xs font-medium uppercase text-slate-500">고객사 추가</h4>
        <div className="flex gap-2">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="이름" className="flex-1 rounded-md border border-slate-200 px-3 py-1.5 text-sm" />
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="코드 (ACME-01)" className="w-32 rounded-md border border-slate-200 px-3 py-1.5 text-sm font-mono" />
          <button onClick={handleAdd} className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700">등록</button>
        </div>
      </div>
    </div>
  );
}
