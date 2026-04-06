"use client";

import { useState } from "react";
import type { Customer, Account } from "@/types";
import { CustomerList } from "@/components/settings/CustomerList";
import { AccountRegistry } from "@/components/settings/AccountRegistry";
import { ThresholdOverrideTabs } from "@/components/settings/ThresholdOverrideTabs";

const MOCK_CUSTOMERS: Customer[] = [
  { customer_id: "acme-corp", name: "Acme Corp", provider: "aws", account_count: 12 },
  { customer_id: "beta-inc", name: "Beta Inc", provider: "aws", account_count: 4 },
];

const MOCK_ACCOUNTS: Account[] = [
  { account_id: "123456789012", customer_id: "acme-corp", name: "Production-US-East", role_arn: "arn:aws:iam::123456789012:role/MonitoringRole", regions: ["us-east-1"], connection_status: "connected" },
  { account_id: "987654321098", customer_id: "beta-inc", name: "Staging-Global", role_arn: "arn:aws:iam::987654321098:role/MonitoringRole", regions: ["us-west-2"], connection_status: "untested" },
];

const TABS = ["고객사", "어카운트", "임계치 오버라이드"] as const;

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<(typeof TABS)[number]>("고객사");
  const [customers] = useState(MOCK_CUSTOMERS);
  const [accounts] = useState(MOCK_ACCOUNTS);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-800">Settings</h1>
        <p className="text-sm text-slate-500">고객사, 어카운트, 알람 임계치 오버라이드를 관리합니다.</p>
      </div>

      <div className="flex gap-1 border-b border-slate-200">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab
                ? "border-b-2 border-accent text-accent"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "고객사" && (
        <CustomerList
          customers={customers}
          onAdd={(c) => console.log("Add customer", c)}
          onDelete={(id) => console.log("Delete customer", id)}
        />
      )}

      {activeTab === "어카운트" && (
        <AccountRegistry
          accounts={accounts}
          customers={customers.map((c) => ({ id: c.customer_id, name: c.name }))}
          onAdd={(a) => console.log("Add account", a)}
          onTestConnection={(id) => console.log("Test connection", id)}
          onDelete={(id) => console.log("Delete account", id)}
        />
      )}

      {activeTab === "임계치 오버라이드" && <ThresholdOverrideTabs />}
    </div>
  );
}
