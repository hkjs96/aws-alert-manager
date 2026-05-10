# Frontend — Claude Guide

`frontend/**/*.{ts,tsx,css}` 작업 시 적용되는 규칙.
루트의 [`../CLAUDE.md`](../CLAUDE.md)는 그대로 유효하고, 아래 프론트엔드 전용 규칙이 추가된다.

## 적용 규칙 (import)

- Next.js 16 + React 19 프레임워크 규칙: @../.kiro/steering/nextjs-rules.md
- TDD 규칙 (Red → Green → Refactor, 커버리지 기준): @../.kiro/steering/tdd-rules.md
- 프론트엔드 아키텍처 작업 원칙 (이미 루트에서 로드됨): @../.kiro/steering/frontend-ruels.md

## 핵심 체크리스트

### 설계 3단계 절대 규칙 (frontend-ruels.md)

UI 이미지나 새 기능 요구사항이 주어졌을 때 **절대 바로 구현 코드를 작성하지 않는다.**

1. **분석 및 분해**: 컴포넌트 계층 구조로 쪼개기. 재사용 공통 컴포넌트 vs 도메인 컴포넌트 구분.
2. **역질문**: 상태 관리(global/local/server), API·데이터 흐름(로딩/에러), 사용자 인터랙션/엣지 케이스에 대해 사용자에게 확인.
3. **사양 확정**: 의사결정 완료 후에만 `requirements.md` / `design.md` / `tasks.md` 생성 제안. 모든 태스크는 TDD 기준 최소 단위로 분할.

### Next.js 렌더링 전략

- 기본은 **Server Component**. `'use client'`는 상호작용이 필요한 leaf에만.
- `page.tsx` / `layout.tsx`에 `'use client'` 절대 금지.
- 데이터 페칭은 Server Component에서 직접. API Route는 Client Component 호출용으로만.
- 병렬 페칭: `Promise.all()` 또는 개별 `<Suspense>`. 워터폴 금지.
- `params`/`searchParams`/`cookies()`/`headers()`는 최상단에서 `await`하지 않고 필요한 컴포넌트까지 내려보낸다.

### TypeScript & 코드 품질

- `strict: true`, `any` 금지.
- 파일 200줄 초과 시 역할별로 분리.
- 매직 넘버는 `lib/constants.ts`로 추출.
- 컴포넌트 named export (예외: `page.tsx`, `layout.tsx` 등 Next.js 컨벤션 default export).

### 보안

- 서버 전용 시크릿에 `NEXT_PUBLIC_` 접두사 금지.
- Client Component props에 DB 레코드 전체 전달 금지 — 필요한 필드만 DTO로.
- Server Action 내부에서 인증·인가·유효성 재검증 필수.

### TDD

- **Red 먼저**: `npm test`로 FAIL 확인 후에만 구현 시작.
- 테스트 설명은 **한국어** (`describe`, `it`).
- 커버리지: `src/domain/` 90% · `src/application/` 85% · 나머지 80%.
- Unit: `jest.Mocked<T>`로 외부 의존성 교체 (실제 DB 호출 금지).
- Integration: Repository는 InMemory 구현체, API Route는 `NextRequest`로 직접.
- E2E: Playwright + `data-testid`.
- 도메인 레이어(`src/domain`)에서 인프라/외부 라이브러리 import 금지 (Clean Architecture 의존성 규칙).

### 완료 조건

```bash
npm test -- --coverage --forceExit
npx tsc --noEmit
```

실패 시 원인을 **A. 구현 버그 / B. 테스트 버그 / C. 환경 문제**로 분류. B는 사용자에게 보고 후 수정.

### 절대 금지

- 테스트 없이 구현 코드 먼저 작성
- `it.skip()` / `xit()` 방치
- 테스트 주석/삭제로 커버리지 맞추기
- `any` 타입
- `page.tsx`/`layout.tsx`에 `'use client'`
- 민감 데이터 클라이언트 노출
- Supabase 마이그레이션(`supabase/migrations/`) 수정/삭제/생성은 반드시 사용자 허가 후
