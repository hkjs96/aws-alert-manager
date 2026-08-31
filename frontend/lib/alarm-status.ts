import type { Alarm } from "@/types";

/** TopBar 알림 벨에 넘기는 최소 DTO — 전체 Alarm 레코드를 클라이언트에 내려보내지 않는다. */
export interface AlarmBrief {
  resource: string;
  metric: string;
  type: string;
}

export const ALARM_BELL_LIMIT = 20;

export interface AlarmStatusSummary {
  /** ALARM 상태 알람 수 (배지·벨 카운트) */
  count: number;
  /** 벨 드롭다운 목록 (최대 ALARM_BELL_LIMIT) */
  alarming: AlarmBrief[];
}

export function summarizeAlarms(alarms: Alarm[]): AlarmStatusSummary {
  const firing = alarms.filter((a) => a.state === "ALARM");
  return {
    count: firing.length,
    alarming: firing.slice(0, ALARM_BELL_LIMIT).map((a) => ({
      resource: a.resource,
      metric: a.metric,
      type: a.type,
    })),
  };
}
