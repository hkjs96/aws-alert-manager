"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

interface GlobalFilterState {
  customerId: string;
  accountId: string;
  serviceId: string;
}

interface GlobalFilterContextValue extends GlobalFilterState {
  setCustomerId: (id: string) => void;
  setAccountId: (id: string) => void;
  setServiceId: (id: string) => void;
  toQueryParams: () => Record<string, string>;
}

const GlobalFilterContext = createContext<GlobalFilterContextValue | null>(null);

export function GlobalFilterProvider({ children }: { children: ReactNode }) {
  const [customerId, setCustomerId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [serviceId, setServiceId] = useState("");

  const toQueryParams = () => {
    const params: Record<string, string> = {};
    if (customerId) params.customer_id = customerId;
    if (accountId) params.account_id = accountId;
    if (serviceId) params.service_id = serviceId;
    return params;
  };

  return (
    <GlobalFilterContext.Provider
      value={{ customerId, accountId, serviceId, setCustomerId, setAccountId, setServiceId, toQueryParams }}
    >
      {children}
    </GlobalFilterContext.Provider>
  );
}

export function useGlobalFilter() {
  const ctx = useContext(GlobalFilterContext);
  if (!ctx) throw new Error("useGlobalFilter must be used within GlobalFilterProvider");
  return ctx;
}
