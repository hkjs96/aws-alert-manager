import { MOCK_RESOURCES, MOCK_ACCOUNTS, MOCK_CUSTOMERS } from "@/lib/mock-data";
import { ResourcesContent } from "@/components/resources/ResourcesContent";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Resources | Alarm Manager",
  description: "Manage and monitor AWS entities across all registered accounts.",
};

export default async function ResourcesPage() {
  const customerDtos = MOCK_CUSTOMERS.map((c) => ({
    id: c.customer_id,
    name: c.name,
  }));

  const accountDtos = MOCK_ACCOUNTS.map((a) => ({
    id: a.account_id,
    name: a.name,
    customerId: a.customer_id,
  }));

  return (
    <ResourcesContent
      resources={MOCK_RESOURCES}
      customers={customerDtos}
      accounts={accountDtos}
    />
  );
}
