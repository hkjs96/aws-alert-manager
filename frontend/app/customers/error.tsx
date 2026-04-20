"use client";

import { ErrorPanel } from "@/components/shared/ErrorPanel";

export default function CustomersError({ reset }: { reset: () => void }) {
  return <ErrorPanel message="Failed to load customer data." onRetry={reset} />;
}
