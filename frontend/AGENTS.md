# Frontend Agent Governance (Next.js/TS)

프론트엔드 영역(`frontend/`)에서 작업하는 모든 에이전트는 아래 규칙을 준수해야 합니다.

## 1. 기술 스택
- **Framework:** Next.js (App Router)
- **Language:** TypeScript (Strict Mode)
- **Styling:** Tailwind CSS, Lucide React (Icons)
- **State/Data:** React Query (TanStack Query)

## 2. 컴포넌트 설계 규칙
- **Atomic Design:** 최대한 재사용 가능한 작은 단위로 컴포넌트를 분리하십시오.
- **Client vs Server:** `'use client'` 디렉티브는 인터랙션이 필요한 최소한의 컴포넌트에만 사용하십시오.
- **Accessibility:** 모든 인터랙티브 요소는 적절한 ARIA 속성을 가져야 합니다.

## 3. 코드 스타일
- **Type Safety:** `any` 사용을 금지하며, 인터페이스와 타입을 명확히 정의하십시오.
- **Naming:** 컴포넌트는 `PascalCase`, 함수와 변수는 `camelCase`를 사용하십시오.
- **Formatting:** 프로젝트 내 Prettier/ESLint 설정을 따르십시오.

## 4. 테스트 및 검증
- **Unit Test:** `vitest`를 사용하여 유틸리티 및 개별 컴포넌트를 테스트하십시오.
- **E2E Test:** 중요 유저 시나리오는 `playwright`를 사용하십시오.
- **Type Check:** 코드 제출 전 반드시 `npx tsc --noEmit`을 실행하여 타입 에러가 없는지 확인하십시오.

## 5. API 연통
- 백엔드와의 통신은 `frontend/lib/api/` (또는 유사 경로)에 정의된 공통 클라이언트를 사용하십시오.
- 환경 변수는 `.env.local`을 참조하되, 브라우저 노출이 필요한 경우 `NEXT_PUBLIC_` 접두사를 사용하십시오.
