"use client";

import { useState } from "react";
import { Button } from "@/components/shared/Button";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { describeBulkToggle, runBulkToggle } from "@/lib/bulk-toggle";

interface DisableModalProps {
  selectedIds: string[];
  onClose: () => void;
  /** 실제로 비활성화에 성공한 리소스 ID만 넘긴다 (부분 실패 시 나머지는 그대로). */
  onComplete: (succeededIds: string[]) => void;
}

/** 선택 리소스 일괄 모니터링 비활성화 — 리소스별 PUT /resources/{id}/monitoring. */
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
      const result = await runBulkToggle(selectedIds, false);
      const { kind, message } = describeBulkToggle(result, false);
      showToast(kind, message);
      if (result.succeeded.length > 0) onComplete(result.succeeded);
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
