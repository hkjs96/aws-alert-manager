# frontend/ — Alarm Manager 웹 앱 작동 방식

> AI 에이전트 또는 새 팀원이 프론트엔드 코드베이스를 빠르게 이해하기 위한 참조 문서.

## 기술 스택

- Next.js 16 (App Router) + React 19
- TypeScript (strict mode)
- Tailwind CSS
- Vitest + Testing Library (테스트)
- Lucide React (아이콘)

## 디렉토리 구조

```
frontend/
├── app/                    # Next.js App Router 라우트
│   ├── layout.tsx          # 루트 레이아웃 (AppShell + ToastProvider)
│   ├── page.tsx            # / → /dashboard 리다이렉트
│   ├── dashboard/          # 대시보드 (통계 카드 + 최근 알람)
│   ├── resources/          # 리소스 목록 + [id] 상세
│   ├── alarms/             # 알람 목록
│   ├── settings/           # 고객사/어카운트/임계치 설정
│   └── api/                # Route Handlers (Client Component용)
├── components/
│   ├── layout/             # AppShell, Sidebar, TopBar, GlobalFilterBar
│   ├── dashboard/          # StatCardGrid, RecentAlarmsTable
│   ├── resources/          # ResourceTable, AlarmConfigTable, 모니터링 토글 등
│   ├── alarms/             # AlarmTable, AlarmSummaryCards
│   ├── settings/           # CustomerSection, AccountSection, ThresholdSection
│   └── shared/             # 공통 UI (Toast, Pagination, SeverityBadge 등)
├── hooks/                  # 커스텀 훅 (useMonitoringToggle 등)
├── lib/                    # 유틸리티 (API 클라이언트, mock 데이터, 필터 등)
└── types/                  # TypeScript 타입 정의
```

## 핵심 아키텍처 패턴

### 렌더링 전략
- 모든 page.tsx, layout.tsx는 Server Component
- 상호작용이 필요한 부분만 별도 Client Component로 분리 (leaf 노드)
- 각 라우트에 error.tsx + loading.tsx 배치

### 데이터 흐름
```
[Server Component page.tsx]
  → Server에서 데이터 fetch (또는 mock-data)
  → props로 Client Component에 전달

[Client Component]
  → 사용자 인터랙션 처리
  → Route Handler (app/api/) 호출로 mutation
```

### 글로벌 필터
- TopBar의 GlobalFilterBar에서 고객사/어카운트/리전 선택
- URL searchParams로 필터 상태 관리
- 모든 API 호출에 필터 파라미터 전달

### API 클라이언트 (`lib/api.ts`)
- `apiFetch<T>()` — 타입 안전한 fetch 래퍼
- `ApiError` 클래스로 에러 구조화 (status, code, message)
- `buildFilterParams()` — 글로벌 필터 → URLSearchParams 변환

## 주요 페이지별 동작

### Dashboard (`/dashboard`)
- StatCardGrid: 모니터링 리소스 수, 활성 알람, 미모니터링, 어카운트 수
- RecentAlarmsTable: 최근 알람 이벤트 (severity 뱃지 포함)

### Resources (`/resources`)
- ResourceTable: 리소스 목록 (필터/검색/페이지네이션)
- ResourceDetailClient (`/resources/[id]`): 리소스 상세 + 알람 설정
  - AlarmConfigTable: 메트릭별 알람 설정 (임계치 편집, 활성화/비활성화)
  - EnableModal/DisableModal: 모니터링 토글 확인 다이얼로그
  - CustomMetricForm: 동적 알람 추가

### Alarms (`/alarms`)
- AlarmSummaryCards: 상태별 알람 수 요약
- AlarmTable: 전체 알람 목록 (상태 필터링)

### Settings (`/settings`)
- CustomerSection: 고객사 CRUD
- AccountSection: AWS 어카운트 관리 (연결 테스트)
- ThresholdSection: 기본 임계치 설정

## 공통 컴포넌트 (`components/shared/`)

| 컴포넌트 | 역할 |
|---------|------|
| Toast / ToastProvider | 전역 토스트 알림 |
| SeverityBadge | SEV-1~5 등급 뱃지 |
| SourceBadge | System/Customer/Custom 소스 뱃지 |
| Pagination | 페이지네이션 UI |
| ConfirmDialog | 확인 다이얼로그 |
| LoadingButton | 로딩 상태 버튼 |
| Skeleton | 로딩 스켈레톤 |
| ErrorPanel | 에러 표시 패널 |

## 현재 상태 (Mock 기반)

- `lib/mock-data.ts`에서 모든 데이터를 mock으로 제공
- `lib/mock-delay.ts`로 네트워크 지연 시뮬레이션
- 실제 백엔드 API 연동은 Phase2에서 진행 예정
- Route Handlers (`app/api/`)는 mock 데이터 반환
