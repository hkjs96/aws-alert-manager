"use client";

import { useSyncExternalStore, useCallback, useState, useEffect } from "react";
import { createUserCustomerStore } from "@/lib/ownedCustomers/store";
import type { UserCustomerStore } from "@/lib/ownedCustomers/store";

// 모듈 수준 lazy 싱글턴 — 첫 렌더 시 초기화되어 전체 앱에서 공유
let _store: UserCustomerStore | undefined;
let _cachedIds: string[] = [];

function getStore(): UserCustomerStore {
  if (!_store) _store = createUserCustomerStore();
  return _store;
}

// 테스트 환경에서 store 상태를 초기화하는 헬퍼
export function _resetStoreForTesting(): void {
  _store = undefined;
  _cachedIds = [];
}

function subscribeToStore(onStoreChange: () => void): () => void {
  return getStore().subscribe((ids) => {
    _cachedIds = ids;
    onStoreChange();
  });
}

function getSnapshot(): string[] {
  return _cachedIds;
}

export interface OwnedCustomersState {
  ownedCustomerIds: string[];
  isLoading: boolean;
  toggleOwned: (customerId: string) => Promise<void>;
  isOwned: (customerId: string) => boolean;
}

export function useOwnedCustomers(): OwnedCustomersState {
  const ownedCustomerIds = useSyncExternalStore(
    subscribeToStore,
    getSnapshot,
    () => [], // SSR fallback
  );

  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    getStore()
      .getOwnedCustomerIds()
      .then((ids) => {
        _cachedIds = ids;
        setIsLoading(false);
      });
  }, []);

  const toggleOwned = useCallback(async (customerId: string) => {
    await getStore().toggleOwnedCustomerId(customerId);
  }, []);

  const isOwned = useCallback(
    (customerId: string) => ownedCustomerIds.includes(customerId),
    [ownedCustomerIds],
  );

  return { ownedCustomerIds, isLoading, toggleOwned, isOwned };
}
