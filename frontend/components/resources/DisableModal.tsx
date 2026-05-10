"use client";

import { useState } from "react";
import { Button } from "@/components/shared/Button";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";

interface DisableModalProps {
  selectedIds: string[];
  onClose: () => void;
  onComplete: () => void;
}

export function DisableModal({
  selectedIds,
  onClose,
  onComplete,
}: DisableModalProps) {
  const { showToast } = useToast();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      // Simulate API call — replace with bulkMonitoring() when backend ready
      await new Promise((resolve) => setTimeout(resolve, 600));
      showToast(
        "success",
        `${selectedIds.length}개 리소스의 모니터링을 비활성화했습니다.`,
      );
      onComplete();
    } catch {
      showToast("error", "모니터링 비활성화에 실패했습니다.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <h3 className="text-lg font-semibold text-slate-800">
          모니터링 비활성화
        </h3>
        <p className="mt-2 text-sm text-slate-600">
          선택한{" "}
          <span className="font-semibold text-red-600">
            {selectedIds.length}개
          </span>{" "}
          리소스의 모니터링을 비활성화하시겠습니까? 해당 리소스의 모든 알람이
          삭제됩니다.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>취소</Button>
          <LoadingButton
            isLoading={isSubmitting}
            onClick={handleSubmit}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
          >
            비활성화
          </LoadingButton>
        </div>
      </div>
    </div>
  );
}
