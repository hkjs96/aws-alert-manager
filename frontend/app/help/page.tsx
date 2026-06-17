import {
  LogIn, Users, Server, Bell, Search, Trash2, ShieldCheck,
} from "lucide-react";

export const metadata = {
  title: "사용 가이드 · Alarm Manager",
};

interface GuideStep {
  icon: typeof LogIn;
  title: string;
  body: React.ReactNode;
}

const STEPS: GuideStep[] = [
  {
    icon: LogIn,
    title: "1. 로그인",
    body: (
      <>회사 Google 계정으로 로그인합니다. 허용된 계정/도메인만 접근할 수 있으며,
      로그인하면 우상단에 본인 이메일과 로그아웃 버튼이 표시됩니다.</>
    ),
  },
  {
    icon: Users,
    title: "2. 담당 고객사 선택 (중요)",
    body: (
      <><b>Settings → Customer List</b>에서 각 고객사의 <b>“담당” 체크박스</b>를 켜세요.
      체크한 고객사만 대시보드·리소스·알람 화면에 표시됩니다. <b>아무것도 체크하지 않으면
      화면이 비어 있습니다.</b> 이 선택은 계정에 저장되어 다른 기기에서도 유지됩니다.</>
    ),
  },
  {
    icon: Server,
    title: "3. 리소스 모니터링",
    body: (
      <><b>Resources</b> 화면에서 AWS 리소스를 확인하고, 토글로 모니터링을 켜고 끕니다.
      타입은 색상 배지(EC2·RDS·S3 등)로 구분됩니다. 모니터링을 켜면 해당 리소스에
      알람이 생성됩니다.</>
    ),
  },
  {
    icon: Bell,
    title: "4. 알람 확인",
    body: (
      <><b>Alarms</b> 화면에서 전체 알람 상태를 봅니다. 상단바 <b>벨 아이콘</b>을 누르면
      현재 ALARM 상태인 항목이 드롭다운으로 떠서 바로 해당 리소스로 이동할 수 있습니다.</>
    ),
  },
  {
    icon: Search,
    title: "5. 검색",
    body: (
      <>상단바 <b>검색창</b>에 리소스 이름을 입력하고 Enter를 누르면 Resources 화면에서
      해당 이름으로 필터링됩니다.</>
    ),
  },
  {
    icon: ShieldCheck,
    title: "6. 권한 (관리자)",
    body: (
      <>고객사 <b>생성·편집</b>은 모든 사용자가 할 수 있습니다. 고객사 <b>삭제</b>는
      관리자(admin)만 가능하며, 관리자에게만 삭제 버튼이 보입니다.</>
    ),
  },
];

export default function HelpPage() {
  return (
    <div className="max-w-3xl space-y-8">
      <div>
        <h1 className="text-3xl font-headline font-extrabold tracking-tight text-slate-900">
          사용 가이드
        </h1>
        <p className="text-slate-500 text-sm mt-1">
          팀원이 Alarm Manager를 사용하는 데 필요한 기본 흐름입니다.
        </p>
      </div>

      <div className="space-y-4">
        {STEPS.map((step) => (
          <div
            key={step.title}
            className="flex gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-soft"
          >
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <step.icon size={20} />
            </span>
            <div>
              <h2 className="text-base font-semibold text-slate-800">{step.title}</h2>
              <p className="mt-1 text-sm leading-relaxed text-slate-600">{step.body}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
        <Trash2 size={15} className="mr-1 inline align-text-bottom" />
        <b>팁:</b> 화면이 비어 보이면 먼저 <b>Settings에서 담당 고객사를 체크</b>했는지 확인하세요.
      </div>
    </div>
  );
}
