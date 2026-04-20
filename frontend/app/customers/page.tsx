import { getCustomers, getAccounts } from "@/lib/mock-store";
import { CustomerSection } from "@/components/settings/CustomerSection";
import { AccountSection } from "@/components/settings/AccountSection";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Customers | Alarm Manager",
  description: "Manage customer organizations and AWS account integrations.",
};

export default async function CustomersPage() {
  const customers = getCustomers();
  const accounts = getAccounts();

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-3xl font-headline font-extrabold tracking-tight text-slate-900">
          Customer Management
        </h1>
        <p className="text-slate-500 text-sm mt-1">
          Manage customer organizations and their AWS account integrations.
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
    </div>
  );
}
