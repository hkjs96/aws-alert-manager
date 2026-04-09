"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { useMonitoringToggle } from "@/hooks/useMonitoringToggle";
import type { Resource } from "@/types";

interface ResourceHeaderProps {
  resource: Resource;
}

export function ResourceHeader({ resource }: ResourceHeaderProps) {
  const { loadingIds, toggle } = useMonitoringToggle();
  const [monitoring, setMonitoring] = useState(resource.monitoring);
  const isToggling = loadingIds.has(resource.id);

  const handleToggle = async () => {
    const success = await toggle(resource.id, monitoring);
    if (success) setMonitoring((prev) => !prev);
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

      <div className="bg-white/80 backdrop-blur-xl p-5 rounded-xl shadow-soft border border-slate-200 flex items-center gap-6">
        <div>
          <div className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1">
            Monitoring Status
          </div>
          <div className="text-lg font-headline font-bold text-primary">
            {monitoring ? "Active Protection" : "Monitoring Off"}
          </div>
        </div>
        <button
          onClick={handleToggle}
          disabled={isToggling}
          className={`w-14 h-7 rounded-full relative transition-all duration-300 ${
            monitoring ? "bg-primary" : "bg-slate-300"
          } ${isToggling ? "opacity-50 cursor-not-allowed" : ""}`}
        >
          <div
            className={`absolute top-1 w-5 h-5 bg-white rounded-full shadow-sm transition-all duration-300 ${
              monitoring ? "left-8" : "left-1"
            }`}
          />
        </button>
      </div>
    </div>
  );
}
