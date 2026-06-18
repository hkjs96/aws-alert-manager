import type { ReactNode } from "react";
import Link from "next/link";
import {
  LogIn, Users, Server, Bell, Search, ShieldCheck, Boxes, SlidersHorizontal,
  Rocket, KeyRound, Cloud, Wrench, ListChecks, FolderGit2, ArrowLeft,
  Lightbulb, Network, Database, Share2, Workflow,
} from "lucide-react";

export const metadata = {
  title: "사용 가이드 · Alarm Manager",
};

type Icon = typeof LogIn;

interface Item {
  icon: Icon;
  title: string;
  body: ReactNode;
}

interface Section {
  id: string;
  label: string;
  intro?: string;
  items: Item[];
}

function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[12px] text-slate-700">
      {children}
    </code>
  );
}

function Block({ children }: { children: ReactNode }) {
  return (
    <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-900 px-4 py-3 text-[12px] leading-relaxed text-slate-100">
      {children}
    </pre>
  );
}

const SECTIONS: Section[] = [
  {
    id: "user",
    label: "사용자 가이드",
    intro: "처음 사용하는 팀원이 알아야 할 기본 흐름입니다.",
    items: [
      {
        icon: LogIn,
        title: "로그인",
        body: (
          <>회사 Google 계정으로 로그인합니다. 허용된 이메일/도메인만 접근할 수 있습니다.
          로그인하면 우상단에 본인 이메일과 로그아웃 버튼이 보입니다. 세션이 만료되면 다시
          로그인 화면으로 이동합니다.</>
        ),
      },
      {
        icon: Users,
        title: "담당 고객사 선택 (가장 먼저!)",
        body: (
          <>
            <b>Settings → Customer List</b>에서 각 고객사의 <b>“담당” 체크박스</b>를 켭니다.
            <ul className="ml-4 mt-1.5 list-disc space-y-0.5">
              <li>체크한 고객사만 <b>대시보드·리소스·알람</b>에 표시됩니다.</li>
              <li><b>아무것도 체크하지 않으면 모든 화면이 비어 있습니다</b> (의도된 동작).</li>
              <li>이 선택은 <b>계정(DB)에 저장</b>되어 다른 PC/브라우저에서도 유지됩니다.</li>
            </ul>
          </>
        ),
      },
      {
        icon: Server,
        title: "리소스 & 모니터링",
        body: (
          <>
            <b>Resources</b> 화면에서 등록된 AWS 리소스를 봅니다. 타입은 색상 배지(EC2·RDS·S3…)로
            구분됩니다.
            <ul className="ml-4 mt-1.5 list-disc space-y-0.5">
              <li>각 행의 <b>토글</b>로 모니터링을 켜고 끕니다. 켜면 해당 리소스에 알람이 생성됩니다.</li>
              <li>여러 개를 선택해 <b>일괄(Bulk)</b>로 켜고 끌 수 있습니다.</li>
              <li><b>Sync</b> 버튼으로 계정/리전 범위를 정해 최신 리소스를 다시 수집합니다.</li>
            </ul>
          </>
        ),
      },
      {
        icon: Bell,
        title: "알람 보기",
        body: (
          <>
            <b>Alarms</b> 화면에서 전체 알람을 상태별로 봅니다. 상태는 <Code>OK</Code> /{" "}
            <Code>ALARM</Code> / <Code>INSUFFICIENT_DATA</Code> / <Code>OFF</Code> 이고, 심각도는{" "}
            <Code>SEV-1</Code>~<Code>SEV-5</Code>로 표시됩니다. 상단바 <b>벨 아이콘</b>을 누르면
            현재 ALARM 항목이 드롭다운으로 떠 바로 해당 리소스로 이동합니다.
          </>
        ),
      },
      {
        icon: Search,
        title: "검색 & 필터",
        body: (
          <>
            상단바 <b>검색창</b>에 리소스 이름을 입력하고 Enter → Resources 화면에서 이름으로
            필터링됩니다. 상단바 <b>고객사/계정/서비스 드롭다운</b>으로 더 좁힐 수 있습니다.
            (드롭다운 고객사 목록은 담당으로 선택한 고객사만 나옵니다.)
          </>
        ),
      },
      {
        icon: Boxes,
        title: "고객사 & 계정 관리",
        body: (
          <>
            <b>Settings</b>에서 고객사를 <b>생성·편집</b>할 수 있습니다(모든 사용자). 고객사 아래에
            AWS 계정을 등록하면 그 계정의 리소스가 수집됩니다. 고객사 <b>삭제는 관리자만</b>
            가능합니다(아래 권한 참고).
          </>
        ),
      },
    ],
  },
  {
    id: "arch",
    label: "아키텍처 & 연동",
    intro: "이 도구가 무엇을, 왜, 어떻게 동작하는지.",
    items: [
      {
        icon: Lightbulb,
        title: "한 줄 요약 — 왜 중앙 스택인가",
        body: (
          <>
            중앙 AWS 계정에 스택 <b>하나</b>를 올려, 여러 고객 AWS 계정의 CloudWatch
            알람을 <b>태그 기반</b>으로 한 곳에서 관리합니다. 고객 계정에는 무거운 리소스
            없이 <b>IAM Role만</b> 두고, 중앙에서 STS AssumeRole로 접근합니다. UI는 중앙
            API 하나만 호출하면 되고, 알람 정책·코드를 중앙에서 일관 관리합니다.
          </>
        ),
      },
      {
        icon: Network,
        title: "구성도 (시스템 구성)",
        body: (
          <Block>{`브라우저
  │ HTTPS
  ▼
AWS Amplify (Next.js SSR)
  · Google 로그인   · /api 프록시(ID 토큰 주입)
  │ Authorization: Bearer <Google ID 토큰>
  ▼
API Gateway (HTTP API) ──[ JWT Authorizer: Google ]
  │
  ▼
api_handler  Lambda
  ├─▶ DynamoDB      고객사·계정·임계값·작업·인벤토리·사용자설정
  ├─▶ CloudWatch    알람 조회 / 생성 / 삭제
  ├─▶ STS AssumeRole ─▶ 고객 AWS 계정 (리소스 조회·알람 CRUD)
  └─▶ SQS FIFO ─▶ sqs_worker Lambda   (대량 작업)

EventBridge Scheduler ─▶ daily_monitor Lambda
     └ 정기: 계정 순회 → 리소스 스캔 → 알람 보정

CloudWatch 알람 발생 ─▶ SNS Topic ─▶ 알림(Slack·이메일·운영팀)`}</Block>
        ),
      },
      {
        icon: Database,
        title: "배포 시 생성되는 리소스 (CloudFormation)",
        body: (
          <>
            스택 하나가 중앙 계정에 다음을 생성합니다:
            <ul className="ml-4 mt-1.5 list-disc space-y-0.5">
              <li><b>Lambda 7</b> — api_handler(API), daily_monitor(정기 동기화), sqs_worker(대량작업), remediation_handler(이벤트 대응) + 초기 셋업/싱크용</li>
              <li><b>DynamoDB 7</b> — Customers, Accounts, ThresholdOverrides, JobStatus, MonitorRunHistory, ResourceInventory, UserPreferences</li>
              <li><b>API Gateway</b> HTTP API + <b>JWT Authorizer</b> + Stage</li>
              <li><b>SQS FIFO</b> + DLQ — 대량 작업 큐(순서·재시도 보장)</li>
              <li><b>SNS 4</b> — 알람·리메디에이션·라이프사이클 알림</li>
              <li><b>EventBridge Scheduler</b> — 정기 동기화 트리거</li>
              <li><b>IAM Role 8</b> — Lambda 실행 권한 + 크로스계정 AssumeRole</li>
            </ul>
          </>
        ),
      },
      {
        icon: Share2,
        title: "크로스 계정 연동 — 왜 / 어떻게",
        body: (
          <>
            고객 계정의 리소스를 읽고 알람을 만들려면 그 계정 권한이 필요합니다. 고객
            계정엔 <b>IAM Role만</b> 배포하고(중앙 계정을 신뢰), 중앙 Lambda가 그 Role을{" "}
            <b>AssumeRole</b>해 접근합니다. 계정 정보(account_id, role)는{" "}
            <Code>AccountsTable</Code>에 등록합니다.
            <Block>{`중앙 계정 (이 스택)               고객 AWS 계정
┌────────────────────┐           ┌──────────────────────────┐
│ api_handler /      │ AssumeRole │ IAM Role (중앙 계정 신뢰) │
│ daily_monitor      │──────────▶ │   · EC2/RDS/ELB… 조회     │
│   Lambda           │           │   · CloudWatch 알람 CRUD  │
└────────────────────┘           └──────────────────────────┘
  ※ 고객 계정엔 Lambda/DB 없음 — IAM Role만(경량 온보딩).`}</Block>
          </>
        ),
      },
      {
        icon: Workflow,
        title: "주요 흐름 (태그 기반)",
        body: (
          <>
            <Block>{`[모니터링 토글 ON]
 UI 토글 → api_handler → (타 계정이면) AssumeRole
   → 리소스에 태그 부여(Monitoring=on, 임계값 태그)
   → CloudWatch PutMetricAlarm + 태그(ManagedBy/Severity)
   → ResourceInventory 기록 → UI 갱신

[정기 동기화 — 보정]
 Scheduler → daily_monitor → 계정 순회·AssumeRole
   → 리소스 태그 스캔 → 알람 상태 비교·보정 → 인벤토리/이력 갱신

[알람 발생 → 알림]
 메트릭 임계값 초과 → CloudWatch ALARM → SNS → 운영팀`}</Block>
            알람의 임계값·심각도·on/off가 모두 <b>리소스 태그</b>로 결정됩니다 — 그래서
            “태그 기반”입니다.
          </>
        ),
      },
    ],
  },
  {
    id: "deploy",
    label: "배포 & 설정 (운영자)",
    intro: "스택을 처음 올리거나 인증을 켜는 사람을 위한 단계입니다.",
    items: [
      {
        icon: FolderGit2,
        title: "코드 받기 (저장소)",
        body: (
          <>
            모든 코드(인프라·백엔드·프론트엔드)는 GitHub 저장소에 있습니다.
            <Block>{`git clone https://github.com/hkjs96/aws-alert-manager.git`}</Block>
            <ul className="ml-4 mt-1.5 list-disc space-y-0.5">
              <li>CloudFormation 템플릿: <Code>infrastructure/backend/template.yaml</Code></li>
              <li>백엔드 배포 스크립트: <Code>.codex/deploy-backend-stack.py</Code></li>
              <li>백엔드 Lambda 코드: <Code>backend/</Code></li>
              <li>프론트엔드(Next.js): <Code>frontend/</Code> — Amplify가 이 저장소 <Code>main</Code> 브랜치에 연결돼 자동 빌드</li>
              <li>운영 문서: <Code>docs/AUTH.md</Code>, <Code>guides/OPERATIONS.md</Code></li>
            </ul>
          </>
        ),
      },
      {
        icon: ListChecks,
        title: "0. 사전 준비",
        body: (
          <>
            <ul className="ml-4 list-disc space-y-0.5">
              <li>대상 AWS 계정 자격증명(SSO 프로파일) + 배포용 S3 버킷</li>
              <li>Google Cloud 프로젝트(OAuth 동의 화면 구성)</li>
              <li>프론트엔드 호스팅: AWS Amplify(Next.js SSR)</li>
            </ul>
          </>
        ),
      },
      {
        icon: Rocket,
        title: "1. 백엔드 스택 배포",
        body: (
          <>
            CloudFormation 스택(Lambda·DynamoDB·API Gateway)을 배포합니다. 코드 변경 후엔 항상{" "}
            <Code>--all-artifacts</Code>로 전체 아티팩트를 올립니다.
            <Block>{`python .codex/deploy-backend-stack.py --all-artifacts`}</Block>
            인증/관리자 값은 환경변수로 전달하며, 미전달 시 이전 값이 유지됩니다.
            <Block>{`GOOGLE_CLIENT_ID=...        # JWT authorizer audience
ALLOWED_EMAILS=a@x.com,b@y.com
ALLOWED_EMAIL_DOMAINS=mz.co.kr
ADMIN_EMAILS=admin@mz.co.kr`}</Block>
          </>
        ),
      },
      {
        icon: KeyRound,
        title: "2. Google OAuth & 인증",
        body: (
          <>
            <ol className="ml-4 list-decimal space-y-0.5">
              <li>Google Cloud Console → OAuth 클라이언트(웹) 생성</li>
              <li>
                승인된 리디렉션 URI에 <b>실제 서빙 도메인</b>(브랜치 접두사 포함) 추가:
                <Block>{`https://<branch>.<appId>.amplifyapp.com/api/auth/callback/google`}</Block>
              </li>
              <li>발급된 Client ID는 백엔드 <Code>GOOGLE_CLIENT_ID</Code>(audience)로 동일하게 사용</li>
              <li>인증은 단계적: <Code>GOOGLE_CLIENT_ID</Code>가 비면 공개, 값이 있으면 강제</li>
            </ol>
          </>
        ),
      },
      {
        icon: Cloud,
        title: "3. 프론트엔드(Amplify) 환경변수",
        body: (
          <>
            Amplify 콘솔 환경변수에 설정합니다. <b>주의:</b> 인증을 켜면{" "}
            <Code>NEXT_PUBLIC_API_BASE_URL</Code>은 <b>비워야</b> 합니다(브라우저가 프록시를
            경유하도록). 서버 전용 <Code>API_GATEWAY_URL</Code>만 둡니다.
            <Block>{`API_GATEWAY_URL=https://<api>.execute-api.<region>.amazonaws.com/<stage>
AUTH_GOOGLE_ID=...        AUTH_GOOGLE_SECRET=...
AUTH_SECRET=$(openssl rand -base64 32)
AUTH_URL=https://<branch>.<appId>.amplifyapp.com
AUTH_TRUST_HOST=true
ALLOWED_EMAILS=...  ALLOWED_EMAIL_DOMAINS=...`}</Block>
            서버 런타임이 값을 읽도록 빌드에서 <Code>.env.production</Code>에 기록합니다
            (<Code>amplify.yml</Code>). 환경변수 변경 후엔 재빌드해야 반영됩니다.
          </>
        ),
      },
      {
        icon: ShieldCheck,
        title: "4. 관리자 권한",
        body: (
          <>
            <Code>ADMIN_EMAILS</Code>(콤마 구분)에 포함된 이메일이 관리자입니다. 관리자만 고객사{" "}
            <b>삭제</b> 버튼이 보이고 실제 삭제가 가능합니다. 비워두면 아무도 삭제할 수 없습니다.
            생성·편집은 모든 로그인 사용자에게 허용됩니다.
          </>
        ),
      },
    ],
  },
  {
    id: "trouble",
    label: "문제 해결 (FAQ)",
    items: [
      {
        icon: SlidersHorizontal,
        title: "화면이 비어 있어요",
        body: <><b>Settings에서 담당 고객사를 체크</b>했는지 확인하세요. 선택이 없으면 모든 화면이 비어 있는 게 정상입니다.</>,
      },
      {
        icon: KeyRound,
        title: "Unauthorized / 로그인이 풀려요",
        body: <>세션 만료일 수 있습니다. 다시 로그인하세요. 그래도 계속되면 운영자에게 인증 설정(도메인/redirect URI)을 문의하세요.</>,
      },
      {
        icon: Wrench,
        title: "첫 응답이 느려요",
        body: <>트래픽이 적으면 서버리스(Lambda) 콜드 스타트로 첫 요청이 1~2초 느릴 수 있습니다. 이후 요청은 빠릅니다.</>,
      },
      {
        icon: Cloud,
        title: "페이지를 찾을 수 없음(404)",
        body: <>접속 주소에 <b>브랜치 접두사</b>(예: <Code>main.</Code>)가 포함됐는지 확인하세요. 접두사 없는 도메인은 서빙되지 않습니다.</>,
      },
    ],
  },
];

export default function HelpPage() {
  const sections = SECTIONS;

  return (
    <main className="min-h-screen bg-surface">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/80 px-4 py-3 backdrop-blur-md">
        <div className="mx-auto flex max-w-3xl items-center justify-between">
          <span className="font-headline text-base font-bold tracking-tight text-slate-900">
            Alarm Manager
          </span>
          <Link
            href="/"
            className="inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-slate-800"
          >
            <ArrowLeft size={14} /> 홈으로
          </Link>
        </div>
      </header>

      <div className="mx-auto max-w-3xl space-y-10 p-8">
      <div>
        <h1 className="text-3xl font-headline font-extrabold tracking-tight text-slate-900">
          사용 가이드
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Alarm Manager 사용·배포·문제해결을 한 곳에 정리했습니다.
        </p>
        {/* 목차 */}
        <nav className="mt-4 flex flex-wrap gap-2">
          {sections.map((s) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50"
            >
              {s.label}
            </a>
          ))}
        </nav>
      </div>

      {sections.map((section) => (
        <section key={section.id} id={section.id} className="scroll-mt-20 space-y-4">
          <div>
            <h2 className="text-xl font-bold text-slate-900">{section.label}</h2>
            {section.intro && <p className="mt-0.5 text-sm text-slate-500">{section.intro}</p>}
          </div>
          <div className="space-y-3">
            {section.items.map((item) => (
              <div
                key={item.title}
                className="flex gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-soft"
              >
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <item.icon size={20} />
                </span>
                <div className="min-w-0">
                  <h3 className="text-base font-semibold text-slate-800">{item.title}</h3>
                  <div className="mt-1 text-sm leading-relaxed text-slate-600">{item.body}</div>
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
      </div>
    </main>
  );
}
