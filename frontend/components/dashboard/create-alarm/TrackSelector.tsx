"use client";

import { Monitor, PlusCircle } from "lucide-react";
import type { Track } from "@/lib/alarm-modal-utils";

interface TrackSelectorProps {
  selectedTrack: Track | null;
  onSelectTrack: (track: Track) => void;
}

const TRACKS = [
  {
    track: 1 as Track,
    title: "Add Custom Alarm",
    description: "Add a CloudWatch custom metric alarm to a resource that is already monitored.",
    icon: PlusCircle,
    testId: "track-card-1",
  },
  {
    track: 2 as Track,
    title: "Set Up New Monitoring",
    description: "Enable monitoring for an unmonitored resource and create its alarms.",
    icon: Monitor,
    testId: "track-card-2",
  },
] as const;

export function TrackSelector({ selectedTrack, onSelectTrack }: TrackSelectorProps) {
  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-slate-700">Select Track</h3>
      <div className="grid grid-cols-2 gap-4">
        {TRACKS.map(({ track, title, description, icon: Icon, testId }) => {
          const selected = selectedTrack === track;
          return (
            <button
              key={track}
              data-testid={testId}
              onClick={() => onSelectTrack(track)}
              className={`flex flex-col items-start gap-3 rounded-lg border-2 p-4 text-left transition-all ${
                selected
                  ? "border-primary bg-primary/5 shadow-sm"
                  : "border-slate-200 bg-white hover:border-slate-300"
              }`}
            >
              <Icon size={24} className={selected ? "text-primary" : "text-slate-400"} />
              <div>
                <p className="text-sm font-semibold text-slate-800">{title}</p>
                <p className="mt-1 text-xs text-slate-500">{description}</p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
