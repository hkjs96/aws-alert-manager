# AWS Monitoring Engine — Project Memory

이 파일은 세션 간에 유지되어야 할 핵심 아키텍처 결정과 프로젝트 상태를 기록한다.

---

## 🏛️ 핵심 아키텍처 결정

- **Harness Engineering (2026-05-13)**: Planner-Generator-Evaluator 구조 도입. `.claude/harness/`에 품질 기준 및 계약 템플릿 위치.
- **Strict TDD (2026-05-13)**: 모든 구현 전 테스트 선행(RED) 및 의도된 실패 보고 강제화.
- **Regression Prevention (2026-05-13)**: 회귀를 "테스트 실패 및 불필요한 기존 코드 파손"으로 재정의. Sprint Contract를 통한 범위 통제 및 diff 감사 원칙 도입.
- **Resilience (2026-05-13)**: 프론트엔드 화이트아웃 방지를 위해 모든 서버 컴포넌트 데이터 페칭에 `try-catch` 및 폴백 적용.

---

## 🛡️ 회귀 방지 및 코드 보존 원칙

1.  **회귀의 정의**: 신규 기능 추가 또는 버그 수정 중, 기존에 잘 동작하던 코드/기능/구조를 불필요하게 변경하거나 파손하여 기존 동작이 망가지는 것.
2.  **보존 우선 원칙**: 기존 코드 베이스는 "이미 검증된 것"으로 간주하며, 명시적인 요구사항 없이 이를 수정하는 행위를 회귀로 본다.
3.  **변경 범위 통제**: 모든 변경은 Sprint Contract에 합의된 파일 목록 내로 한정하며, 범위를 벗어난 수정은 즉시 반려한다.
4.  **diff 감사 원칙**: `verify_all.py`가 출력하는 `git diff` 정보를 바탕으로 Evaluator가 불필요한 변경 여부를 매번 감사한다.

---

## 🚨 절대 깨지면 안 되는 불변 규칙 (Core Invariants)

1.  **알람 매칭 (Backend)**: 알람 이름 문자열 매칭 금지. 반드시 Namespace/MetricName/Dimensions 메타데이터 기반으로 매칭 및 동기화할 것.
2.  **리소스 식별 (Backend)**: ALB/NLB/TG는 Short_ID를 사용하며, AlarmDescription에는 Full_ARN이 저장되어야 함.
3.  **화이트아웃 방지 (Frontend)**: 모든 Server Component의 데이터 페칭은 `try-catch`로 보호되어야 하며, API 실패 시에도 AppShell이 렌더링되어야 함.
4.  **TDD 사이클**: 테스트 코드 없는 구현(Vibe Coding)은 금지되며, 항상 RED 상태를 먼저 확인해야 함.

---

## 📅 주요 마일스톤 및 상태

- [x] 프로젝트 구조 정리 및 문서 통합 완료
- [x] 회귀 방지 및 TDD 시스템 고도화 완료
- [ ] Phase 2 UI 고도화 (진행 예정)
