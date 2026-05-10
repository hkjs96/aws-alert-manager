"use client";

import { useState } from "react";
import { X, AlertTriangle } from "lucide-react";
import { Button } from "@/components/shared/Button";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";
import {
  type MetricRow,
  METRICS_BY_TYPE,
  AVAILABLE_CW_METRICS,
  MetricConfigSection,
} from "./MetricConfigSection";

interface EnableModalProps {
  selectedIds: string[];
  selectedType: string | null;
  isSameType: boolean;
  onClose: () => void;
  onComplete: () => void;
}

export function EnableModal({
  selectedIds,
  selectedType,
  isSameType,
  onClose,
  onComplete,
}: EnableModalProps) {
  const { showToast } = useToast();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [metrics, setMetrics] = useState<MetricRow[]>(
    selectedType && METRICS_BY_TYPE[selectedType]
      ? METRICS_BY_TYPE[selectedType].map((m) => ({ ...m }))
      : [],
  );
  const [customMetrics, setCustomMetrics] = useState<MetricRow[]>([]);
  const [showCustom, setShowCustom] = useState(false);
  const [selectedCwMetric, setSelectedCwMetric] = useState("");
  const [customThreshold, setCustomThreshold] = useState(0);
  const [customUnit, setCustomUnit] = useState("");

  const availableCwMetrics = selectedType
    ? (AVAILABLE_CW_METRICS[selectedType] ?? [])
    : [];

  const addCustomFromDropdown = () => {
    if (!selectedCwMetric) return;
    const found = availableCwMetrics.find((m) => m.name === selectedCwMetric);
    if (!found) return;
    setCustomMetrics((prev) => [
      ...prev,
      { key: `cw-${Date.now()}`, name: found.name, threshold: customThreshold, unit: customUnit, direction: ">", enabled: true },
    ]);
    setSelectedCwMetric("");
    setCustomThreshold(0);
    setCustomUnit("");
    setShowCustom(false);
  };

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      // Simulate API call — replace with bulkMonitoring() when backend ready
      await new Promise((resolve) => setTimeout(resolve, 800));
      showToast("success", `${selectedIds.length}개 리소스의 모니터링을 활성화했습니다.`);
      onComplete();
    } catch {
      showToast("error", "모니터링 활성화에 실패했습니다.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-2xl rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <h3 className="text-lg font-semibold text-slate-800">모니터링 활성화</h3>
          <Button variant="ghost" onClick={onClose} icon={<X size={20} />} />
        </div>
        <div className="max-h-[60vh] overflow-y-auto px-6 py-4 space-y-4">
          <p className="text-sm text-slate-600">
            선택한 <span className="font-semibold text-primary">{selectedIds.length}개</span> 리소스의 모니터링을 활성화합니다.
          </p>
          {!isSameType && selectedIds.length > 1 ? (
            <MixedTypeWarning />
          ) : (
            <MetricConfigSection
              selectedType={selectedType}
              metrics={metrics}
              setMetrics={setMetrics}
              customMetrics={customMetrics}
              setCustomMetrics={setCustomMetrics}
              showCustom={showCustom}
              setShowCustom={setShowCustom}
              selectedCwMetric={selectedCwMetric}
              setSelectedCwMetric={setSelectedCwMetric}
              customThreshold={customThreshold}
              setCustomThreshold={setCustomThreshold}
              customUnit={customUnit}
              setCustomUnit={setCustomUnit}
              availableCwMetrics={availableCwMetrics}
              addCustomFromDropdown={addCustomFromDropdown}
            />
          )}
        </div>
        <div className="flex items-center justify-between border-t border-slate-200 px-6 py-4">
          <p className="text-xs text-slate-400">
            {isSameType ? `${metrics.filter((m) => m.enabled).length + customMetrics.length}개 메트릭 활성화 예정` : "기본 알람으로 활성화"}
          </p>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose}>취소</Button>
            <LoadingButton
              isLoading={isSubmitting}
              onClick={handleSubmit}
              className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700"
            >
              활성화
            </LoadingButton>
          </div>
        </div>
      </div>
    </div>
  );
}

function MixedTypeWarning() {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 flex items-start gap-3">
      <AlertTriangle size={18} className="text-amber-600 mt-0.5 shrink-0" />
      <div>
        <p className="text-sm font-medium text-amber-800">다른 타입의 리소스가 섞여 있습니다</p>
        <p className="text-xs text-amber-600 mt-1">같은 타입의 리소스를 선택해야 메트릭별 임계치를 설정할 수 있습니다.</p>
      </div>
    </div>
  );
}
