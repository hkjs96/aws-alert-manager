"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Users, Plus, Trash2 } from "lucide-react";
import type { Customer } from "@/types";
import { Button } from "@/components/shared/Button";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";

interface CustomerSectionProps {
  customers: Customer[];
}

export function CustomerSection({ customers }: CustomerSectionProps) {
  const router = useRouter();
  const { showToast } = useToast();
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Customer | null>(null);

  const handleRegister = async () => {
    if (!name.trim() || !code.trim()) {
      setError("Please enter both Display Name and Entity Code.");
      return;
    }
    setError("");
    setIsSubmitting(true);
    try {
      const res = await fetch("/api/customers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), code: code.trim() }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.message ?? "Failed");
      }
      showToast("success", `Customer "${name}" has been registered.`);
      setName("");
      setCode("");
      router.refresh();
    } catch {
      setError("Failed to register customer.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      const res = await fetch(`/api/customers/${deleteTarget.customer_id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed");
      showToast("success", `Customer "${deleteTarget.name}" has been deleted.`);
      router.refresh();
    } catch {
      showToast("error", "Failed to delete customer.");
    } finally {
      setDeleteTarget(null);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-soft overflow-hidden">
      {/* Section header */}
      <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-800 flex items-center gap-2">
            <Users size={18} className="text-primary" /> Customer List
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">Manage your registered customers</p>
        </div>
        {customers.length > 0 && (
          <span className="bg-slate-100 text-primary px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider">
            {customers.length} ACTIVE
          </span>
        )}
      </div>

      {/* Customer table or empty state */}
      <div className="overflow-x-auto">
        {customers.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <span className="text-3xl mb-3">👥</span>
            <p className="text-sm font-semibold text-slate-600">등록된 고객사가 없습니다</p>
            <p className="text-xs text-slate-400 mt-1">새 고객사를 추가해보세요</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Name</th>
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">ID</th>
                <th className="px-4 py-3 text-right text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Accounts</th>
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {customers.map((c) => (
                <tr key={c.customer_id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3 font-semibold text-slate-900">{c.name}</td>
                  <td className="px-4 py-3 font-mono text-[11px] text-slate-600">{c.customer_id}</td>
                  <td className="px-4 py-3 text-right text-slate-600">{c.account_count}</td>
                  <td className="px-4 py-3">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setDeleteTarget(c)}
                      icon={<Trash2 size={14} />}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Register form */}
      <div className="px-6 py-6 border-t border-slate-100 bg-slate-50">
        <h3 className="text-sm font-semibold mb-4 text-slate-700 uppercase tracking-widest">
          Add New Customer
        </h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-[11px] font-bold text-slate-500 mb-1 ml-1 uppercase">
              Display Name
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full bg-slate-50 border-none rounded-lg px-4 py-2 text-sm focus:ring-2 focus:ring-primary/20 outline-none"
              placeholder="e.g. Acme Corp"
            />
          </div>
          <div>
            <label className="block text-[11px] font-bold text-slate-500 mb-1 ml-1 uppercase">
              Entity Code
            </label>
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="w-full bg-slate-50 border-none rounded-lg px-4 py-2 font-mono text-sm focus:ring-2 focus:ring-primary/20 outline-none"
              placeholder="ACME-01"
            />
          </div>
        </div>
        {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
        <LoadingButton
          isLoading={isSubmitting}
          onClick={handleRegister}
          className="mt-4 w-full bg-primary text-white py-2.5 rounded-lg font-semibold text-sm shadow-lg shadow-primary/20 hover:brightness-110 transition-all flex items-center justify-center gap-2"
        >
          <Plus size={16} /> Register Customer
        </LoadingButton>
        {/* Note: Register button kept as LoadingButton to maintain custom full-width styling */}
      </div>

      {/* Delete confirmation */}
      <ConfirmDialog
        isOpen={!!deleteTarget}
        title="Delete Customer"
        message={`"${deleteTarget?.name}" customer? This action cannot be undone.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
