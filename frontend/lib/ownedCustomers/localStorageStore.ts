import type { UserCustomerStore } from "./store";
import { STORAGE_KEY_PREFIX, GUEST_USER_ID } from "./constants";

export class LocalStorageUserCustomerStore implements UserCustomerStore {
  private readonly key = `${STORAGE_KEY_PREFIX}${GUEST_USER_ID}`;
  private listeners = new Set<(ids: string[]) => void>();

  private isClient(): boolean {
    return typeof window !== "undefined";
  }

  private readFromStorage(): string[] {
    if (!this.isClient()) return [];
    try {
      const raw = localStorage.getItem(this.key);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }

  private writeToStorage(ids: string[]): void {
    if (!this.isClient()) return;
    localStorage.setItem(this.key, JSON.stringify(ids));
  }

  private notify(ids: string[]): void {
    this.listeners.forEach((fn) => fn(ids));
  }

  async getOwnedCustomerIds(): Promise<string[]> {
    return this.readFromStorage();
  }

  async setOwnedCustomerIds(ids: string[]): Promise<void> {
    this.writeToStorage(ids);
    this.notify(ids);
  }

  async toggleOwnedCustomerId(id: string): Promise<string[]> {
    const current = this.readFromStorage();
    const next = current.includes(id)
      ? current.filter((c) => c !== id)
      : [...current, id];
    this.writeToStorage(next);
    this.notify(next);
    return next;
  }

  subscribe(listener: (ids: string[]) => void): () => void {
    this.listeners.add(listener);

    // 다른 탭에서 발생한 localStorage 변경을 수신
    const handleStorageEvent = (e: StorageEvent) => {
      if (e.storageArea !== localStorage || e.key !== this.key) return;
      const ids = e.newValue ? (() => {
        try { return JSON.parse(e.newValue); } catch { return []; }
      })() : [];
      listener(Array.isArray(ids) ? ids : []);
    };

    if (this.isClient()) {
      window.addEventListener("storage", handleStorageEvent);
    }

    return () => {
      this.listeners.delete(listener);
      if (this.isClient()) {
        window.removeEventListener("storage", handleStorageEvent);
      }
    };
  }
}

export function createUserCustomerStore(): UserCustomerStore {
  // Phase2 전환 시: if (process.env.NEXT_PUBLIC_AUTH_ENABLED === "true") return new ApiUserCustomerStore();
  return new LocalStorageUserCustomerStore();
}
