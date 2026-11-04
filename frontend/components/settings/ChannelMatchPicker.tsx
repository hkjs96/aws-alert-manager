"use client";

import { useState } from "react";

import { SUPPORTED_RESOURCE_TYPES } from "@/lib/constants";

/** 채널 조건 — 손으로 치면 오타 하나로 조용히 아무 알림도 안 받게 되므로, 고를 수 있는 값만 보여준다. */
export type ChannelMatch = Record<string, string[]>;

/** 새 채널 기본값: 바로 대응할 등급만. SEV-4·5까지 받으면 금방 무시하게 된다. */
export const DEFAULT_SEVERITIES = ["SEV-1", "SEV-2", "SEV-3"];

/** 등급 뜻 — docs/ALARM-RULES.md 심각도 표의 요약. 고르는 사람이 무엇을 놓치는지 알 수 있게 한다. */
export const SEVERITY_INFO: Record<string, { name: string; example: string }> = {
  "SEV-1": { name: "Outage · immediate", example: "Status check failed, 0 healthy targets, VPN tunnel down" },
  "SEV-2": { name: "Major failure · within 15 min", example: "5XX spike, Lambda errors, more unhealthy targets" },
  "SEV-3": { name: "Saturation · within 30 min", example: "CPU/memory/disk over 80%, certificate expiring" },
  "SEV-4": { name: "Degraded · within 4 hours", example: "Slow responses, DB read/write latency" },
  "SEV-5": { name: "Info · next business hours", example: "Request/traffic trends, 4XX" },
};

export type AccountOption = { id: string; name: string; customerId: string };

function toggle(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}

/**
 * "All / Choose" — 아무것도 안 고르면 전부라는 규칙을 숨기지 않는다.
 * Choose를 눌렀는데 아직 하나도 안 골랐으면 저장하면 전부가 되므로 그 사실을 적어 둔다.
 */
function AllOrPick({
  label,
  name,
  selected,
  onChange,
  children,
}: {
  label: string;
  name: string;
  selected: string[];
  onChange: (next: string[]) => void;
  children: React.ReactNode;
}) {
  const [picking, setPicking] = useState(selected.length > 0);
  return (
    <fieldset className="space-y-2">
      <legend className="text-xs font-semibold text-slate-600">{label}</legend>
      <div className="flex gap-4 text-sm text-slate-700">
        <label className="flex items-center gap-1.5">
          <input
            type="radio"
            name={name}
            checked={!picking}
            onChange={() => { setPicking(false); onChange([]); }}
          />
          All
        </label>
        <label className="flex items-center gap-1.5">
          <input type="radio" name={name} checked={picking} onChange={() => setPicking(true)} />
          Choose
        </label>
      </div>
      {picking && (
        <div className="space-y-1.5 pl-5">
          {children}
          {selected.length === 0 && (
            <p className="text-[11px] text-amber-700">Nothing selected — saving now receives everything.</p>
          )}
        </div>
      )}
    </fieldset>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={`rounded-full border px-2.5 py-1 text-xs ${
        on ? "border-primary bg-primary text-white" : "border-slate-300 bg-white text-slate-600 hover:border-slate-400"
      }`}
    >
      {children}
    </button>
  );
}

export function ChannelMatchPicker({
  match,
  severities,
  accounts,
  typeCounts,
  onChange,
}: {
  match: ChannelMatch;
  severities: string[];
  /** 이 채널의 고객사에 등록된 계정만 넘긴다. */
  accounts: AccountOption[];
  /** 이 고객사에 실제로 있는 리소스 타입별 개수. 비었으면(전역 채널·불러오기 전) 모든 타입을 보여 준다. */
  typeCounts: Record<string, number>;
  onChange: (next: ChannelMatch) => void;
}) {
  const [showAllTypes, setShowAllTypes] = useState(false);
  const set = (key: string) => (values: string[]) => onChange({ ...match, [key]: values });
  const selectedSeverities = match.severity ?? [];
  const selectedTypes = match.resource_type ?? [];
  const selectedAccounts = match.account_id ?? [];

  const present = Object.keys(typeCounts);
  const limited = present.length > 0 && !showAllTypes;
  // 이미 골라 둔 타입은 지금 없더라도 보여야 뺄 수 있다
  const typeOptions = limited
    ? [...new Set([...present, ...selectedTypes])].sort((a, b) => (typeCounts[b] ?? 0) - (typeCounts[a] ?? 0))
    : [...SUPPORTED_RESOURCE_TYPES];

  return (
    <div className="space-y-5 rounded-lg bg-slate-50 p-4">
      <p className="text-xs font-semibold text-slate-600">Conditions</p>

      <fieldset>
        <legend className="text-xs font-semibold text-slate-600">
          Severity <span className="font-normal text-slate-400">— none selected receives all</span>
        </legend>
        <div className="mt-2 space-y-1">
          {severities.map((s) => {
            const info = SEVERITY_INFO[s];
            return (
              <label key={s} className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 hover:bg-white">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={selectedSeverities.includes(s)}
                  onChange={() => set("severity")(toggle(selectedSeverities, s))}
                />
                <span className="text-sm">
                  <span className="font-semibold text-slate-800">{s}</span>
                  {info && <span className="ml-2 text-slate-700">{info.name}</span>}
                  {info && <span className="block text-[11px] text-slate-400">{info.example}</span>}
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      <AllOrPick label="Resource type" name="match-type" selected={selectedTypes} onChange={set("resource_type")}>
        <div className="flex flex-wrap gap-1.5">
          {typeOptions.map((t) => (
            <Chip key={t} on={selectedTypes.includes(t)} onClick={() => set("resource_type")(toggle(selectedTypes, t))}>
              {t}
              {typeCounts[t] ? <span className="ml-1 opacity-70">{typeCounts[t]}</span> : null}
            </Chip>
          ))}
        </div>
        {present.length > 0 && (
          <button
            type="button"
            onClick={() => setShowAllTypes((v) => !v)}
            className="text-[11px] font-semibold text-primary"
          >
            {showAllTypes ? "Show only this customer's types" : `Show all types (${SUPPORTED_RESOURCE_TYPES.length})`}
          </button>
        )}
      </AllOrPick>

      {/* 계정이 하나면 고를 게 없다 */}
      {accounts.length > 1 && (
        <AllOrPick label="Account" name="match-account" selected={selectedAccounts} onChange={set("account_id")}>
          <div className="flex flex-wrap gap-1.5">
            {accounts.map((a) => (
              <Chip
                key={a.id}
                on={selectedAccounts.includes(a.id)}
                onClick={() => set("account_id")(toggle(selectedAccounts, a.id))}
              >
                {a.name ? `${a.name} (${a.id})` : a.id}
              </Chip>
            ))}
          </div>
        </AllOrPick>
      )}
    </div>
  );
}

/** 저장 전에 무엇을 받게 되는지 한 줄로. */
export function describeMatch(match: ChannelMatch, customerName: string): string {
  const sev = match.severity?.length ? match.severity.join("·") : "all severities";
  const types = match.resource_type?.length ? match.resource_type.join("·") : "all resources";
  const accts = match.account_id?.length ? ` (${match.account_id.length} accounts)` : "";
  return `Receives ${sev} alerts from ${types} for ${customerName || "all customers"}${accts}.`;
}
