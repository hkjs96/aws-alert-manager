import { toggleMonitoring } from "@/lib/api-functions";

export interface BulkToggleFailure {
  id: string;
  message: string;
}

export interface BulkToggleResult {
  succeeded: string[];
  failed: BulkToggleFailure[];
}

export interface BulkToggleOptions {
  /** 동시 요청 수. 백엔드 PUT은 리소스당 알람을 순차 생성(PutMetricAlarm 3 TPS)하므로 기본 3. */
  concurrency?: number;
  /** 테스트 주입용 — 기본은 lib/api-functions.toggleMonitoring */
  toggle?: (id: string, enabled: boolean) => Promise<unknown>;
}

/**
 * 선택 리소스의 모니터링을 리소스별 PUT /resources/{id}/monitoring 으로 일괄 전환한다.
 *
 * 왜 /bulk/monitoring 이 아닌가: 그 SQS 경로는 알람만 생성/삭제하고 Monitoring 태그와
 * 인벤토리 monitoring 플래그를 건드리지 않아, 다음 daily run이 태그 기준으로 되돌린다.
 * 리소스별 PUT은 태그 + 인벤토리 + 즉시 알람 동기화(실패 시 daily self-heal)를 모두 수행한다.
 *
 * 실패는 개별로 수집하고 나머지는 계속 진행한다 — 한 리소스의 오류가 전체를 막지 않는다.
 */
export async function runBulkToggle(
  ids: string[],
  enabled: boolean,
  options: BulkToggleOptions = {},
): Promise<BulkToggleResult> {
  const toggle = options.toggle ?? toggleMonitoring;
  const concurrency = Math.max(1, options.concurrency ?? 3);
  const queue = [...ids];
  const succeeded: string[] = [];
  const failed: BulkToggleFailure[] = [];

  const worker = async () => {
    for (let id = queue.shift(); id !== undefined; id = queue.shift()) {
      try {
        await toggle(id, enabled);
        succeeded.push(id);
      } catch (error) {
        failed.push({ id, message: error instanceof Error ? error.message : String(error) });
      }
    }
  };

  await Promise.all(Array.from({ length: Math.min(concurrency, ids.length) }, worker));
  return { succeeded, failed };
}

/** 토스트 문구 — 전부 성공 / 일부 실패 / 전부 실패를 구분한다. */
export function describeBulkToggle(result: BulkToggleResult, enabled: boolean): {
  kind: "success" | "error";
  message: string;
} {
  const verb = enabled ? "활성화" : "비활성화";
  const total = result.succeeded.length + result.failed.length;
  if (result.failed.length === 0) {
    return { kind: "success", message: `${total}개 리소스의 모니터링을 ${verb}했습니다.` };
  }
  if (result.succeeded.length === 0) {
    return { kind: "error", message: `모니터링 ${verb}에 실패했습니다 (${total}개).` };
  }
  return {
    kind: "error",
    message: `${result.succeeded.length}개 ${verb}, ${result.failed.length}개 실패: ${result.failed
      .map((f) => f.id)
      .slice(0, 3)
      .join(", ")}${result.failed.length > 3 ? " 외" : ""}`,
  };
}
