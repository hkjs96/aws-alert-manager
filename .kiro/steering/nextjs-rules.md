---
inclusion: fileMatch
fileMatchPattern: "frontend/**/*.{ts,tsx,css}"
---

# Next.js Framework Rules

> 이 프로젝트에서 Next.js(App Router) 코드를 작성할 때 반드시 지켜야 할 룰입니다.
> **Next.js 16 + React 19** 기준으로 작성되었습니다.

---

## 1. 렌더링 전략

### 1-1. Server Component 우선 사용
- 모든 컴포넌트는 **기본적으로 Server Component**로 작성한다.
- `'use client'`는 **상호작용이 반드시 필요한 컴포넌트에만** 선언한다.
- Client Component가 필요한 경우:
  - `useState`, `useEffect`, `useRef` 등 React Hook 사용 시
  - 브라우저 API(`window`, `localStorage` 등) 접근 시
  - 이벤트 핸들러(`onClick`, `onChange` 등) 사용 시

### 1-2. `'use client'` 경계를 최대한 아래로 밀어내기
- 페이지(page.tsx)나 레이아웃(layout.tsx)에 `'use client'`를 선언하지 않는다.
- 상호작용이 필요한 부분만 별도의 Client Component로 분리하여 **leaf 노드에 가깝게** 배치한다.

### 1-3. Streaming & Suspense 활용
- 데이터 페칭이 있는 비동기 Server Component는 `<Suspense>`로 감싸 점진적 렌더링을 구현한다.
- 페이지 전체 로딩이 필요한 경우 `loading.tsx` 파일을 사용한다.
- LCP(Largest Contentful Paint) 요소는 Suspense 바운더리 **바깥**에 배치한다.

### 1-4. 마이그레이션 (Migrations)
- supabase/migrations 폴더에 위치
- 마이그레이션을 수정하거나 삭제하거나 새로 생성할 때는 항상 사용자의 허가 받기

---

## 2. 코드 품질 & 가독성

### 2-1. 알아보기 쉽고 간결한 코드 작성
- 함수와 변수 이름은 **역할이 명확히 드러나도록** 작성한다.
- 불필요한 추상화를 피하고, 코드의 의도가 바로 읽히도록 한다.
- 주석은 **"왜(Why)"**를 설명할 때만 사용하고, **"무엇(What)"**은 코드 자체로 표현한다.
- 매직 넘버는 상수(`lib/constants.ts`)로 추출한다.

### 2-2. TypeScript 엄격 모드 준수
- `strict: true`를 유지하고, `any` 타입 사용을 금지한다.
- 함수의 인자와 반환 타입을 명시한다 (단, 타입 추론이 명확한 경우 반환 타입 생략 가능).
- 인터페이스(`interface`)는 객체 형태 정의에, 타입 별칭(`type`)은 유니온/유틸리티 타입에 사용한다.

### 2-3. 파일 크기 제한 & 분리 원칙
- **하나의 파일이 200줄을 초과하면** 역할에 따라 여러 파일로 분리한다.
- 하나의 파일에는 **하나의 주요 책임**만 부여한다.
- 분리 기준: UI 컴포넌트 vs 비즈니스 로직, 데이터 페칭 vs 데이터 변환, 서버 전용 vs 클라이언트 전용

---

## 3. 데이터 페칭

### 3-1. Server Component에서 데이터 페칭
- **Server Component에서 직접 데이터를 가져온다.** API Route를 거치지 않는다.
- Client Component에서 서버 데이터가 필요한 경우, **Server Component에서 props로 전달**한다.
- Route Handler(`app/api/`)는 **Client Component에서 호출하는 경우에만** 사용한다.

### 3-2. 병렬 데이터 페칭
- 서로 의존성이 없는 데이터는 `Promise.all()` 또는 개별 `<Suspense>`로 **병렬 요청**한다.
- 워터폴(순차 요청)을 만들지 않는다.

### 3-3. 동적 접근(params, searchParams 등)은 필요한 곳까지 내려보내기
- `params`, `searchParams`, `cookies()`, `headers()`를 페이지/레이아웃 최상단에서 `await` 하지 않는다.
- Promise를 필요한 컴포넌트까지 전달하여 `<Suspense>` 안에서 resolve 한다.

---

## 4. 데이터 변경 (Mutation)

### 4-1. Server Action 사용
- 데이터 변경은 **Server Action(`'use server'`)** 을 통해 처리한다.
- 렌더링 중 사이드이펙트(쿠키 삭제, DB 변경 등)를 발생시키지 않는다.
- Server Action 내부에서 반드시 **인증·인가를 재검증**한다.

### 4-2. Form 처리
- 폼 제출은 `<form action={serverAction}>` 패턴을 사용한다.
- 클라이언트 폼 상태는 `useActionState`로 관리한다.
- 서버 사이드 유효성 검사를 반드시 수행한다 (클라이언트 검증은 UX 보조용).

---

## 5. 라우팅 & 네비게이션

### 5-1. Link 컴포넌트 사용
- 페이지 이동에는 **반드시 `<Link>`** 컴포넌트를 사용한다 (`<a>` 직접 사용 금지).
- Prefetch를 불필요하게 비활성화하지 않는다.

### 5-2. Route Group 활용
- 관련 라우트는 **Route Group `(groupName)/`** 으로 묶어 레이아웃을 공유한다.

### 5-3. 에러·로딩 처리
- 각 주요 라우트에 `error.tsx`와 `loading.tsx`를 배치한다.
- 전역 에러 처리를 위해 `app/global-error.tsx`를 생성한다.
- 404 처리를 위해 `app/not-found.tsx`를 생성한다.

---

## 6. 성능 최적화

### 6-1. 이미지 & 폰트
- 이미지는 `next/image`의 `<Image>` 컴포넌트를 사용한다.
- 폰트는 `next/font`를 사용하여 자동 최적화한다.
- 외부 CDN 폰트를 직접 로드하지 않는다.

### 6-2. 번들 크기 관리
- 큰 라이브러리는 `next/dynamic` 또는 `import()`로 지연 로딩한다.
- `'use client'` 파일에서 서버 전용 코드(`server-only`)를 import하지 않는다.

### 6-3. 캐싱 전략
- 변경이 드문 데이터는 캐싱을 적극 활용한다.
- `revalidatePath()`와 `revalidateTag()`로 캐시를 명시적으로 무효화한다.

---

## 7. 보안

### 7-1. 환경 변수
- 클라이언트에서 사용할 환경 변수만 `NEXT_PUBLIC_` 접두사를 붙인다.
- 서버 전용 시크릿은 절대 클라이언트에 노출하지 않는다.
- `.env` 파일은 `.gitignore`에 반드시 포함한다.

### 7-2. 데이터 직렬화 주의
- Server Component에서 Client Component로 전달하는 props에 **민감한 데이터를 포함하지 않는다.**
- DB 레코드 전체가 아닌, **필요한 필드만 포함한 DTO**를 전달한다.

### 7-3. Server Action 보안
- 모든 Server Action 내부에서 **인증(Authentication)과 인가(Authorization)를 재검증**한다.
- 클라이언트 입력은 반드시 서버에서 유효성 검사한다.

---

## 8. 프로젝트 구조 컨벤션

### 8-1. 파일 네이밍
| 유형 | 네이밍 규칙 | 예시 |
|------|-----------|------|
| React 컴포넌트 | PascalCase | `ProductCard.tsx` |
| 유틸리티 / 헬퍼 | camelCase | `formatPrice.ts` |
| 상수 | camelCase 파일 + UPPER_SNAKE_CASE 변수 | `constants.ts` → `FREE_SHIPPING_THRESHOLD` |
| 타입 정의 | PascalCase | `ProductDTO.ts` |
| Hook | `use` 접두사 + camelCase | `useCart.ts` |
| Server Action | camelCase + `Action` 접미사 | `addToCartAction` |

### 8-2. import 순서
1. 외부 라이브러리
2. 내부 모듈 (path alias 사용)
3. 컴포넌트
4. 스타일

### 8-3. Export 규칙
- 컴포넌트는 **named export**를 사용한다 (default export는 page.tsx, layout.tsx 등 Next.js 컨벤션만).
- barrel export(`index.ts`)는 도메인 레이어에서만 사용한다.

---

## 9. 테스트

### 9-1. 테스트 범위
- **도메인 엔티티와 Use Case**는 반드시 단위 테스트를 작성한다.
- Server Action은 인증·유효성 검사 경로를 포함해 통합 테스트로 커버한다.
- UI 컴포넌트는 핵심 인터랙션에 한해 테스트한다.

### 9-2. TDD 사이클 준수
- 새 기능은 **Red → Green → Refactor** 사이클로 개발한다.
- 테스트 설명은 **한국어**로 작성하여 의도를 명확히 한다.

---

## 10. Metadata & SEO

### 10-1. 정적 Metadata
- 각 페이지에 `export const metadata`를 선언하여 title, description을 명시한다.
- 공통 메타데이터는 `layout.tsx`에서 정의하고, 페이지별로 오버라이드한다.

### 10-2. 동적 Metadata
- 동적 라우트(`[id]`)에서는 `generateMetadata()` 함수를 사용한다.

---

## 11. Quick Reference

| 상황 | 사용할 것 |
|------|----------|
| 페이지 간 이동 | `<Link>` from `next/link` |
| 이미지 표시 | `<Image>` from `next/image` |
| 폰트 로딩 | `next/font/google` 또는 `next/font/local` |
| 데이터 페칭 (서버) | Server Component에서 직접 호출 |
| 데이터 페칭 (클라이언트) | Route Handler + `fetch` 또는 `use()` |
| 데이터 변경 | Server Action (`'use server'`) |
| 폼 상태 관리 | `useActionState` |
| 로딩 상태 | `<Suspense>` + `loading.tsx` |
| 에러 처리 | `error.tsx` + `global-error.tsx` |
| 지연 로딩 | `next/dynamic` 또는 `React.lazy()` |
| Metadata / SEO | `export const metadata` 또는 `generateMetadata()` |
