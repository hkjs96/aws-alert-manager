// 담당 고객사(개인 뷰 선택)를 백엔드 DB에 저장하는 store.
// GET /api/me 로 읽고 PUT /api/me/preferences 로 저장한다. 토큰은 프록시가 주입.
import type { UserCustomerStore } from "./store";

export class ApiUserCustomerStore implements UserCustomerStore {
  private listeners = new Set<(ids: string[]) => void>();
  private cache: string[] = [];
  private loaded = false;

  private notify(ids: string[]): void {
    this.listeners.forEach((fn) => fn(ids));
  }

  async getOwnedCustomerIds(): Promise<string[]> {
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
    }
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
