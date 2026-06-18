import Link from "next/link";
import { HelpCircle, Bell, Check } from "lucide-react";
import { LoginButton } from "./LoginButton";

const FEATURES = [
  "태그 기반 알람 생성·관리",
  "29종 AWS 리소스 타입 지원",
  "고객사·계정 단위 정리",
];

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; callbackUrl?: string }>;
}) {
  const { error, callbackUrl } = await searchParams;
  const denied = error === "AccessDenied";

  return (
    <main className="grid min-h-screen bg-surface lg:grid-cols-2">
      {/* 좌측 브랜드 패널 (데스크톱) — 앱과 동일한 화이트/슬레이트/블루 톤 */}
      <div className="relative hidden overflow-hidden border-r border-slate-200 bg-white p-12 lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-primary/5 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-24 -left-16 h-72 w-72 rounded-full bg-primary/5 blur-3xl" />

        <div className="relative flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-white shadow-sm">
            <Bell size={18} fill="currentColor" />
          </span>
          <div>
            <p className="text-base font-bold text-slate-900">Alarm Manager</p>
            <p className="text-xs text-slate-400">AWS Monitoring</p>
          </div>
        </div>

        <div className="relative">
          <h2 className="font-headline text-4xl font-extrabold leading-tight text-slate-900">
            태그 기반<br />
            <span className="text-primary">AWS 알람 관리</span>
          </h2>
          <p className="mt-4 max-w-md text-sm leading-relaxed text-slate-500">
            AWS 리소스의 CloudWatch 알람을 태그 기반으로 생성하고 관리합니다.
            29종 리소스 타입을 지원합니다.
          </p>
          <ul className="mt-8 space-y-3 text-sm text-slate-600">
            {FEATURES.map((f) => (
              <li key={f} className="flex items-center gap-2.5">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/10 text-primary">
                  <Check size={12} />
                </span>
                {f}
              </li>
            ))}
          </ul>
        </div>

        <p className="relative text-xs text-slate-400">
          AWS CloudWatch · 태그 기반 알람 관리
        </p>
      </div>

      {/* 우측 로그인 폼 */}
      <div className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm">
          {/* 모바일 로고 */}
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-white">
              <Bell size={18} fill="currentColor" />
            </span>
            <span className="text-lg font-bold text-slate-900">Alarm Manager</span>
          </div>

          <h1 className="text-2xl font-bold tracking-tight text-slate-900">로그인</h1>
          <p className="mt-1.5 text-sm text-slate-500">회사 Google 계정으로 시작하세요.</p>

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
            className="mt-3 flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
          >
            <HelpCircle size={16} className="text-primary" /> 처음이신가요? 사용 가이드 보기
          </Link>

          <p className="mt-10 text-center text-[11px] text-slate-400">
            허용된 계정만 접근할 수 있습니다.
          </p>
        </div>
      </div>
    </main>
  );
}
