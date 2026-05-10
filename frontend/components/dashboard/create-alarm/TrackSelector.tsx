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
    title: "커스텀 알람 추가",
    description: "이미 모니터링 중인 리소스에 CloudWatch 커스텀 메트릭 알람을 추가합니다.",
    icon: PlusCircle,
    testId: "track-card-1",
  },
  {
    track: 2 as Track,
    title: "새 모니터링 설정",
    description: "미모니터링 리소스에 대해 모니터링을 활성화하고 알람을 생성합니다.",
    icon: Monitor,
    testId: "track-card-2",
  },
] as const;

export function TrackSelector({ selectedTrack, onSelectTrack }: TrackSelectorProps) {
  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-slate-700">트랙 선택</h3>
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
