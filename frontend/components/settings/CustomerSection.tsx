"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Users, Plus, Trash2 } from "lucide-react";
import type { Customer } from "@/types";
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
    <div className="bg-white rounded-xl p-8 shadow-soft border border-slate-200">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-headline font-semibold flex items-center gap-2">
          <Users size={20} className="text-primary" /> Customer List
        </h2>
        <span className="bg-slate-100 text-primary px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider">
          {customers.length} ACTIVE
        </span>
      </div>

      {/* Customer table */}
      <div className="bg-slate-50 rounded-lg overflow-hidden">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-slate-400 text-[11px] font-bold uppercase tracking-wider">
              <th className="py-3 px-4">Name</th>
              <th className="py-3 px-4">ID</th>
              <th className="py-3 px-4 text-right">Accounts</th>
              <th className="py-3 px-4 w-10" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {customers.map((c) => (
              <tr key={c.customer_id} className="hover:bg-white transition-colors">
                <td className="py-3 px-4 font-semibold">{c.name}</td>
                <td className="py-3 px-4 font-mono text-[11px]">{c.customer_id}</td>
                <td className="py-3 px-4 text-right">{c.account_count}</td>
                <td className="py-3 px-4">
                  <button
                    onClick={() => setDeleteTarget(c)}
                    className="p-1 hover:bg-red-50 rounded text-slate-400 hover:text-red-500 transition-colors"
                  >
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Register form */}
      <div className="mt-8 pt-8 border-t border-slate-100">
        <h3 className="text-sm font-semibold mb-4 text-slate-500 uppercase tracking-widest">
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
