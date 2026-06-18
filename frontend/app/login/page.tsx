import Link from "next/link";
import { HelpCircle, Bell, Check } from "lucide-react";
import { LoginButton } from "./LoginButton";

const FEATURES = [
  "29종 AWS 리소스 자동 수집·동기화",
  "리소스별 실시간 임계값 알람",
  "고객사·팀 단위 운영 관리",
];

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; callbackUrl?: string }>;
}) {
  const { error, callbackUrl } = await searchParams;
  const denied = error === "AccessDenied";

  return (
    <main className="grid min-h-screen lg:grid-cols-2">
      {/* 좌측 브랜드 히어로 (데스크톱) */}
      <div className="relative hidden overflow-hidden bg-gradient-to-br from-primary via-blue-800 to-slate-900 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-white/10 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 -left-16 h-80 w-80 rounded-full bg-blue-400/20 blur-3xl" />

        <div className="relative flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/15 ring-1 ring-white/20">
            <Bell size={18} fill="currentColor" />
          </span>
          <div>
            <p className="text-base font-bold leading-tight">Alarm Manager</p>
            <p className="text-xs text-white/60">AWS Monitoring</p>
          </div>
        </div>

        <div className="relative">
          <h2 className="font-headline text-4xl font-extrabold leading-tight">
            AWS 리소스를<br />한눈에 모니터링
          </h2>
          <p className="mt-4 max-w-md text-sm leading-relaxed text-white/70">
            29종 AWS 리소스를 자동 수집하고, 임계값 기반 알람을 관리하세요.
            고객사별로 정리된 운영 대시보드를 제공합니다.
          </p>
          <ul className="mt-8 space-y-3 text-sm text-white/90">
            {FEATURES.map((f) => (
              <li key={f} className="flex items-center gap-2.5">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-white/15">
                  <Check size={12} />
                </span>
                {f}
              </li>
            ))}
          </ul>
        </div>

        <p className="relative text-xs text-white/40">
          사내 운영 도구 · 허용된 계정만 접근 가능
        </p>
      </div>

      {/* 우측 로그인 폼 */}
      <div className="flex items-center justify-center bg-surface p-6">
        <div className="w-full max-w-sm">
          {/* 모바일 로고 */}
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-white">
              <Bell size={18} fill="currentColor" />
            </span>
            <span className="text-lg font-bold text-slate-900">Alarm Manager</span>
          </div>

          <h1 className="text-2xl font-bold tracking-tight text-slate-900">환영합니다 👋</h1>
          <p className="mt-1.5 text-sm text-slate-500">회사 Google 계정으로 로그인하세요.</p>

          {denied && (
            <p className="mt-5 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              허용되지 않은 계정입니다. 관리자에게 문의하세요.
            </p>
          )}

          <div className="mt-7">
            <LoginButton callbackUrl={callbackUrl ?? "/"} />
          </div>

          <Link
            href="/help"
            className="mt-4 flex items-center justify-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-800"
          >
            <HelpCircle size={14} /> 처음이신가요? 사용 가이드 보기
          </Link>

          <p className="mt-10 text-center text-[11px] text-slate-400">
            로그인하면 접근 정책에 동의하는 것으로 간주됩니다.
          </p>
        </div>
      </div>
    </main>
  );
}
