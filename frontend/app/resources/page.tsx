import { MOCK_RESOURCES } from "@/lib/mock-data";
import { paginate } from "@/lib/mock-data";
import { ResourcesContent } from "@/components/resources/ResourcesContent";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Resources | Alarm Manager",
  description:
    "Manage and monitor AWS entities across all registered accounts.",
};

// When real backend API is ready, replace mock imports with:
// import { fetchResources } from "@/lib/api-functions";

interface ResourcesPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function ResourcesPage({
  searchParams,
}: ResourcesPageProps) {
  const params = await searchParams;
  const page = Math.max(1, Number(params.page) || 1);
  const pageSize = [25, 50, 100].includes(Number(params.page_size))
    ? Number(params.page_size)
    : 25;

  // Pragmatic approach: use mock data directly for now.
  // When the real backend API is ready, swap to:
  //   const result = await fetchResources({
  //     page, page_size: pageSize,
  //     customer_id: params.customer_id as string,
  //     account_id: params.account_id as string,
  //     resource_type: params.resource_type as string,
  //     search: params.search as string,
  //   });
  const result = paginate(MOCK_RESOURCES, page, pageSize);

  return (
    <ResourcesContent
      resources={result.items}
      total={result.total}
      page={result.page}
      pageSize={result.page_size}
    />
  );
}
