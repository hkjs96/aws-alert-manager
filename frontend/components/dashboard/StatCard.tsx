interface StatCardProps {
  title: string;
  value: number | string;
  icon?: React.ReactNode;
  highlight?: boolean;
  subtitle?: string;
}

export function StatCard({ title, value, icon, highlight = false, subtitle }: StatCardProps) {
  return (
    <div
      className={`rounded-lg border p-5 ${
        highlight ? "border-red-200 bg-red-50" : "border-slate-200 bg-white"
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wider text-slate-500">{title}</span>
        {icon && <span className="text-slate-400">{icon}</span>}
      </div>
      <p className={`mt-2 text-3xl font-bold ${highlight ? "text-red-600" : "text-slate-800"}`}>
        {value}
      </p>
      {subtitle && <p className="mt-1 text-xs text-slate-500">{subtitle}</p>}
    </div>
  );
}
