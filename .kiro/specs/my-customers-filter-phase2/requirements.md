# My Customers Filter — Phase2 Requirements

> Phase1 (`my-customers-filter`) 의 localStorage 기반 UX 필터를 BE 인증·인가 체계로 대체한다.
> 이 문서는 Phase2 설계 시작 전 참조용 초안이다.

## 배경

Phase1에서는 브라우저 localStorage에 담당 고객사 목록을 저장하는 UX 필터로 구현되었다.
Phase2에서는 다음 두 가지를 달성해야 한다:

1. **관리자가 엔지니어에게 고객사를 할당** (DB 기반, UI 관리 가능)
2. **BE가 JWT claim으로 접근 제어** (보안 경계를 FE가 아닌 BE로 이동)

---

## 용어 정의 (Glossary)

| 용어 | 설명 |
|------|------|
| `engineer` | 이 시스템을 사용하는 MSP 엔지니어. 담당 고객사가 할당됨 |
| `admin` | 엔지니어에게 고객사를 할당할 수 있는 관리자 역할 |
| `CustomerAssignment` | (engineer_id, customer_id) 쌍의 할당 레코드 |
| `JWT claim` | 로그인 시 BE가 발급하는 토큰에 포함된 `owned_customer_ids` 배열 |
| `Phase2_Scope` | JWT claim 기반으로 BE가 직접 필터링하는 접근 제어 범위 |

---

## Requirements

### REQ-1. 사용자 인증 (Authentication)

**WHEN** 사용자가 애플리케이션에 접근하면  
**THE** 시스템은 인증된 사용자만 접근을 허용해야 한다  
**SHALL** 미인증 사용자는 로그인 페이지로 리다이렉트

- 인증 방식: OAuth2 / OIDC (예: AWS Cognito, Azure AD)
- 세션은 JWT Access Token + Refresh Token 으로 관리

### REQ-2. 고객사 할당 관리 (Admin)

**WHEN** 관리자가 엔지니어에게 고객사를 할당하면  
**THE** 시스템은 `CustomerAssignment` 레코드를 DB에 저장해야 한다  
**SHALL** 할당 변경 시 감사 로그(Audit Log)에 기록: (actor, engineer_id, customer_id, action, timestamp)

- Admin UI: Settings → User Management 또는 Customers 페이지 내 "담당자 지정" 기능
- 한 고객사에 여러 엔지니어 할당 가능 (N:M 관계)

### REQ-3. JWT claim 발급

**WHEN** 인증된 사용자가 로그인하면  
**THE** BE는 JWT payload에 `owned_customer_ids: string[]` claim을 포함해야 한다  
**SHALL** `owned_customer_ids`는 DB의 `CustomerAssignment` 기준으로 채워진다

```json
{
  "sub": "engineer-uuid",
  "email": "engineer@company.com",
  "role": "engineer",
  "owned_customer_ids": ["cust-001", "cust-003"],
  "exp": 1234567890
}
```

### REQ-4. BE API 접근 제어

**WHEN** 인증된 사용자가 API를 호출하면  
**THE** BE는 JWT claim의 `owned_customer_ids`를 기준으로 데이터를 필터링해야 한다  
**SHALL** FE가 보내는 `owned_customer_ids` 파라미터는 무시하고 JWT claim만 신뢰

- 엔드포인트 영향 범위: `/api/resources`, `/api/alarms`, `/api/dashboard/*`
- Admin 역할은 모든 고객사 데이터 접근 가능

### REQ-5. FE localStorage 제거

**WHEN** Phase2로 전환되면  
**THE** FE는 `lib/ownedCustomers/localStorageStore.ts` 대신 `apiStore.ts`를 사용해야 한다  
**SHALL** `UserCustomerStore.getOwnedCustomerIds()`는 JWT claim에서 파싱하거나 BE `/api/me/customers` 엔드포인트를 호출

- `createUserCustomerStore()` factory 반환값을 `localStorageStore` → `apiStore`로 교체
- UI/hook 변경 없음 (인터페이스 동일)

### REQ-6. 감사 로그 (Audit Log)

**WHEN** 고객사 할당이 변경되면  
**THE** 시스템은 감사 로그를 기록해야 한다  
**SHALL** 로그에는 최소한 (actor_id, target_engineer_id, customer_id, action, timestamp, ip_address) 포함

---

## DB 스키마 초안

```sql
-- 사용자 테이블
CREATE TABLE users (
  id          UUID PRIMARY KEY,
  email       TEXT UNIQUE NOT NULL,
  role        TEXT NOT NULL CHECK (role IN ('admin', 'engineer')),
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- 고객사 할당 테이블
CREATE TABLE customer_assignments (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id),
  customer_id TEXT NOT NULL,
  assigned_by UUID NOT NULL REFERENCES users(id),
  assigned_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (user_id, customer_id)
);

-- 감사 로그 테이블
CREATE TABLE audit_logs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id    UUID NOT NULL REFERENCES users(id),
  action      TEXT NOT NULL,   -- 'assign_customer' | 'unassign_customer'
  target_id   UUID,            -- 대상 엔지니어
  resource    TEXT,            -- customer_id 등
  metadata    JSONB,
  ip_address  TEXT,
  created_at  TIMESTAMPTZ DEFAULT now()
);
```

---

## Phase2 전환 체크리스트

- [ ] 인증 제공자(Cognito / Azure AD 등) 결정
- [ ] BE 프레임워크 결정 (FastAPI / Express 등)
- [ ] DB 마이그레이션 작성 (users, customer_assignments, audit_logs)
- [ ] JWT 발급 로직 구현 (`owned_customer_ids` claim 포함)
- [ ] API 미들웨어에서 JWT 검증 + 데이터 필터링
- [ ] `apiStore.ts` stub 구현 완성
- [ ] `createUserCustomerStore()` factory 교체
- [ ] Admin UI: 엔지니어별 고객사 할당 화면
- [ ] `localStorage` 관련 코드 제거 (클린업)
- [ ] E2E 테스트: 인증 플로우 + 권한 경계 검증
