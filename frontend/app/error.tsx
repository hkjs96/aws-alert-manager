"use client";

import { useEffect } from "react";

interface ErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function Error({ error, reset }: ErrorProps) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center min-h-[400px] gap-4 text-center px-4">
      <div className="text-5xl">⚠️</div>
      <h2 className="text-xl font-semibold text-slate-800">페이지 로드에 실패했습니다</h2>
      <p className="text-sm text-slate-500 max-w-sm">
        {error.message || "알 수 없는 오류가 발생했습니다. 잠시 후 다시 시도해주세요."}
      </p>
      <button
        onClick={reset}
        className="px-4 py-2 text-sm font-medium text-white bg-primary rounded-lg hover:bg-primary/90 transition-colors"
      >
        다시 시도
      </button>
    </div>
  );
}
