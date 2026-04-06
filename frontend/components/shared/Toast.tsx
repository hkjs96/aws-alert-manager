"use client";

interface ToastProps {
  message: string;
  type: "success" | "error" | "warning";
  onClose: () => void;
  onRetry?: () => void;
}

const TOAST_STYLES = {
  success: "border-green-200 bg-green-50 text-green-800",
  error: "border-red-200 bg-red-50 text-red-800",
  warning: "border-amber-200 bg-amber-50 text-amber-800",
};

export function Toast({ message, type, onClose, onRetry }: ToastProps) {
  return (
    <div className={`flex items-center gap-3 rounded-lg border px-4 py-3 text-sm shadow-sm ${TOAST_STYLES[type]}`}>
      <span className="flex-1">{message}</span>
      {onRetry && (
        <button onClick={onRetry} className="font-medium underline hover:no-underline">
          재시도
        </button>
      )}
      <button onClick={onClose} className="text-lg leading-none opacity-60 hover:opacity-100">
        ×
      </button>
    </div>
  );
}
