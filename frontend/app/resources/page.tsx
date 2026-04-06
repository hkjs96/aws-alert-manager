"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { Resource } from "@/types";
import { FilterBar } from "@/components/shared/FilterBar";
import { Pagination } from "@/components/shared/Pagination";
import { ResourceTable } from "@/components/resources/ResourceTable";
import { BulkActionBar } from "@/components/resources/BulkActionBar";
import { StatCard } from "@/components/dashboard/StatCard";
import { Monitor, AlertTriangle, RefreshCw, BarChart3 } from "lucide-react";

// TODO: Replace with API calls
const MOCK_RESOURCES: Resource[] = [
  {
    id: "i-0a2b4c6d8e0f12",
    name: "payments-api-prod-01",
    type: "EC2",
    account_id: "882311440092",
    customer_id: "acme-corp",
    region: "us-east-1",
    provider: "aws",
    monitoring: true,
    active_alarms: [{ count: 2, severity: "SEV-1" }],
    tags: { Environment: "prod", Team: "payments" },
  },
  {
    id: "arn:aws:s3:::user-data-store",
    name: "user-static-assets",
    type: "S3",
    account_id: "882311440092",
    customer_id: "acme-corp",
    region: "eu-central-1",
    provider: "aws",
    monitoring: true,
    active_alarms: [],
    tags: {},
  },
  {
    id: "db-XYZ9908821-RDS",
    name: "auth-db-postgres",
    type: "RDS",
    account_id: "440911228833",
    customer_id: "beta-inc",
    region: "us-west-2",
    provider: "aws",
    monitoring: true,
    active_alarms: [{ count: 1, severity: "SEV-3" }],
    tags: { Environment: "prod" },
  },
  {
    id: "arn:aws:lambda:us-east-1:882311440092:function:worker",
    name: "image-processor-worker",
    type: "Lambda",
    account_id: "882311440092",
    customer_id: "acme-corp",
    region: "us-east-1",
    provider: "aws",
    monitoring: false,
    active_alarms: [],
    tags: {},
  },
  {
    id: "alb-prod-external-332",
    name: "main-ingress-lb",
    type: "ALB",
    account_id: "882311440092",
    customer_id: "acme-corp",
    region: "us-east-1",
    provider: "aws",
    monitoring: true,
    active_alarms: [],
    tags: { Environment: "prod" },
  },
];

export default function ResourcesPage() {
  const router = useRouter();
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  // Filter state
  const [customer, setCustomer] = useState("");
  const [account, setAccount] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [monitoringFilter, setMonitoringFilter] = useState<"all" | "on" | "off">("all");
  const [search, setSearch] = useState("");

  const resources = MOCK_RESOURCES;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-800">Resources</h1>
          <p className="text-sm text-slate-500">등록된 어카운트의 AWS 리소스를 관리합니다.</p>
        </div>
        <div className="flex gap-2">
          <button className="flex items-center gap-1.5 rounded-md border border-slate-200 px-3 py-1.5 text-sm hover:bg-slate-50">
            <RefreshCw size={14} /> 리소스 동기화
          </button>
        </div>
      </div>

      <FilterBar
        customers={[{ id: "acme-corp", name: "Acme Corp" }, { id: "beta-inc", name: "Beta Inc" }]}
        accounts={[{ id: "882311440092", name: "Production" }, { id: "440911228833", name: "Staging" }]}
        selectedCustomer={customer}
        selectedAccount={account}
        selectedResourceType={resourceType}
        monitoringFilter={monitoringFilter}
        searchQuery={search}
        onCustomerChange={setCustomer}
        onAccountChange={setAccount}
        onResourceTypeChange={setResourceType}
        onMonitoringFilterChange={setMonitoringFilter}
        onSearchChange={setSearch}
      />

      <ResourceTable
        resources={resources}
        selectedKeys={selectedKeys}
        onSelectionChange={setSelectedKeys}
        onRowClick={(r) => router.push(`/resources/${encodeURIComponent(r.id)}`)}
        onToggleMonitoring={(id, enabled) => {
          console.log("Toggle monitoring", id, enabled);
        }}
      />

      <Pagination
        page={page}
        pageSize={pageSize}
        total={resources.length}
        onPageChange={setPage}
        onPageSizeChange={setPageSize}
      />

      <div className="grid grid-cols-4 gap-4">
        <StatCard title="전체 모니터링" value="1,102" icon={<Monitor size={18} />} />
        <StatCard title="활성 알람" value="14" icon={<AlertTriangle size={18} />} highlight />
        <StatCard title="동기화 상태" value="Healthy" icon={<RefreshCw size={18} />} />
        <StatCard title="커버리지" value="98.2%" icon={<BarChart3 size={18} />} />
      </div>

      <BulkActionBar
        selectedCount={selectedKeys.size}
        onClear={() => setSelectedKeys(new Set())}
        onEnableMonitoring={() => console.log("Enable monitoring")}
        onDisableMonitoring={() => console.log("Disable monitoring")}
        onConfigureAlarms={() => console.log("Configure alarms")}
      />
    </div>
  );
}
