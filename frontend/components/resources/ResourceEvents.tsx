import { History } from "lucide-react";
import type { RecentAlarm } from "@/types";

interface ResourceEventsProps {
  events: RecentAlarm[];
}

const SEVERITY_DOT_COLORS: Record<string, string> = {
  "SEV-1": "bg-red-600",
  "SEV-2": "bg-error",
  "SEV-3": "bg-amber-500",
  "SEV-4": "bg-blue-500",
  "SEV-5": "bg-slate-400",
};

export function ResourceEvents({ events }: ResourceEventsProps) {
  return (
    <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-soft">
      <div className="flex items-center gap-3 mb-4">
        <History size={18} className="text-tertiary" />
        <h3 className="font-headline font-bold text-sm">Recent Events</h3>
      </div>
      {events.length === 0 ? (
        <p className="text-sm text-slate-400">No recent events.</p>
      ) : (
        <div className="space-y-4">
          {events.map((event) => {
            const dotColor = SEVERITY_DOT_COLORS[event.severity] ?? "bg-slate-400";
            const time = new Date(event.timestamp).toLocaleTimeString("en-US", {
              hour12: false,
              timeZone: "UTC",
            });
            return (
              <div key={`${event.timestamp}-${event.metric}`} className="flex gap-3">
                <div className={`w-1.5 h-1.5 rounded-full ${dotColor} mt-1.5 shrink-0`} />
                <div>
                  <div className="text-xs font-mono opacity-60">{time} UTC</div>
                  <div className="text-xs font-medium">
                    {event.metric} {event.state_change} — {event.value} / {event.threshold}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
