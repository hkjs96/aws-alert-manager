"use client";

import { useState, useCallback } from "react";
import { X } from "lucide-react";
import { useToast } from "@/components/shared/Toast";
import { getResources } from "@/lib/mock-store";
import { isSubmitEnabled, type Track } from "@/lib/alarm-modal-utils";
import { METRICS_BY_TYPE, type MetricRow } from "@/components/resources/MetricConfigSection";
import { TrackSelector } from "./TrackSelector";
import { ResourceFilterStep } from "./ResourceFilterStep";
import { MetricConfigStep } from "./MetricConfigStep";
import { InfoBanner } from "./InfoBanner";
import { ModalFooter } from "./ModalFooter";

type ModalStep = "track-select" | "resource-filter" | "metric-config";

interface CreateAlarmModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

const INITIAL_STATE = {
  step: "track-select" as ModalStep,
  track: null as Track | null,
  customerId: "",
  accountId: "",
  resourceId: "",
};

export function CreateAlarmModal({ open, onClose, onSuccess }: CreateAlarmModalProps) {
  const { showToast } = useToast();
  const [step, setStep] = useState<ModalStep>(INITIAL_STATE.step);
  const [track, setTrack] = useState<Track | null>(INITIAL_STATE.track);
  const [customerId, setCustomerId] = useState(INITIAL_STATE.customerId);
  const [accountId, setAccountId] = useState(INITIAL_STATE.accountId);
  const [resourceId, setResourceId] = useState(INITIAL_STATE.resourceId);
  const [metrics, setMetrics] = useState<MetricRow[]>([]);
  const [customMetrics, setCustomMetrics] = useState<MetricRow[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showCustom, setShowCustom] = useState(false);
  const [selectedCwMetric, setSelectedCwMetric] = useState("");
  const [customThreshold, setCustomThreshold] = useState(0);
  const [customUnit, setCustomUnit] = useState("");

  const resetState = useCallback(() => {
    setStep(INITIAL_STATE.step);
    setTrack(INITIAL_STATE.track);
    setCustomerId(INITIAL_STATE.customerId);
    setAccountId(INITIAL_STATE.accountId);
    setResourceId(INITIAL_STATE.resourceId);
    setMetrics([]);
    setCustomMetrics([]);
    setIsSubmitting(false);
    setShowCustom(false);
    setSelectedCwMetric("");
    setCustomThreshold(0);
    setCustomUnit("");
  }, []);

  const handleClose = useCallback(() => {
    resetState();
    onClose();
  }, [resetState, onClose]);

  const selectedResource = getResources().find((r) => r.id === resourceId);
  const resourceType = selectedResource?.type ?? "";

  const handleSelectTrack = (t: Track) => {
    setTrack(t);
    setCustomerId("");
    setAccountId("");
    setResourceId("");
    setMetrics([]);
    setCustomMetrics([]);
    setShowCustom(false);
    setSelectedCwMetric("");
    setStep("resource-filter");
  };

  const handleCustomerChange = (id: string) => {
    setCustomerId(id);
    setAccountId("");
    setResourceId("");
    setMetrics([]);
    setCustomMetrics([]);
  };

  const handleAccountChange = (id: string) => {
    setAccountId(id);
    setResourceId("");
    setMetrics([]);
    setCustomMetrics([]);
  };

  const handleResourceChange = (id: string) => {
    setResourceId(id);
    if (id && track === 2) {
      const res = getResources().find((r) => r.id === id);
      if (res) {
        const defaultMetrics = METRICS_BY_TYPE[res.type] ?? [];
        setMetrics(defaultMetrics.map((m) => ({ ...m })));
      }
    } else {
      setMetrics([]);
    }
    setCustomMetrics([]);
    setShowCustom(false);
    setSelectedCwMetric("");
    if (id) setStep("metric-config");
  };

  const handleSubmit = async () => {
    if (!track || !resourceId) return;
    setIsSubmitting(true);
    try {
      // Collect all active metrics into the payload
      const activeMetrics: { metric_name: string; threshold: number; unit: string; direction: ">" | "<" }[] = [];

      if (track === 2) {
        for (const m of metrics) {
          if (m.enabled) {
            activeMetrics.push({
              metric_name: m.name,
              threshold: m.threshold,
              unit: m.unit,
              direction: m.direction as ">" | "<",
            });
          }
        }
      }
      for (const m of customMetrics) {
        activeMetrics.push({
          metric_name: m.name,
          threshold: m.threshold,
          unit: m.unit,
          direction: m.direction as ">" | "<",
        });
      }

      const res = await fetch("/api/alarms/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resource_id: resourceId, track, metrics: activeMetrics }),
      });

      if (!res.ok) throw new Error("API Error");

      showToast("success", "알람이 성공적으로 생성되었습니다.");
      handleClose();
      onSuccess?.();
    } catch {
      showToast("error", "알람 생성에 실패했습니다. 다시 시도해주세요.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const submitDisabled = !track || !resourceId || !isSubmitEnabled(track, metrics, customMetrics);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={handleClose} />
      <div
        data-testid="create-alarm-modal"
        className="relative z-10 flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-2xl"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <h2 className="text-lg font-bold text-slate-900">Create Alarm</h2>
          <button data-testid="close-button" onClick={handleClose} className="text-slate-400 hover:text-slate-600">
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          <TrackSelector selectedTrack={track} onSelectTrack={handleSelectTrack} />

          {step !== "track-select" && track && (
            <ResourceFilterStep
              track={track}
              customerId={customerId}
              accountId={accountId}
              resourceId={resourceId}
              onCustomerChange={handleCustomerChange}
              onAccountChange={handleAccountChange}
              onResourceChange={handleResourceChange}
            />
          )}

          {step === "metric-config" && track && resourceId && (
            <>
              <InfoBanner message="알람 알림은 기본 SNS 토픽(alarm-notifications)으로 전달됩니다." />
              <MetricConfigStep
                track={track}
                resourceType={resourceType}
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
              />
            </>
          )}
        </div>

        {/* Footer */}
        <ModalFooter
          onCancel={handleClose}
          onSubmit={handleSubmit}
          isSubmitting={isSubmitting}
          isSubmitDisabled={submitDisabled}
        />
      </div>
    </div>
  );
}
