import { fetchCustomers, fetchAccounts } from "@/lib/server/data";
import { CustomerSection } from "@/components/settings/CustomerSection";
import { AccountSection } from "@/components/settings/AccountSection";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Customers | Alarm Manager",
  description: "Manage customer organizations and AWS account integrations.",
};

export default async function CustomersPage() {
  const [customers, accounts] = await Promise.all([
    fetchCustomers(),
    fetchAccounts(),
  ]);

  return (
    <div className="space-y-8">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800 font-headline">Customer Management</h1>
          <p className="text-sm text-slate-500 mt-1">Manage customer organizations and their AWS account integrations.</p>
        </div>
      </header>

      <div className="grid grid-cols-12 gap-8">
        <section className="col-span-12 lg:col-span-5">
          <CustomerSection customers={customers} />
        </section>
        <section className="col-span-12 lg:col-span-7">
          <AccountSection accounts={accounts} customers={customers} />
        </section>
      </div>
    </div>
  );
}
