import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useOwnedCustomers, _resetStoreForTesting } from "../useOwnedCustomers";
import type { UserCustomerStore } from "@/lib/ownedCustomers/store";

vi.mock("@/lib/ownedCustomers/store", () => ({
  createUserCustomerStore: vi.fn(),
}));

import { createUserCustomerStore } from "@/lib/ownedCustomers/store";

function makeMockStore(initialIds: string[] = []): UserCustomerStore {
  let ids = [...initialIds];
  const listeners = new Set<(ids: string[]) => void>();

  return {
    getOwnedCustomerIds: vi.fn(async () => [...ids]),
    setOwnedCustomerIds: vi.fn(async (newIds: string[]) => {
      ids = newIds;
      listeners.forEach((fn) => fn([...ids]));
    }),
    toggleOwnedCustomerId: vi.fn(async (id: string) => {
      ids = ids.includes(id) ? ids.filter((c) => c !== id) : [...ids, id];
      listeners.forEach((fn) => fn([...ids]));
      return [...ids];
    }),
    subscribe: vi.fn((listener: (ids: string[]) => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    }),
  };
}

describe("useOwnedCustomers", () => {
  let mockStore: UserCustomerStore;

  beforeEach(() => {
    _resetStoreForTesting();
    mockStore = makeMockStore(["cust-a"]);
    vi.mocked(createUserCustomerStore).mockReturnValue(mockStore);
  });

  it("마운트 시 store.getOwnedCustomerIds 값을 반환한다", async () => {
    const { result } = renderHook(() => useOwnedCustomers());
    await act(async () => {});
    expect(result.current.ownedCustomerIds).toEqual(["cust-a"]);
  });

  it("toggleOwned 호출 후 상태가 갱신된다", async () => {
    const { result } = renderHook(() => useOwnedCustomers());
    await act(async () => {});
    await act(async () => {
      await result.current.toggleOwned("cust-b");
    });
    expect(result.current.ownedCustomerIds).toContain("cust-b");
  });

  it("isOwned는 포함된 customer_id에 true를 반환한다", async () => {
    const { result } = renderHook(() => useOwnedCustomers());
    await act(async () => {});
    expect(result.current.isOwned("cust-a")).toBe(true);
    expect(result.current.isOwned("cust-z")).toBe(false);
  });

  it("언마운트 시 store.subscribe 해제가 호출된다", async () => {
    const unsubscribe = vi.fn();
    vi.mocked(mockStore.subscribe).mockReturnValue(unsubscribe);
    const { unmount } = renderHook(() => useOwnedCustomers());
    await act(async () => {});
    unmount();
    expect(unsubscribe).toHaveBeenCalled();
  });
});
