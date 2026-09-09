"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Bell, Globe, Pencil, Plus, Trash2, X } from "lucide-react";

import { Button } from "@/components/shared/Button";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { useToast } from "@/components/shared/Toast";
import {
  createChannel,
  deleteChannel,
  fetchChannels,
  fetchChannelTypes,
  fetchCustomers,
  updateChannel,
} from "@/lib/api-functions";
import type {
  ChannelType,
  ChannelTypeCatalogue,
  NotificationChannel,
} from "@/types/api";

const MATCH_LABELS: Record<string, string> = {
  severity: "등급",
  resource_type: "리소스 타입",
  account_id: "계정",
};

/** 백엔드가 자격증명 자리에 넣는 가림 문자열. 그대로 돌려보내면 "안 바꿈"이다. */
const REDACTED = "(설정됨)";

type Draft = {
  channel_id?: string;
  name: string;
  type: string;
  customer_id: string;
  config: Record<string, string>;
  match: Record<string, string>;
  enabled: boolean;
};

function emptyDraft(types: ChannelType[], customerId: string): Draft {
  return {
    name: "",
    type: types[0]?.type ?? "",
    customer_id: customerId,
    config: {},
    match: {},
    enabled: true,
  };
}

function toDraft(channel: NotificationChannel): Draft {
  const match: Record<string, string> = {};
  for (const [key, values] of Object.entries(channel.match ?? {})) {
    match[key] = (values ?? []).join(", ");
  }
  return {
    channel_id: channel.channel_id,
    name: channel.name,
    type: channel.type,
    customer_id: channel.customer_id,
    config: { ...channel.config },
    match,
    enabled: channel.enabled,
  };
}

function matchToApi(match: Record<string, string>): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const [key, raw] of Object.entries(match)) {
    const values = raw.split(",").map((v) => v.trim()).filter(Boolean);
    if (values.length) out[key] = values;
  }
  return out;
}

function ConditionSummary({ channel }: { channel: NotificationChannel }) {
  const parts = Object.entries(channel.match ?? {}).map(
    ([key, values]) => `${MATCH_LABELS[key] ?? key} ${values.join("/")}`,
  );
  if (parts.length === 0) {
    return <span className="text-slate-400">모든 알림</span>;
  }
  return <span>{parts.join(" · ")}</span>;
}

function ChannelForm({
  draft,
  catalogue,
  customers,
  saving,
  onChange,
  onSubmit,
  onCancel,
}: {
  draft: Draft;
  catalogue: ChannelTypeCatalogue;
  customers: { id: string; name: string }[];
  saving: boolean;
  onChange: (next: Draft) => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  const editing = Boolean(draft.channel_id);
  const type = catalogue.types.find((t) => t.type === draft.type);

  return (
    <form
      className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-slate-800">
          {editing ? "채널 수정" : "채널 추가"}
        </h3>
        <button type="button" onClick={onCancel} className="text-slate-400 hover:text-slate-600">
          <X size={16} />
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="text-xs font-semibold text-slate-600">채널 이름</span>
          <input
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            value={draft.name}
            maxLength={60}
            onChange={(e) => onChange({ ...draft, name: e.target.value })}
            placeholder="예: 운영팀 슬랙"
          />
        </label>

        <label className="block">
          <span className="text-xs font-semibold text-slate-600">고객사</span>
          <select
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            value={draft.customer_id}
            disabled={editing}
            onChange={(e) => onChange({ ...draft, customer_id: e.target.value })}
          >
            <option value="">전체 (전역 채널 · 관리자 전용)</option>
            {customers.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="text-xs font-semibold text-slate-600">유형</span>
          <select
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            value={draft.type}
            disabled={editing}
            onChange={(e) => onChange({ ...draft, type: e.target.value, config: {} })}
          >
            {catalogue.types.map((t) => (
              <option key={t.type} value={t.type}>{t.label}</option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-2 pt-6">
          <input
            type="checkbox"
            checked={draft.enabled}
            onChange={(e) => onChange({ ...draft, enabled: e.target.checked })}
          />
          <span className="text-sm text-slate-700">사용</span>
        </label>
      </div>

      {/* 설정 필드는 카탈로그가 알려준 대로 그린다 — 유형이 늘어도 이 코드는 그대로다 */}
      {type && (
        <div className="grid grid-cols-1 gap-4">
          {type.fields.map((field) => (
            <label key={field.name} className="block">
              <span className="text-xs font-semibold text-slate-600">
                {field.label}
                {field.required && <span className="text-red-500"> *</span>}
                {field.secret && (
                  <span className="ml-1 font-normal text-slate-400">
                    (저장 후 다시 보이지 않습니다)
                  </span>
                )}
              </span>
              <input
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm"
                type={field.secret ? "password" : "text"}
                maxLength={field.max_len}
                value={draft.config[field.name] ?? ""}
                placeholder={field.secret && draft.channel_id ? REDACTED : ""}
                onChange={(e) =>
                  onChange({
                    ...draft,
                    config: { ...draft.config, [field.name]: e.target.value },
                  })
                }
              />
            </label>
          ))}
        </div>
      )}

      <div className="space-y-3 rounded-lg bg-slate-50 p-4">
        <p className="text-xs font-semibold text-slate-600">
          조건 — 비워 두면 이 고객사의 모든 알림을 받습니다
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {catalogue.match_fields.map((name) => (
            <label key={name} className="block">
              <span className="text-xs text-slate-500">{MATCH_LABELS[name] ?? name}</span>
              <input
                className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-xs"
                value={draft.match[name] ?? ""}
                onChange={(e) =>
                  onChange({ ...draft, match: { ...draft.match, [name]: e.target.value } })
                }
                placeholder={
                  name === "severity" ? catalogue.severities.slice(0, 2).join(", ") : "쉼표로 구분"
                }
              />
            </label>
          ))}
        </div>
      </div>

      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={onCancel}>
          취소
        </Button>
        <LoadingButton
          type="submit"
          isLoading={saving}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
        >
          {editing ? "저장" : "추가"}
        </LoadingButton>
      </div>
    </form>
  );
}

export function NotificationSection() {
  const { showToast } = useToast();
  const [catalogue, setCatalogue] = useState<ChannelTypeCatalogue | null>(null);
  const [channels, setChannels] = useState<NotificationChannel[]>([]);
  const [customers, setCustomers] = useState<{ id: string; name: string }[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cat, list] = await Promise.all([fetchChannelTypes(), fetchChannels()]);
      setCatalogue(cat);
      setChannels(list.channels);
    } catch (e) {
      showToast("error", e instanceof Error ? e.message : "알림 채널을 불러오지 못했습니다");
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    fetchCustomers()
      .then((list) => setCustomers(list.map((c) => ({ id: c.customer_id, name: c.name }))))
      .catch(() => setCustomers([]));
  }, []);

  const handleSubmit = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const config: Record<string, string> = {};
      for (const [key, value] of Object.entries(draft.config)) {
        // 빈 값은 보내지 않는다 — 수정 시 자격증명을 지우지 않기 위해서다.
        if (value.trim()) config[key] = value;
      }
      const payload = {
        name: draft.name,
        type: draft.type,
        customer_id: draft.customer_id,
        config,
        match: matchToApi(draft.match),
        enabled: draft.enabled,
      };
      if (draft.channel_id) {
        await updateChannel(draft.channel_id, draft.customer_id, payload);
        showToast("success", "채널을 수정했습니다");
      } else {
        await createChannel(payload);
        showToast("success", "채널을 추가했습니다");
      }
      setDraft(null);
      await load();
    } catch (e) {
      showToast("error", e instanceof Error ? e.message : "저장에 실패했습니다");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (channel: NotificationChannel) => {
    if (!window.confirm(`'${channel.name}' 채널을 삭제할까요? 이 채널로는 더 이상 알림이 가지 않습니다.`)) {
      return;
    }
    try {
      await deleteChannel(channel.channel_id, channel.customer_id);
      showToast("success", "채널을 삭제했습니다");
      await load();
    } catch (e) {
      showToast("error", e instanceof Error ? e.message : "삭제에 실패했습니다");
    }
  };

  const customerName = useMemo(() => {
    const map = new Map(customers.map((c) => [c.id, c.name]));
    return (id: string) => map.get(id) ?? id;
  }, [customers]);

  return (
    <section className="space-y-4">
      <header className="flex items-start justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-bold text-slate-800">
            <Bell size={18} /> 알림 채널
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            알람이 확정되면 조건에 맞는 채널로 알림을 보냅니다. 채널을 더해도 알람은 건드리지 않습니다.
          </p>
        </div>
        {catalogue && !draft && (
          <Button
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => setDraft(emptyDraft(catalogue.types, customers[0]?.id ?? ""))}
          >
            채널 추가
          </Button>
        )}
      </header>

      {draft && catalogue && (
        <ChannelForm
          draft={draft}
          catalogue={catalogue}
          customers={customers}
          saving={saving}
          onChange={setDraft}
          onSubmit={handleSubmit}
          onCancel={() => setDraft(null)}
        />
      )}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px]">
            <thead className="bg-slate-50 text-left text-xs font-bold uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-4 py-2">채널</th>
                <th className="px-4 py-2">고객사</th>
                <th className="px-4 py-2">유형</th>
                <th className="px-4 py-2">조건</th>
                <th className="px-4 py-2">상태</th>
                <th className="px-4 py-2 text-right">관리</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-sm text-slate-400">
                    불러오는 중…
                  </td>
                </tr>
              ) : channels.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-sm text-slate-400">
                    등록된 채널이 없습니다. 채널이 없으면 알림이 나가지 않습니다.
                  </td>
                </tr>
              ) : (
                channels.map((channel) => (
                  <tr key={`${channel.customer_id}#${channel.channel_id}`}
                      className="border-t border-slate-100">
                    <td className="px-4 py-2 text-sm font-medium text-slate-800">{channel.name}</td>
                    <td className="px-4 py-2 text-sm text-slate-600">
                      {channel.is_global ? (
                        <span className="inline-flex items-center gap-1 text-amber-700">
                          <Globe size={13} /> 전체
                        </span>
                      ) : (
                        customerName(channel.customer_id)
                      )}
                    </td>
                    <td className="px-4 py-2 text-sm text-slate-600">{channel.type_label}</td>
                    <td className="px-4 py-2 text-xs text-slate-600">
                      <ConditionSummary channel={channel} />
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-semibold ${
                          channel.enabled
                            ? "bg-green-50 text-green-700"
                            : "bg-slate-100 text-slate-500"
                        }`}
                      >
                        {channel.enabled ? "사용" : "중지"}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Pencil size={13} />}
                          onClick={() => setDraft(toDraft(channel))}
                        >
                          수정
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Trash2 size={13} />}
                          onClick={() => void handleDelete(channel)}
                        >
                          삭제
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-xs text-slate-400">
        전역 채널(고객사 “전체”)은 모든 고객사의 알림을 받으므로 관리자만 만들 수 있습니다.
        자격증명은 저장 후 다시 표시되지 않으며, 수정할 때 비워 두면 기존 값이 유지됩니다.
      </p>
    </section>
  );
}
