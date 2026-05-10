"use client";

import { LoadingButton } from "@/components/shared/LoadingButton";

interface ModalFooterProps {
  onCancel: () => void;
  onSubmit: () => void;
  isSubmitting: boolean;
  isSubmitDisabled: boolean;
}

export function ModalFooter({ onCancel, onSubmit, isSubmitting, isSubmitDisabled }: ModalFooterProps) {
  return (
    <div className="flex justify-end gap-3 border-t border-slate-200 px-6 py-4">
      <button
        onClick={onCancel}
        className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
      >
        Cancel
      </button>
      <LoadingButton
        isLoading={isSubmitting}
        disabled={isSubmitDisabled}
        onClick={onSubmit}
        className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary/90 disabled:opacity-40"
      >
        Create Alarm
      </LoadingButton>
    </div>
  );
}
