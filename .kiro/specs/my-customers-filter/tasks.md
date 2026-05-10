# Implementation Plan: 내 담당 고객사 필터

## Overview

본 계획은 Phase1(localStorage UX 필터)만을 대상으로 한다. Phase2(BE JWT claim 기반 접근 제어)는 auth 시스템 도입 시점에 별도 스펙으로 확장한다. 모든 태스크는 TDD(Red → Green → Refactor) 사이클을 따르며, 테스트 가능한 최소 단위로 분할한다.

### 구현 범위

- ✅ Phase1: `UserCustomerStore` 인터페이스 + localStorage 구현체, `useOwnedCustomers` 훅, Customers 페이지 체크박스, GlobalFilterBar 옵션 필터, 데이터 페이지 Owned_Scope 전파
- 🔜 Phase2 (별도 스펙): `/api/me/customers` BE 엔드포인트, JWT claim 검증, DB 스키마, Audit 로그

## Tasks

- [ ] 1. Phase 1 — 저장소 어댑터 구축

  - [ ] 1.1 `UserCustomerStore` 인터페이스 및 상수 정의
    - `frontend/lib/ownedCustomers/store.ts` — interface 정의 (`getOwnedCustomerIds`, `setOwnedCustomerIds`, `toggleOwnedCustomerId`, `subscribe`)
    - `frontend/lib/ownedCustomers/constants.ts` — `STORAGE_KEY_PREFIX = "userCustomers:"`, `GUEST_USER_ID = "guest"`
    - `createUserCustomerStore()` 팩토리 함수 시그니처 정의 (구현은 1.3에서)
    - _Requirements: 1.1, 1.4_

  - [ ] 1.2 `LocalStorageUserCustomerStore` 단위 테스트 작성 (Red)
    - `frontend/lib/ownedCustomers/__tests__/localStorageStore.test.ts`
    - 한국어 `describe`/`it`
    - 테스트 케이스:
      - "빈 localStorage에서 getOwnedCustomerIds는 빈 배열을 반환한다"
      - "잘못된 JSON이 저장된 경우 빈 배열을 반환한다"
      - "setOwnedCustomerIds 후 getOwnedCustomerIds가 동일한 배열을 반환한다"
      - "toggleOwnedCustomerId는 없으면 추가, 있으면 제거한다"
      - "subscribe 리스너는 setOwnedCustomerIds 호출 시 갱신된 값으로 호출된다"
      - "storage 이벤트 발생 시 subscribe 리스너가 호출된다"
      - "typeof window === 'undefined' (SSR) 환경에서 빈 배열을 반환하고 에러를 던지지 않는다"
    - _Requirements: 1.2, 1.5, 6.2_

  - [ ] 1.3 `LocalStorageUserCustomerStore` 구현 (Green)
    - `frontend/lib/ownedCustomers/localStorageStore.ts`
    - SSR 가드 (`typeof window === "undefined"`)
    - try/catch로 `JSON.parse` 실패 시 빈 배열
    - 내부 이벤트 버스로 같은 탭 전파, `window` storage 이벤트로 다른 탭 전파
    - `createUserCustomerStore()` 팩토리에서 이 구현체 반환
    - _Requirements: 1.1, 1.2, 1.5, 6.2_

  - [ ] 1.4 `ApiUserCustomerStore` stub 파일 추가 (Phase2 예약)
    - `frontend/lib/ownedCustomers/apiStore.ts` — 비어있는 class 선언 + `throw new Error("Phase2 only")` 메서드
    - 팩토리는 아직 선택하지 않음 (Phase2에서 feature flag로 활성화)
    - _Requirements: 1.3, 5.1, 5.2_

- [ ] 2. `useOwnedCustomers` 훅

  - [ ] 2.1 훅 단위 테스트 작성 (Red)
    - `frontend/hooks/__tests__/useOwnedCustomers.test.ts`
    - 테스트 케이스:
      - "마운트 시 store.getOwnedCustomerIds 값을 반환한다"
      - "toggleOwned 호출 후 상태가 갱신된다"
      - "isOwned는 주어진 customer_id가 포함되어 있는지 boolean을 반환한다"
      - "언마운트 시 store.subscribe 해제가 호출된다"
    - `jest.Mocked<UserCustomerStore>`로 store 교체
    - _Requirements: 1.4_

  - [ ] 2.2 훅 구현 (Green)
    - `frontend/hooks/useOwnedCustomers.ts`
    - `useSyncExternalStore` 사용 — 전역 상태를 Context 없이 공유
    - `store.subscribe` 등록/해제
    - `toggleOwned`, `isOwned` 헬퍼 노출
    - _Requirements: 1.4, 3.4_

- [ ] 3. Customers 페이지 — 담당 체크박스

  - [ ] 3.1 `CustomerSection` 체크박스 컬럼 통합 테스트 작성 (Red)
    - `frontend/components/settings/__tests__/CustomerSection.test.tsx`
    - 테스트 케이스:
      - "담당 체크박스를 토글하면 useOwnedCustomers.toggleOwned가 호출된다"
      - "OwnedCustomers에 포함된 고객사 행의 체크박스가 체크된 상태로 렌더된다"
      - "OwnedCustomers가 비어있을 때 안내 배너가 표시된다"
    - `useOwnedCustomers` 훅을 mock
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ] 3.2 `CustomerSection` 체크박스 컬럼 구현 (Green)
    - 기존 `frontend/components/settings/CustomerSection.tsx` 수정
    - 테이블 헤더에 "담당" 컬럼 추가, 각 행에 체크박스
    - `useOwnedCustomers()` 구독
    - OwnedCustomers 빈 상태 배너
    - 200줄 초과 시 `CustomerOwnedBanner.tsx`로 분리
    - _Requirements: 2.1, 2.2, 2.4, 2.5_

- [ ] 4. GlobalFilterBar — 담당 고객사 한정

  - [ ] 4.1 필터 옵션 제한 통합 테스트 작성 (Red)
    - `frontend/components/layout/__tests__/GlobalFilterBar.test.tsx`에 케이스 추가
    - 테스트 케이스:
      - "OwnedCustomers에 포함된 고객사만 Customer 드롭다운에 나타난다"
      - "OwnedCustomers가 비어있으면 Customer 드롭다운이 disabled되고 placeholder가 '담당 고객사 없음'이다"
      - "URL에 OwnedCustomers에 없는 customer_id가 있으면 router.replace로 파라미터를 제거한다"
      - "다른 탭에서 담당 고객사가 변경되면 현재 탭의 옵션이 갱신된다 (storage 이벤트)"
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [ ] 4.2 필터 옵션 제한 구현 (Green)
    - `frontend/components/layout/GlobalFilterBar.tsx` 수정
    - `const { ownedCustomerIds } = useOwnedCustomers();`
    - 옵션 계산 시 교집합, URL 검증 로직 `useEffect` 추가
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 6.3_

- [ ] 5. 데이터 페이지 — Owned_Scope 전파

  - [ ] 5.1 `OwnedEmptyState` 공통 컴포넌트 테스트 및 구현
    - `frontend/components/shared/OwnedEmptyState.tsx` + 테스트
    - "담당 고객사를 먼저 선택하세요" 메시지, 고객사 페이지 링크 버튼
    - _Requirements: 4.2_

  - [ ] 5.2 `buildFilterParams` 에 owned_customer_ids 파라미터 지원 (Red → Green)
    - `frontend/lib/filterParams.ts` 수정 + 테스트
    - `customer_id`가 비어있고 `owned_customer_ids`가 비어있지 않을 때만 쿼리에 `owned_customer_ids=cust-a,cust-b` 포함
    - 두 파라미터 동시 지정 시 `customer_id` 우선
    - _Requirements: 4.3_

  - [ ] 5.3 Dashboard/Resources/Alarms Client 컴포넌트에서 Owned_Scope 전달
    - 각 페이지의 최상위 Client 컴포넌트에서 `useOwnedCustomers` 구독
    - 데이터 페칭 호출 시 `owned_customer_ids` 포함
    - OwnedCustomers 빈 배열이면 `OwnedEmptyState` 렌더
    - 통합 테스트: "OwnedCustomers 비어있을 때 API 호출이 발생하지 않고 빈 상태가 렌더된다"
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ] 5.4 Mock API Route Handler들에 `owned_customer_ids` 필터 로직 추가
    - `frontend/app/api/resources/route.ts`, `frontend/app/api/alarms/route.ts`, `frontend/app/api/dashboard/recent-alarms/route.ts` 수정
    - 쿼리 파라미터 파싱 후 mock-store 결과 필터링
    - **명시적 주석**: "⚠️ Phase1: UX 필터. 실제 접근 제어는 Phase2 BE에서 JWT claim으로 수행"
    - _Requirements: 4.4_

- [ ] 6. E2E 및 문서화

  - [ ] 6.1 Playwright E2E 시나리오
    - `frontend/e2e/my-customers-filter.spec.ts`
    - 시나리오 A: 고객사 페이지에서 A, B 체크 → 리소스 페이지 진입 시 C/D/E 리소스 안 보임
    - 시나리오 B: 담당 0개 상태에서 대시보드 진입 → OwnedEmptyState 렌더
    - 시나리오 C: 탭 1에서 담당 해제 → 탭 2의 GlobalFilterBar 옵션 자동 제거 (storage 이벤트)
    - _Requirements: 3.4, 3.5, 4.1, 4.2_

  - [ ] 6.2 README / HOW_DOES_THIS_WORK.md 업데이트
    - `frontend/HOW_DOES_THIS_WORK.md` — "내 담당 고객사 필터" 섹션 추가
    - Phase1 한계 명시: "localStorage 기반, 보안 경계 아님, Phase2 BE 검증 예정"
    - Phase2 전환 체크리스트 요약 (design.md 마지막 섹션 링크)
    - _Requirements: 6.4_

- [ ] 7. Phase2 전환 준비 (문서만, 구현 X)

  - [ ] 7.1 Phase2 별도 스펙 폴더 플레이스홀더 생성
    - `.kiro/specs/my-customers-filter-phase2/` — `requirements.md`에 BE 엔드포인트, DB 스키마, JWT claim, Audit 로그 요구사항 초안만
    - 본 스펙이 Phase1 범위로 명확히 종료됨을 표시
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

## 완료 조건

```bash
cd frontend
npm test -- --coverage --forceExit     # 전체 테스트 + 커버리지 (lib/ownedCustomers 90%+)
npx tsc --noEmit                       # 타입 에러 0
npx playwright test                    # E2E (6.1)
```

실패 시 A. 구현 버그 / B. 테스트 버그 / C. 환경 문제로 분류 후 수정.
