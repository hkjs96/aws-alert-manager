import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { LocalStorageUserCustomerStore } from "../localStorageStore";

describe("LocalStorageUserCustomerStore", () => {
  let store: LocalStorageUserCustomerStore;

  beforeEach(() => {
    localStorage.clear();
    store = new LocalStorageUserCustomerStore();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("getOwnedCustomerIds", () => {
    it("빈 localStorage에서 빈 배열을 반환한다", async () => {
      expect(await store.getOwnedCustomerIds()).toEqual([]);
    });

    it("잘못된 JSON이 저장된 경우 빈 배열을 반환한다", async () => {
      localStorage.setItem("userCustomers:guest", "NOT_JSON{{");
      expect(await store.getOwnedCustomerIds()).toEqual([]);
    });

    it("저장된 customer_id 배열을 반환한다", async () => {
      localStorage.setItem(
        "userCustomers:guest",
        JSON.stringify(["cust-a", "cust-b"]),
      );
      expect(await store.getOwnedCustomerIds()).toEqual(["cust-a", "cust-b"]);
    });
  });

  describe("setOwnedCustomerIds", () => {
    it("setOwnedCustomerIds 후 getOwnedCustomerIds가 동일한 배열을 반환한다", async () => {
      await store.setOwnedCustomerIds(["cust-a", "cust-b"]);
      expect(await store.getOwnedCustomerIds()).toEqual(["cust-a", "cust-b"]);
    });

    it("빈 배열로 설정하면 빈 배열을 반환한다", async () => {
      await store.setOwnedCustomerIds(["cust-a"]);
      await store.setOwnedCustomerIds([]);
      expect(await store.getOwnedCustomerIds()).toEqual([]);
    });
  });

  describe("toggleOwnedCustomerId", () => {
    it("없는 id를 토글하면 추가한다", async () => {
      const result = await store.toggleOwnedCustomerId("cust-a");
      expect(result).toEqual(["cust-a"]);
    });

    it("있는 id를 토글하면 제거한다", async () => {
      await store.setOwnedCustomerIds(["cust-a", "cust-b"]);
      const result = await store.toggleOwnedCustomerId("cust-a");
      expect(result).toEqual(["cust-b"]);
    });

    it("토글 후 getOwnedCustomerIds에 반영된다", async () => {
      await store.toggleOwnedCustomerId("cust-x");
      expect(await store.getOwnedCustomerIds()).toEqual(["cust-x"]);
    });
  });

  describe("subscribe", () => {
    it("setOwnedCustomerIds 호출 시 subscribe 리스너가 갱신된 값으로 호출된다", async () => {
      const listener = vi.fn();
      store.subscribe(listener);
      await store.setOwnedCustomerIds(["cust-a"]);
      expect(listener).toHaveBeenCalledWith(["cust-a"]);
    });

    it("subscribe 해제 함수 호출 후에는 리스너가 호출되지 않는다", async () => {
      const listener = vi.fn();
      const unsubscribe = store.subscribe(listener);
      unsubscribe();
      await store.setOwnedCustomerIds(["cust-a"]);
      expect(listener).not.toHaveBeenCalled();
    });

    it("다른 탭의 storage 이벤트 발생 시 subscribe 리스너가 호출된다", async () => {
      const listener = vi.fn();
      store.subscribe(listener);

      // 다른 탭에서 localStorage를 변경하는 상황을 storage 이벤트로 시뮬레이션
      const newIds = ["cust-z"];
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: "userCustomers:guest",
          newValue: JSON.stringify(newIds),
          storageArea: localStorage,
        }),
      );

      expect(listener).toHaveBeenCalledWith(newIds);
    });

    it("storage 이벤트에서 newValue가 null이면 빈 배열로 호출된다", async () => {
      const listener = vi.fn();
      store.subscribe(listener);

      window.dispatchEvent(
        new StorageEvent("storage", {
          key: "userCustomers:guest",
          newValue: null,
          storageArea: localStorage,
        }),
      );

      expect(listener).toHaveBeenCalledWith([]);
    });
  });

  describe("SSR 환경 가드", () => {
    it("window가 없는 환경에서 getOwnedCustomerIds는 빈 배열을 반환하고 에러를 던지지 않는다", async () => {
      const originalWindow = global.window;
      // @ts-expect-error - SSR 시뮬레이션
      delete global.window;
      const ssrStore = new LocalStorageUserCustomerStore();
      await expect(ssrStore.getOwnedCustomerIds()).resolves.toEqual([]);
      global.window = originalWindow;
    });
  });
});
