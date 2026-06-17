import { fetchResources, fetchCustomerOptions, fetchAccountOptions } from "@/lib/server/data";
import { ResourcesContent } from "@/components/resources/ResourcesContent";
import type { Metadata } from "next";
import type { Resource } from "@/types";

export const metadata: Metadata = {
  title: "Resources | Alarm Manager",
  description: "Manage and monitor AWS entities across all registered accounts.",
};

export default async function ResourcesPage({
  searchParams,
}: {
  searchParams: Promise<{ search?: string }>;
}) {
  const { search } = await searchParams;
  let resources: Resource[] = [];
  let customers: { id: string; name: string }[] = [];
  let accounts: { id: string; name: string; customerId: string }[] = [];
  try {
    [resources, customers, accounts] = await Promise.all([
      fetchResources(),
      fetchCustomerOptions(),
      fetchAccountOptions(),
    ]);
  } catch (error) {
    console.error("[ResourcesPage] Failed to fetch data:", error);
  }

  return (
    <ResourcesContent
      resources={resources}
      customers={customers}
      accounts={accounts}
      initialSearch={search ?? ""}
    />
  );
}
