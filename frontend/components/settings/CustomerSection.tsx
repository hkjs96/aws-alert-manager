"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Users, Plus, Trash2, Pencil } from "lucide-react";
import type { Customer } from "@/types";
import { Button } from "@/components/shared/Button";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { useMe } from "@/hooks/useMe";
import {
  createCustomer as apiCreateCustomer,
  deleteCustomer as apiDeleteCustomer,
  updateCustomer as apiUpdateCustomer,
} from "@/lib/api-functions";

interface CustomerSectionProps {
  customers: Customer[];
}

/** 쉼표·공백·줄바꿈으로 나뉜 이메일 → 소문자·중복 제거 목록. */
export function parseManagers(text: string): string[] {
  return Array.from(new Set(text.split(/[\s,;]+/).map((e) => e.trim().toLowerCase()).filter(Boolean)));
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function CustomerSection({ customers }: CustomerSectionProps) {
  const router = useRouter();
  const { showToast } = useToast();
  const { email, isAdmin } = useMe();
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Customer | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [managersDraft, setManagersDraft] = useState("");
  const [savingManagers, setSavingManagers] = useState(false);

  // 담당자 편집은 관리자 또는 그 고객사의 담당자만 — 백엔드가 같은 규칙으로 다시 검사한다.
  const canEdit = (c: Customer) => isAdmin || (!!email && (c.managers ?? []).includes(email));

  const startEdit = (c: Customer) => {
    setEditingId(c.customer_id);
    setManagersDraft((c.managers ?? []).join(", "));
  };

  const saveManagers = async (c: Customer) => {
    const managers = parseManagers(managersDraft);
    const invalid = managers.filter((m) => !EMAIL_RE.test(m));
    if (managers.length === 0 || invalid.length > 0) {
      showToast("error", managers.length === 0 ? "담당자는 한 명 이상이어야 합니다." : `이메일 형식이 아닙니다: ${invalid.join(", ")}`);
      return;
    }
    if (!isAdmin && email && !managers.includes(email)) {
      // 자기 자신을 빼면 저장 직후 이 고객사가 안 보이게 된다 — 의도인지 확인한다.
      if (!window.confirm("담당자에서 본인을 빼면 이 고객사를 더 이상 볼 수 없습니다. 계속할까요?")) return;
    }
    setSavingManagers(true);
    try {
      await apiUpdateCustomer(c.customer_id, { managers });
      showToast("success", `"${c.name}" 담당자를 저장했습니다.`);
      setEditingId(null);
      router.refresh();
    } catch (e) {
      showToast("error", e instanceof Error ? e.message : "담당자 저장에 실패했습니다.");
    } finally {
      setSavingManagers(false);
    }
  };

  const handleRegister = async () => {
    if (!name.trim() || !code.trim()) {
      setError("Please enter both Display Name and Entity Code.");
      return;
    }
    setError("");
    setIsSubmitting(true);
    try {
      await apiCreateCustomer({ name: name.trim(), code: code.trim() });
      showToast("success", `Customer "${name}" has been registered.`);
      setName("");
      setCode("");
      router.refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to register customer.";
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await apiDeleteCustomer(deleteTarget.customer_id);
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

      {!isAdmin && (
        <div className="mx-6 mt-4 rounded-lg bg-slate-50 border border-slate-200 px-4 py-3 text-xs text-slate-600">
          담당자로 지정된 고객사만 보입니다. 다른 고객사가 필요하면 그 고객사의 담당자나 관리자에게 요청하세요.
        </div>
      )}

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
                <th className="px-4 py-3 text-left text-[11px] font-semibold text-slate-500 uppercase tracking-wider whitespace-nowrap">담당자</th>
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
                    {editingId === c.customer_id ? (
                      <div className="flex items-center gap-2">
                        <input
                          aria-label={`${c.name} 담당자`}
                          value={managersDraft}
                          onChange={(e) => setManagersDraft(e.target.value)}
                          placeholder="a@mz.co.kr, b@mz.co.kr"
                          className="min-w-[16rem] bg-white ring-1 ring-slate-200 rounded px-2 py-1 text-xs font-mono"
                        />
                        <LoadingButton
                          isLoading={savingManagers}
                          onClick={() => saveManagers(c)}
                          className="text-xs font-semibold text-primary hover:underline"
                        >
                          저장
                        </LoadingButton>
                        <button type="button" onClick={() => setEditingId(null)} className="text-xs text-slate-400 hover:underline">
                          취소
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-slate-600">
                          {(c.managers ?? []).length > 0 ? (c.managers ?? []).join(", ") : <span className="text-amber-600">없음 — 관리자만 볼 수 있음</span>}
                        </span>
                        {canEdit(c) && (
                          <button
                            type="button"
                            aria-label={`${c.name} 담당자 편집`}
                            onClick={() => startEdit(c)}
                            className="text-slate-400 hover:text-primary"
                          >
                            <Pencil size={12} />
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {isAdmin && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDeleteTarget(c)}
                        icon={<Trash2 size={14} />}
                      />
                    )}
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
