"use client";

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
}

export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
}: PaginationProps) {
  const totalPages = Math.ceil(total / pageSize);
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);

  return (
    <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3">
      <span className="text-sm text-slate-500">
        {total > 0 ? `${start}-${end} / ${total}건` : "0건"}
      </span>
      <div className="flex items-center gap-3">
        <select
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          className="rounded-md border border-slate-200 px-2 py-1 text-sm"
        >
          {[25, 50, 100].map((s) => (
            <option key={s} value={s}>{s}개</option>
          ))}
        </select>
        <div className="flex gap-1">
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1}
            className="rounded-md border border-slate-200 px-2 py-1 text-sm disabled:opacity-40"
          >
            ‹
          </button>
          <span className="flex items-center px-2 text-sm text-slate-600">
            {page} / {totalPages || 1}
          </span>
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages}
            className="rounded-md border border-slate-200 px-2 py-1 text-sm disabled:opacity-40"
          >
            ›
          </button>
        </div>
      </div>
    </div>
  );
}
