import Link from "next/link";
import { HelpCircle } from "lucide-react";
import { LoginButton } from "./LoginButton";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; callbackUrl?: string }>;
}) {
  const { error, callbackUrl } = await searchParams;
  const denied = error === "AccessDenied";

  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="w-full max-w-sm rounded-2xl border border-gray-200 bg-white p-8 shadow-sm">
        <h1 className="mb-1 text-xl font-semibold text-gray-900">AWS Alert Manager</h1>
        <p className="mb-6 text-sm text-gray-500">Google 계정으로 로그인하세요.</p>
        {denied && (
          <p className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">
            허용되지 않은 계정입니다. 관리자에게 문의하세요.
          </p>
        )}
        <LoginButton callbackUrl={callbackUrl ?? "/"} />

        <Link
          href="/help"
          className="mt-4 flex items-center justify-center gap-1.5 text-xs font-medium text-gray-500 hover:text-gray-800"
        >
          <HelpCircle size={14} /> 처음이신가요? 사용 가이드 보기
        </Link>
      </div>
    </main>
  );
}
