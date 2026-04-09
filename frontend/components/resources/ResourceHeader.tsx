"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronLeft, ShieldCheck, ShieldOff } from "lucide-react";
import { useMonitoringToggle } from "@/hooks/useMonitoringToggle";
import type { Resource } from "@/types";

interface ResourceHeaderProps {
  resource: Resource;
}

export function ResourceHeader({ resource }: ResourceHeaderProps) {
  const router = useRouter();
  const { loadingIds, toggle } = useMonitoringToggle();
  const [monitoring, setMonitoring] = useState(resource.monitoring);
  const isToggling = loadingIds.has(resource.id);

  const handleToggle = async () => {
    const success = await toggle(resource.id, monitoring);
    if (success) {
      setMonitoring((prev) => !prev);
      router.refresh();
    }
  };

  const tags = [
    { label: "ID", value: resource.id, mono: true },
    { label: "Type", value: resource.type },
    { label: "Account", value: resource.account, mono: true },
    { label: "Region", value: resource.region },
  ];

  return (
    <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
      <div>
        <Link
          href="/resources"
          className="flex items-center gap-2 text-sm text-slate-500 font-medium mb-2 hover:text-primary transition-colors"
        >
          <ChevronLeft size={16} />
          <span>Back to Resource Fleet</span>
        </Link>
        <h1 className="text-3xl font-headline font-semibold tracking-tight text-slate-900">
          {resource.name}
        </h1>
        <div className="mt-4 flex flex-wrap gap-3">
          {tags.map((tag) => (
            <div
              key={tag.label}
              className="flex items-center bg-slate-100 px-3 py-1.5 rounded-lg border border-slate-200"
            >
              <span className="text-[10px] uppercase font-bold text-slate-400 mr-2 opacity-60">
                {tag.label}
              </span>
              <span className={`text-sm font-medium ${tag.mono ? "font-mono" : ""}`}>
                {tag.value}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div
        className={`p-5 rounded-xl shadow-soft border flex flex-col gap-3 transition-colors duration-300 min-w-[200px] ${
          monitoring
            ? "bg-green-50 border-green-200"
            : "bg-slate-50 border-slate-200"
        }`}
      >
        <div className="text-xs font-bold text-slate-500 uppercase tracking-wider">
          Monitoring Status
        </div>
        <div className={`text-base font-headline font-bold flex items-center gap-1.5 ${
          monitoring ? "text-green-700" : "text-slate-500"
        }`}>
          {monitoring ? (
            <ShieldCheck size={15} className="text-green-600" />
          ) : (
            <ShieldOff size={15} className="text-slate-400" />
          )}
          {monitoring ? "Monitoring On" : "Monitoring Off"}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleToggle}
            disabled={isToggling}
            className={`w-12 h-6 rounded-full relative transition-all duration-300 flex-shrink-0 ${
              monitoring ? "bg-green-500" : "bg-slate-300"
            } ${isToggling ? "opacity-50 cursor-not-allowed" : ""}`}
          >
            <div
              className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow-sm transition-all duration-300 ${
                monitoring ? "left-6" : "left-0.5"
              }`}
            />
          </button>
          {monitoring ? (
            <span className="text-[10px] font-bold bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
              ON
            </span>
          ) : (
            <span className="text-[10px] font-bold bg-slate-200 text-slate-500 px-2 py-0.5 rounded-full">
              OFF
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
