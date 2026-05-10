import Link from "next/link";

export function OwnedEmptyState() {
  return (
    <div
      className="flex flex-col items-center justify-center py-20 text-center"
      data-testid="owned-empty-state"
    >
      <span className="text-4xl mb-4">🏢</span>
      <p className="text-base font-semibold text-slate-700">담당 고객사가 없습니다</p>
      <p className="text-sm text-slate-400 mt-1 mb-4">
        고객사 페이지에서 담당 고객사를 먼저 선택하세요
      </p>
      <Link
        href="/customers"
        className="px-4 py-2 bg-primary text-white rounded-lg text-sm font-semibold hover:brightness-110 transition-all"
      >
        고객사 페이지로 이동
      </Link>
    </div>
  );
}
