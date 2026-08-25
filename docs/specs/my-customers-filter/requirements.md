# Requirements Document

## Introduction

MSP 엔지니어 여러 명이 같은 Alarm Manager UI를 공유하게 되면, 각자 담당하지 않는 고객사(AWS Account ID)가 리스트에 함께 노출되어 작업 효율이 떨어지고 실수로 남의 고객사를 건드릴 위험이 있다. 이 기능은 **"내가 담당하는 고객사만 UI에 보이도록 하는 필터링"** 을 제공한다.

본 스펙은 Phase1/Phase2 2단계 전환을 전제로 한다.

- **Phase1 (현재, auth 도입 전)**: localStorage 기반 UX 필터. 사용자가 고객사 페이지에서 체크박스로 자신의 담당 고객사를 선택하면, 비담당 고객사는 UI에 완전히 숨겨진다. **보안 경계가 아니라 UX 편의 기능**이며, 악의적 우회(localStorage 직접 수정)는 막지 않는다.
- **Phase2 (auth 도입 후)**: DB가 권위 소스가 되며, 관리자가 사용자에게 담당 고객사를 할당한다. 백엔드 API가 JWT/세션 기반 claim으로 필터링·검증하며, localStorage 저장소는 완전히 폐기된다. Audit 로그는 Phase2에서 백엔드 레벨로 기록한다.

두 단계는 **동일한 "사용자 → 담당 account_id/customer_id 리스트" 데이터 모양** 위에서 저장소 어댑터만 교체되는 구조로 설계한다.

## Glossary

- **OwnedCustomers**: 현재 사용자가 담당하는 customer_id 집합
- **UserCustomerStore**: "내 담당 고객사" 목록을 읽고 쓰는 저장소 추상 인터페이스. Phase1은 localStorage 구현체, Phase2는 DB 구현체.
- **Customers_Page**: 고객사 관리 페이지 (`/customers`)
- **Global_Filter**: 상단 `GlobalFilterBar`의 Customer/Account/Service 드롭다운
- **Owned_Scope**: 사용자가 담당하는 customer_id에 속한 account_id 집합 (파생값)
- **Phase1_Scope**: FE(Next.js)만을 경계로 한 필터링 범위
- **Phase2_Scope**: BE(API Gateway + Lambda)에서 JWT claim 기반으로 검증하는 필터링 범위

## Requirements

### Requirement 1: 담당 고객사 저장소 추상화

**User Story:** As a frontend developer, I want a single storage interface for "my customers", so that Phase2의 DB 전환 시 UI/필터 로직을 그대로 재사용할 수 있다.

#### Acceptance Criteria

1. THE UserCustomerStore SHALL expose `getOwnedCustomerIds(): Promise<string[]>`, `setOwnedCustomerIds(ids: string[]): Promise<void>`, `toggleOwnedCustomerId(id: string): Promise<string[]>` 메서드를 정의한다.
2. THE UserCustomerStore의 localStorage 구현체 SHALL `userCustomers:{userId}` 키로 저장하고, 인증 전에는 `userId` 자리에 `"guest"` 리터럴을 사용한다.
3. WHEN Phase2 auth가 도입되면, THE UserCustomerStore 구현체 SHALL DB 기반 구현체로 교체되며, localStorage 키는 더 이상 읽지 않는다.
4. THE UserCustomerStore SHALL 동일한 메서드 시그니처를 Phase1/Phase2에서 유지하여, 호출측 컴포넌트/훅은 수정 없이 동작해야 한다.
5. WHEN localStorage가 비어있거나 유효하지 않은 JSON이 저장되어 있을 때, THE UserCustomerStore.getOwnedCustomerIds SHALL 빈 배열을 반환한다.

### Requirement 2: 고객사 페이지의 "담당" 체크박스

**User Story:** As an MSP engineer, I want to check my assigned customers on the customers page, so that I can control which customers appear in my UI.

#### Acceptance Criteria

1. THE Customers_Page SHALL CustomerSection의 각 고객사 행에 "담당(Owned)" 체크박스 컬럼을 렌더한다.
2. WHEN 사용자가 특정 고객사 행의 체크박스를 토글하면, THE Customers_Page SHALL `UserCustomerStore.toggleOwnedCustomerId(customer_id)` 를 호출하고, 상단 Global_Filter의 Customer 드롭다운 옵션이 즉시 갱신된다.
3. THE Customers_Page SHALL "담당" 체크박스 상태를 URL이 아닌 `UserCustomerStore`로부터 로드한다.
4. WHERE 현재 OwnedCustomers가 비어있다면, THE Customers_Page SHALL 페이지 상단에 안내 배너 ("담당 고객사를 선택하면 다른 화면에서 해당 고객사만 표시됩니다")를 표시한다.
5. THE Customers_Page 자체 SHALL 담당 여부와 무관하게 모든 고객사를 표시한다 (다른 화면과 달리 여기서는 숨기지 않는다 — 선택/관리 용도이므로).
6. IF 사용자가 OwnedCustomers에 포함되지 않은 고객사를 삭제하려 해도, THE Customers_Page SHALL Phase1에서는 별도 권한 검사를 하지 않는다 (Phase2에서 BE가 강제).

### Requirement 3: Global_Filter의 담당 고객사 한정

**User Story:** As an MSP engineer, I want the customer dropdown to show only my assigned customers, so that I don't accidentally select someone else's customer.

#### Acceptance Criteria

1. WHEN Global_Filter의 Customer 드롭다운이 렌더링될 때, THE Global_Filter SHALL OwnedCustomers에 포함된 고객사만 옵션으로 표시한다.
2. WHEN OwnedCustomers가 비어있다면, THE Global_Filter SHALL Customer 드롭다운을 비활성화하고 "담당 고객사 없음" placeholder를 표시한다.
3. WHEN URL의 `customer_id` 쿼리 파라미터가 OwnedCustomers에 속하지 않는 값이라면, THE Global_Filter SHALL 해당 파라미터를 URL에서 제거하고 선택을 초기화한다.
4. WHEN 사용자가 Customers_Page에서 담당 고객사 집합을 변경하면, THE Global_Filter SHALL 동일 브라우저 탭 내에서 즉시 옵션을 재계산한다.
5. WHEN 브라우저 탭이 여러 개 열려있고 다른 탭에서 담당 고객사를 변경하면, THE Global_Filter SHALL `storage` 이벤트를 수신하여 현재 탭에서도 옵션을 자동 갱신한다.

### Requirement 4: 데이터 페이지의 담당 범위 필터링

**User Story:** As an MSP engineer, I want dashboards, resources, and alarms to display only data from my assigned customers, so that I can focus on what I own.

#### Acceptance Criteria

1. THE Dashboard_Page, Resource_List_Page, Alarms_Page SHALL 데이터 페칭 시 OwnedCustomers에서 파생된 Owned_Scope를 필터로 적용하여 비담당 데이터를 UI에 노출하지 않는다.
2. WHEN OwnedCustomers가 비어있다면, THE Dashboard_Page/Resource_List_Page/Alarms_Page SHALL 데이터 영역을 "담당 고객사를 먼저 선택하세요" 빈 상태 컴포넌트로 대체한다.
3. WHEN Global_Filter의 Customer 값이 비어있는 상태에서 데이터를 요청할 때, THE Client SHALL 요청 쿼리에 `customer_ids=<owned_ids>` 형태로 다중 customer_id를 포함한다.
4. THE Phase1_Scope에서 필터링은 Next.js Route Handler 또는 Client 측에서 수행되어도 무방하며, 보안 경계가 아님을 설계 문서에 명시한다.
5. THE Phase2_Scope에서 API Gateway + Lambda SHALL JWT claim의 담당 고객사 목록을 신뢰 소스로 삼아 필터링을 강제하며, 클라이언트가 보낸 customer_id가 claim에 없으면 403을 반환한다.

### Requirement 5: Phase2 전환 계약

**User Story:** As a backend developer, I want a clear contract for Phase2 rollout, so that the localStorage-based UX can be swapped for DB-backed access control without UI rework.

#### Acceptance Criteria

1. THE UserCustomerStore 인터페이스 SHALL Phase1과 Phase2에서 동일한 메서드 시그니처를 유지한다.
2. WHEN Phase2 auth가 배포되면, THE UserCustomerStore 구현체 SHALL `GET /api/me/customers` 엔드포인트에서 OwnedCustomers를 읽어온다.
3. THE Phase2 BE SHALL 모든 리소스/알람/대시보드 API에 대해, 요청자의 JWT claim에 포함된 customer_id 목록을 단일 진실 소스(single source of truth)로 사용한다.
4. WHEN Phase2 배포 시점에, THE System SHALL Phase1의 localStorage 키(`userCustomers:guest` 등)를 읽거나 시드하지 않는다 — 관리자가 DB에 직접 할당한다.
5. THE Phase2 BE SHALL 권한 검증에 실패한 요청과 그 claim/resource를 audit 로그에 기록한다.

### Requirement 6: 엣지 케이스

#### Acceptance Criteria

1. WHEN 사용자가 담당으로 선택한 customer_id가 더 이상 존재하지 않는다면(삭제됨), THE UserCustomerStore SHALL 다음 조회 시 해당 id를 자동으로 OwnedCustomers에서 제외한다.
2. WHEN 브라우저에서 localStorage 접근이 실패한다면(프라이빗 모드 등), THE UserCustomerStore SHALL 콘솔 에러 없이 빈 배열을 반환하고, UI는 "담당 고객사 없음" 상태로 동작한다.
3. WHEN URL이 공유되어 OwnedCustomers에 없는 customer_id가 포함된 링크를 열었을 때, THE Frontend SHALL customer_id 파라미터를 제거한 상태로 페이지를 렌더한다.
4. THE Feature SHALL Phase1 단계에서 공유/복사/탈취된 URL을 통한 우회를 보안 문제로 간주하지 않으며, 이는 Phase2 BE 검증으로만 해결한다.
