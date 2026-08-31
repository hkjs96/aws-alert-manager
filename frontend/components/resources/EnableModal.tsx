"use client";

import { useState } from "react";
import { X, Info } from "lucide-react";
import { Button } from "@/components/shared/Button";
import { useToast } from "@/components/shared/Toast";
import { LoadingButton } from "@/components/shared/LoadingButton";
import { describeBulkToggle, runBulkToggle } from "@/lib/bulk-toggle";

interface EnableModalProps {
  selectedIds: string[];
  selectedType: string | null;
  isSameType: boolean;
  onClose: () => void;
  /** 실제로 활성화에 성공한 리소스 ID만 넘긴다 (부분 실패 시 나머지는 그대로). */
  onComplete: (succeededIds: string[]) => void;
}

/**
 * 선택 리소스 일괄 모니터링 활성화.
 *
 * 리소스별 PUT /resources/{id}/monitoring 을 호출한다(태그 + 인벤토리 + 즉시 알람 동기화).
 * 임계치는 백엔드 규칙(Threshold_* 태그 → 기본값)을 따르며, 여기서 메트릭별 임계치를
 * 받지 않는다 — 예전 UI는 임계치 입력을 받고도 서버에 보내지 않은 채 가짜 성공을 띄웠다.
 */
export function EnableModal({
  selectedIds,
  selectedType,
  isSameType,
  onClose,
  onComplete,
}: EnableModalProps) {
  const { showToast } = useToast();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      const result = await runBulkToggle(selectedIds, true);
      const { kind, message } = describeBulkToggle(result, true);
      showToast(kind, message);
      if (result.succeeded.length > 0) onComplete(result.succeeded);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-lg rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <h3 className="text-lg font-semibold text-slate-800">모니터링 활성화</h3>
          <Button variant="ghost" onClick={onClose} icon={<X size={20} />} aria-label="닫기" />
        </div>
        <div className="px-6 py-4 space-y-4">
          <p className="text-sm text-slate-600">
            선택한 <span className="font-semibold text-primary">{selectedIds.length}개</span> 리소스의
            모니터링을 활성화합니다{isSameType && selectedType ? ` (${selectedType})` : ""}.
          </p>
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 flex items-start gap-3">
            <Info size={18} className="text-slate-500 mt-0.5 shrink-0" />
            <div className="text-xs text-slate-600 space-y-1">
              <p>
                리소스에 <code className="font-mono">Monitoring=on</code> 태그를 설정하고 필수 알람을
                즉시 생성합니다.
              </p>
              <p>
                임계치는 리소스의 <code className="font-mono">Threshold_*</code> 태그 → 기본값 순으로
                적용됩니다. 메트릭별 임계치는 활성화 후 리소스 상세에서 조정하세요.
              </p>
            </div>
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-6 py-4">
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
  );
}
