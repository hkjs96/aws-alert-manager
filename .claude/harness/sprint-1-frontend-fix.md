# Sprint 계약 1: 프론트엔드 화이트아웃(Blank Page) 복구

이 계약은 프론트엔드가 보이지 않는 현상을 해결하기 위한 **Generator**와 **Evaluator** 간의 합의사항이다.

## 📝 Generator 제안 (구현 계획)

### 원인 분석 (Planner 결과)
- `RootLayout`에서 `fetchAlarms()`를 직접 `await`하고 있음.
- `apiFetch`는 API 응답 실패 시 `Error`를 throw함.
- 서버 컴포넌트(Layout)에서 처리되지 않은 에러 발생 시 전체 페이지 렌더링이 중단되어 화이트아웃 발생 가능성 높음.

### 구현 범위
- [ ] `frontend/app/layout.tsx` 수정: 데이터 페칭 로직에 `try-catch` 추가.
- [ ] 에러 발생 시 빈 배열(`[]`)로 폴백하여 앱 셸이 최소한 렌더링되도록 보장.
- [ ] 서버 로그에 에러 메시지 출력 (`console.error`).

### 완료 조건 (Definition of Done)
1. API 서버가 죽어있더라도 앱의 기본 레이아웃(사이드바, 헤더)이 화면에 보여야 함.
2. `fetchAlarms` 실패가 전체 애플리케이션의 크래시로 이어지지 않아야 함.

---

## 🧐 Evaluator 검토 (검증 계획)

### 추가 완료 조건
3. `Toast` 등을 통해 사용자에게 데이터 로드 실패 알림이 가는지 확인 (향후 단계).
4. `RootLayout` 외에 다른 페이지(Dashboard 등)에서도 유사한 패턴의 크래시가 있는지 `grep`으로 확인.

### 테스트 방법
- [ ] 코드 리뷰: `try-catch` 블록의 적절한 위치 확인.
- [ ] `npm run build`를 통한 문법 오류 및 타입 에러 수동 검증.

---

## 🤝 합의
- **Generator**: 동의합니다. 즉시 수정을 시작합니다.
- **Evaluator**: 데이터 안정성이 확보되면 PASS 판정을 내리겠습니다.
