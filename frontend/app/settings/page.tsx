import { ThresholdSection } from "@/components/settings/ThresholdSection";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Settings | Alarm Manager",
  description: "Configure default threshold policies for monitored resources.",
};

export default async function SettingsPage() {
  return (
    <div className="space-y-8">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800 font-headline">Settings</h1>
          <p className="text-sm text-slate-500 mt-1">Configure default threshold policies for monitored resources.</p>
        </div>
      </header>

      <ThresholdSection />
    </div>
  );
}
