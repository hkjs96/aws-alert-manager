# Frontend Claude Guide

These rules apply to `frontend/**/*.{ts,tsx,css}`. The shared root
`../AGENTS.md` rules and the root `../CLAUDE.md` guide also apply.

## Frontend API Contract Rules

When a frontend change touches API data:

- Check `docs/API-CONTRACT.md` before changing fetch code or component props.
- Distinguish backend-supported resources from frontend-active resources.
  Backend-wide type contracts use `SUPPORTED_RESOURCE_TYPES`; UI filters,
  settings, and primary workflows currently use
  `FRONTEND_INTEGRATION_RESOURCE_TYPES`.
- Keep API JSON fields as `snake_case` until an explicit frontend DTO mapping is
  created.
- Keep UI option DTOs local and named clearly. For example, `{id, name,
  customerId}` must be mapped from `{account_id, name, customer_id}` in one
  place.
- Update `frontend/types/index.ts` or `frontend/types/api.ts` in the same change
  as any API contract change.
- Update `frontend/lib/server/data.ts` fallback objects with the same keys as
  the API contract.
- Dashboard, list, and settings Server Components must catch backend fetch
  failures and render empty or zero-state fallback data.
- Do not use `useSearchParams()` in components rendered from the root layout
  unless the Suspense/CSR bailout behavior is explicitly tested in production
  SSR.

## Next.js Rules

- Default to Server Components. Add `"use client"` only at interaction leaves.
- Do not put `"use client"` in `page.tsx` or `layout.tsx`.
- Fetch initial page data in Server Components through
  `frontend/lib/server/data.ts`.
- Client Components should use `frontend/lib/api-functions.ts` or local route
  handlers.
- Parallelize independent page data with `Promise.all()`.
- Keep API failure handling explicit. SSR pages should not crash for routine
  backend failures.
- Do not collapse every fetch failure into one "connection failed" message.
  Distinguish HTTP error responses (surface the status/backend `code`) from
  network failures, and keep "request failed" separate from a job/resource whose
  own status is `failed`. See anti-patterns AP-16. A generic message here hid a
  real backend 500 (`GET /jobs/{id}` Decimal serialization, AP-17).

## Next.js Framework Rules (병합: 구 .kiro/steering/nextjs-rules.md)

- Streaming: 데이터 페칭이 있는 비동기 Server Component는 `<Suspense>`로 감싸 점진적
  렌더링하고, LCP 요소는 Suspense 바운더리 바깥에 둔다. 주요 라우트에는
  `error.tsx`/`loading.tsx`를 배치한다.
- `params`/`searchParams`/`cookies()`/`headers()`는 페이지 최상단에서 `await`하지 말고
  필요한 컴포넌트까지 Promise로 내려보내 `<Suspense>` 안에서 resolve한다.
- 데이터 변경은 Server Action(`'use server'`)을 우선 사용하고, 내부에서 인증·인가와
  입력 유효성 검사를 재검증한다. 렌더링 중 사이드이펙트 금지.
- 하나의 파일이 200줄을 초과하면 역할별로 분리한다 (UI vs 로직, 페칭 vs 변환, 서버 vs 클라).
- 이미지는 `next/image`, 폰트는 `next/font` 사용. **외부 CDN 폰트 직접 로드 금지**
  (`globals.css`의 `@import url(fonts.googleapis.com…)`는 이 규칙 위반으로 개선 대상).
- 큰 라이브러리/모달류는 `next/dynamic` 또는 `import()`로 지연 로딩한다.
- 변경이 드문 데이터는 캐싱을 활용하고 `revalidatePath()`/`revalidateTag()`로 명시적 무효화한다.
- 페이지 이동은 `<Link>`만 사용 (`<a>` 직접 사용 금지).
- 네이밍: 컴포넌트 PascalCase, 유틸 camelCase, 상수 UPPER_SNAKE_CASE(`lib/constants.ts`),
  훅 `use*`, Server Action `*Action`. import 순서: 외부 → 내부 모듈 → 컴포넌트 → 스타일.
- 각 페이지에 `export const metadata`(동적 라우트는 `generateMetadata()`)를 선언한다.

## 새 UI 기능 착수 워크플로 (병합: 구 .kiro/steering/frontend-ruels.md)

UI 이미지나 새로운 프론트엔드 기능 요구사항이 주어지면 바로 구현하지 말고:

1. **분해 (Deconstruction):** UI를 컴포넌트 계층 구조로 쪼개고, 재사용 공통 컴포넌트와
   도메인 종속 컴포넌트를 구분해 설명한다.
2. **역질문 (Questioning):** 상태의 종류(전역/지역/서버), 데이터 페칭 위치와 로딩/에러 처리,
   인터랙션·엣지 케이스가 모호하면 사용자에게 질문 리스트를 제시한다.
3. **사양 확정 (Spec Generation):** 의사결정 완료 후에만 `docs/specs/` 스펙 문서 생성을
   제안하고, 태스크는 TDD 가능한 최소 단위로 나눈다.

## TypeScript Rules

- `strict: true` is required.
- Do not introduce `any`.
- Prefer named exports except for Next.js `page.tsx` and `layout.tsx` default
  exports.
- Keep component props narrow. Do not pass full backend records when a smaller
  DTO is enough.
- Extract shared constants to `frontend/lib/constants.ts`.

## Security Rules

- Do not expose server-only secrets with `NEXT_PUBLIC_`.
- Client props must not include credentials, role secrets, API keys, or raw
  sensitive backend records.
- Validate user-controlled payloads before sending them to backend mutation
  endpoints.

## Verification

Run these when the environment allows child processes:

```bash
npx tsc --noEmit
npm test
```

If a command fails, classify the cause as implementation bug, test bug, or local
environment issue.
