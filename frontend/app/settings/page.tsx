import { MOCK_CUSTOMERS, MOCK_ACCOUNTS } from "@/lib/mock-data";
import { CustomerSection } from "@/components/settings/CustomerSection";
import { AccountSection } from "@/components/settings/AccountSection";
import { ThresholdSection } from "@/components/settings/ThresholdSection";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Settings | Alarm Manager",
  description:
    "Configure global customer mappings, AWS account integration, and resource threshold overrides.",
};

// When real backend API is ready, replace mock imports with:
// import { fetchCustomers, fetchAccounts } from "@/lib/api-functions";

export default async function SettingsPage() {
  // Pragmatic approach: use mock data directly for now.
  // When the real backend API is ready, swap to:
  //   const [customers, accounts] = await Promise.all([
  //     fetchCustomers(),
  //     fetchAccounts(),
  //   ]);
  const customers = MOCK_CUSTOMERS;
  const accounts = MOCK_ACCOUNTS;

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-4xl font-headline font-semibold tracking-tight text-slate-900 mb-2">
          System Settings
        </h1>
        <p className="text-slate-500 max-w-2xl">
          Configure global customer mappings, AWS account integration, and
          define resource threshold overrides.
        </p>
      </header>

      <div className="grid grid-cols-12 gap-8">
        <section className="col-span-12 lg:col-span-5">
          <CustomerSection customers={customers} />
        </section>
        <section className="col-span-12 lg:col-span-7">
          <AccountSection accounts={accounts} customers={customers} />
        </section>
      </div>

      <ThresholdSection />
    </div>
  );
}
