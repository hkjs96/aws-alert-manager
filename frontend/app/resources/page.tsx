import { fetchResources, fetchCustomerOptions, fetchAccountOptions } from "@/lib/server/data";
import { ResourcesContent } from "@/components/resources/ResourcesContent";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Resources | Alarm Manager",
  description: "Manage and monitor AWS entities across all registered accounts.",
};

export default async function ResourcesPage() {
  const [resources, customers, accounts] = await Promise.all([
    fetchResources(),
    fetchCustomerOptions(),
    fetchAccountOptions(),
  ]);

  return (
    <ResourcesContent
      resources={resources}
      customers={customers}
      accounts={accounts}
    />
  );
}
