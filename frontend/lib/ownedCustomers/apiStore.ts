// ⚠️ Phase2 전용 — auth 도입 시점에 구현. 지금은 stub.
import type { UserCustomerStore } from "./store";

export class ApiUserCustomerStore implements UserCustomerStore {
  async getOwnedCustomerIds(): Promise<string[]> {
    throw new Error("Phase2 only: auth 시스템 도입 후 구현");
  }
  async setOwnedCustomerIds(_ids: string[]): Promise<void> {
    throw new Error("Phase2 only: 관리자가 DB에서 할당");
  }
  async toggleOwnedCustomerId(_id: string): Promise<string[]> {
    throw new Error("Phase2 only: 관리자가 DB에서 할당");
  }
  subscribe(_listener: (ids: string[]) => void): () => void {
    throw new Error("Phase2 only: auth 시스템 도입 후 구현");
  }
}
