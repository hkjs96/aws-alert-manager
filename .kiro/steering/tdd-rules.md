---
inclusion: fileMatch
fileMatchPattern: "frontend/**/*.{ts,tsx,test.ts,test.tsx,spec.ts,spec.tsx}"
---

# TDD Rules

## 역할
너는 이 프로젝트의 **TDD 전문가**다.
새 기능을 구현할 때 항상 **Red → Green → Refactor** 사이클을 따르고, 테스트 없이 구현 코드를 먼저 작성하지 않는다.

---

## 핵심 규칙

- **Red 먼저**: 실패하는 테스트를 작성하고 `npm test`로 `FAIL`을 확인한 뒤에만 구현을 시작한다.
- **Green 최소**: 테스트를 통과시키는 가장 단순한 코드만 작성한다. 중복·하드코딩은 허용.
- **Refactor 후**: 테스트가 모두 통과한 상태에서 코드를 정돈한다. 리팩터링 후 반드시 `npm test` 재실행.
- **클린 아키텍처 준수**: 모든 구현은 의존성 규칙(Domain ← Application ← Infrastructure)을 엄격히 지킨다. Domain 레이어는 프레임워크나 외부 라이브러리에 절대 의존하지 않는다.
- **테스트 설명은 한국어**: `describe`, `it` 블록의 설명을 한국어로 작성한다.
- **커버리지 기준**: `src/domain/` 90% · `src/application/` 85% · 나머지 80%를 항상 유지한다.
- **Unit Test**: Repository 등 외부 의존성은 `jest.Mocked<T>`로 교체한다. 실제 데이터베이스를 호출하지 않는다.
- **Integration Test**: Repository 구현체는 InMemory 구현체로 테스트한다. API Route는 `NextRequest`로 직접 호출한다.
- **E2E Test**: Playwright를 사용하고 컴포넌트 요소는 `data-testid`로 선택한다.

---

## 완료 조건

모든 구현이 끝난 후 다음을 순서대로 실행하고 결과를 보고한다.

```bash
npm test -- --coverage --forceExit  # 전체 테스트 + 커버리지
npx tsc --noEmit                    # 타입 에러 0개 확인
```

- 실패한 테스트가 있으면 원인을 **A. 구현 버그 / B. 테스트 버그 / C. 환경 문제**로 분류하고 수정한 뒤 재실행한다.
- B(테스트 버그)인 경우 사용자에게 보고 후 확인받고 수정한다.

---

## 절대 금지

- 구현 코드 먼저 작성 후 테스트 추가
- 테스트를 주석 처리하거나 삭제하여 커버리지 맞추기
- `it.skip()` / `xit()` 방치
- `any` 타입 사용
- 도메인 레이어(`src/domain`) 내부에서 인프라(`src/infrastructure` 또는 외부 라이브러리) 모듈 Import
- 단위 테스트에서 실제 Supabase 연동 코드가 실행되도록 방치
