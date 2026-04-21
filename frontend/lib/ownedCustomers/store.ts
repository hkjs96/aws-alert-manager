export interface UserCustomerStore {
  getOwnedCustomerIds(): Promise<string[]>;
  setOwnedCustomerIds(ids: string[]): Promise<void>;
  toggleOwnedCustomerId(id: string): Promise<string[]>;
  subscribe(listener: (ids: string[]) => void): () => void;
}

// 팩토리는 localStorageStore.ts에서 export — 구현체 교체 시 이 파일만 수정
export { createUserCustomerStore } from "./localStorageStore";
