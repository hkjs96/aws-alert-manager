import { ThresholdSection } from "@/components/settings/ThresholdSection";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Settings | Alarm Manager",
  description: "Configure default threshold policies for monitored resources.",
};

export default async function SettingsPage() {
  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-3xl font-headline font-extrabold tracking-tight text-slate-900">
          Settings
        </h1>
        <p className="text-slate-500 text-sm mt-1">
          Configure default threshold policies for monitored resources.
        </p>
      </header>

      <ThresholdSection />
    </div>
  );
}
