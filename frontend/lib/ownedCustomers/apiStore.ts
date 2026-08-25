// 담당 고객사(개인 뷰 선택)를 백엔드 DB에 저장하는 store.
// GET /api/me 로 읽고 PUT /api/me/preferences 로 저장한다. 토큰은 프록시가 주입.
import type { UserCustomerStore } from "./store";

export class ApiUserCustomerStore implements UserCustomerStore {
  private listeners = new Set<(ids: string[]) => void>();
  private cache: string[] = [];
  private loaded = false;
  private inflight: Promise<string[]> | null = null;

  private notify(ids: string[]): void {
    this.listeners.forEach((fn) => fn(ids));
  }

  // 이 값은 로그인 세션 동안 바뀌지 않는다(변경은 setOwnedCustomerIds가 직접 반영).
  // 매 호출마다 요청하면 이 store를 쓰는 컴포넌트 수만큼 /api/me가 반복 호출된다.
  async getOwnedCustomerIds(): Promise<string[]> {
    if (this.loaded) return this.cache;
    // 여러 컴포넌트가 동시에 마운트되면 같은 요청이 겹친다 — 진행 중 요청을 공유한다.
    if (this.inflight) return this.inflight;

    this.inflight = (async () => {
      try {
        const res = await fetch("/api/me", { cache: "no-store" });
        if (!res.ok) return this.cache;
        const data: unknown = await res.json();
        const raw = (data as { owned_customer_ids?: unknown }).owned_customer_ids;
        const ids = Array.isArray(raw) ? raw.map((x) => String(x)) : [];
        this.cache = ids;
        this.loaded = true;
        return ids;
      } catch {
        return this.cache;
      } finally {
        this.inflight = null;
      }
    })();

    return this.inflight;
  }

  async setOwnedCustomerIds(ids: string[]): Promise<void> {
    // 낙관적 갱신: 먼저 로컬 반영/통지 후 서버 저장
    this.cache = ids;
    this.loaded = true;
    this.notify(ids);
    try {
      await fetch("/api/me/preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ owned_customer_ids: ids }),
      });
    } catch {
      // 저장 실패는 조용히 무시(다음 로드 시 서버값으로 정정)
    }
  }

  async toggleOwnedCustomerId(id: string): Promise<string[]> {
    const current = this.loaded ? this.cache : await this.getOwnedCustomerIds();
    const next = current.includes(id)
      ? current.filter((c) => c !== id)
      : [...current, id];
    await this.setOwnedCustomerIds(next);
    return next;
  }

  subscribe(listener: (ids: string[]) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
}
