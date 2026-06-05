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

## 6. 리소스 URL 식별자 (토큰)
`resource_id`를 URL path(`/resources/[id]`)나 API path(`/api/resources/{id}/...`)에 넣을 때는
**절대 raw로 넣지 말고** `frontend/lib/resource-id.ts`의 `encodeResourceId()`를 경유하십시오.
ALB/NLB/TG의 `resource_id`는 풀 ARN(`/`·`:` 포함)이라 raw로 넣으면 CloudFront/Next 프록시/
API Gateway가 `%2F`를 `/`로 풀면서 라우팅이 깨집니다(루트 `AGENTS.md` AP-6).

- **링크/네비게이션:** `router.push(\`/resources/${encodeResourceId(res.id)}\`)`.
- **API 호출:** `lib/api-functions.ts`·`lib/server/data.ts`의 resource path 빌더는 이미
  `encodeResourceId`를 적용한다. 새 호출을 추가할 때도 동일하게 경유하십시오.
  직접 `fetch()`를 쓸 때도 path의 `resource_id`는 반드시 `encodeResourceId`로 감싸십시오.
- **상세 페이지:** `params.id`(토큰)를 화면 표시/필터용 원본 id로 복원할 땐
  `decodeResourceId()`를 쓰십시오. `encodeURIComponent`/`decodeURIComponent`로 대체하지 마십시오.
- 토큰은 가역·타입 무관이라 **신규 리소스 타입을 추가해도 별도 처리가 필요 없습니다.**
