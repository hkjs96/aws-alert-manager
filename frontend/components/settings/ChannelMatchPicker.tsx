"use client";

import { SUPPORTED_RESOURCE_TYPES } from "@/lib/constants";

/** 채널 조건 — 손으로 치면 오타 하나로 조용히 아무 알림도 안 받게 되므로, 고를 수 있는 값만 보여준다. */
export type ChannelMatch = Record<string, string[]>;

/** 새 채널 기본값: 바로 대응할 등급만. SEV-4·5까지 받으면 금방 무시하게 된다. */
export const DEFAULT_SEVERITIES = ["SEV-1", "SEV-2", "SEV-3"];

/** 등급 뜻 — docs/ALARM-RULES.md 심각도 표의 요약. 고르는 사람이 무엇을 놓치는지 알 수 있게 한다. */
export const SEVERITY_INFO: Record<string, { name: string; example: string }> = {
  "SEV-1": { name: "서비스 장애 · 즉시", example: "상태 검사 실패, 정상 대상 0, VPN 터널 끊김" },
  "SEV-2": { name: "주요 기능 장애 · 15분 내", example: "5XX 급증, Lambda 오류, 비정상 대상 증가" },
  "SEV-3": { name: "자원 포화 · 30분 내", example: "CPU·메모리·디스크 80% 초과, 인증서 만료 임박" },
  "SEV-4": { name: "성능 저하 · 4시간 내", example: "응답 지연, DB 읽기/쓰기 지연" },
  "SEV-5": { name: "참고 · 다음 업무 시간", example: "요청 수·트래픽 추세, 4XX" },
};

export type AccountOption = { id: string; name: string; customerId: string };

function toggle(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}

function Chips({
  label,
  hint,
  options,
  selected,
  onChange,
}: {
  label: string;
  hint: string;
  options: { value: string; label: string; title?: string }[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  return (
    <fieldset>
      <legend className="text-xs text-slate-500">
        {label}
        <span className="ml-1 text-slate-400">{selected.length ? `${selected.length}개 선택` : hint}</span>
      </legend>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {options.map((o) => {
          const on = selected.includes(o.value);
          return (
            <button
              key={o.value}
              type="button"
              aria-pressed={on}
              title={o.title}
              onClick={() => onChange(toggle(selected, o.value))}
              className={`rounded-full border px-2.5 py-1 text-xs ${
                on
                  ? "border-primary bg-primary text-white"
                  : "border-slate-300 bg-white text-slate-600 hover:border-slate-400"
              }`}
            >
              {o.label}
            </button>
          );
        })}
        {options.length === 0 && <span className="text-xs text-slate-400">선택할 항목이 없습니다</span>}
      </div>
    </fieldset>
  );
}

export function ChannelMatchPicker({
  match,
  severities,
  accounts,
  onChange,
}: {
  match: ChannelMatch;
  severities: string[];
  /** 이 채널의 고객사에 등록된 계정만 넘긴다. */
  accounts: AccountOption[];
  onChange: (next: ChannelMatch) => void;
}) {
  const set = (key: string) => (values: string[]) => onChange({ ...match, [key]: values });

  return (
    <div className="space-y-4 rounded-lg bg-slate-50 p-4">
      <p className="text-xs font-semibold text-slate-600">
        조건 — 항목마다 아무것도 고르지 않으면 전부 받습니다
      </p>
      <Chips
        label="등급"
        hint="전체"
        options={severities.map((s) => ({
          value: s,
          label: s,
          title: SEVERITY_INFO[s] ? `${SEVERITY_INFO[s].name} — 예: ${SEVERITY_INFO[s].example}` : undefined,
        }))}
        selected={match.severity ?? []}
        onChange={set("severity")}
      />
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11px] leading-relaxed text-slate-500">
        {severities.map((s) => {
          const info = SEVERITY_INFO[s];
          return info ? (
            <div key={s} className="contents">
              <dt className="font-semibold text-slate-600">{s}</dt>
              <dd>
                {info.name}
                <span className="text-slate-400"> — 예: {info.example}</span>
              </dd>
            </div>
          ) : null;
        })}
      </dl>
      <Chips
        label="리소스 타입"
        hint="전체"
        options={SUPPORTED_RESOURCE_TYPES.map((t) => ({ value: t, label: t }))}
        selected={match.resource_type ?? []}
        onChange={set("resource_type")}
      />
      <Chips
        label="계정"
        hint="전체"
        options={accounts.map((a) => ({ value: a.id, label: a.name ? `${a.name} (${a.id})` : a.id }))}
        selected={match.account_id ?? []}
        onChange={set("account_id")}
      />
    </div>
  );
}
