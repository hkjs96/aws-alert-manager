# AWS Monitoring Engine — Claude Guide

이 파일은 Claude가 작업을 수행할 때 참고하는 **마스터 가이드**다. 
Anthropic의 **Harness & Context Engineering** 원칙과 **Strict TDD**, 그리고 강력한 **회귀 방지(Regression Prevention)**를 준수한다.

---

## 🛠️ 하네스 엔지니어링 (Harness Engineering)

1. **Planner**: 요청을 최소 단위로 분해하고, 변경 범위가 명시된 **Sprint Contract**를 작성한다.
2. **Generator**: 계약된 범위 내에서만 **RED-GREEN-REFACTOR** 사이클을 수행한다.
3. **Evaluator**: 자동화 훅과 `git diff` 감사를 통해 품질 및 **회귀 방지**를 검증한다.

---

## 🛡️ 회귀 방지 원칙 (Regression Prevention)

*   **정의**: 회귀는 테스트 실패뿐 아니라, 기존의 동작/구조를 불필요하게 파손하는 모든 행위를 의미한다.
*   **보존 우선**: 기존에 잘 동작하는 코드를 보존하는 것이 기본값이다. 
*   **범위 통제**: 스프린트 계약에 명시되지 않은 파일/동작 변경은 절대 금지한다.
*   **최소 리팩터링**: 리팩터링은 요구사항 해결에 필요한 최소 범위로 제한한다.
*   **Diff 감사**: 모든 변경 완료 후 Evaluator는 `git diff --name-only` 및 `--stat`를 확인하여 범위를 감사한다.

---

## 🚀 Strict TDD 워크플로

1.  **RED**: 구현 전 테스트 수정 → **의도된 실패(FAIL)** 보고.
2.  **GREEN**: 테스트 통과를 위한 **최소한의 코드** 작성.
3.  **REFACTOR**: 구조 개선 및 회귀 검증(Full Suite) 수행.
4.  **Verify & Commit**: `python scripts/verify_all.py` 통과 후 커밋.

---

## 🧠 컨텍스트 엔지니어링 (Context Engineering)

- **경량 식별자**: 이 파일은 200줄 이하 유지. 상세 내용은 `docs/` 및 `guides/` 참조.
- **적시 로드 (JIT)**: 필요한 파일만 골라 읽어 주의 예산(Attention Budget) 보존.
- **압축 (Compaction)**: 마일스톤 달성 시 `/compact` 수행.

---

## 📋 핵심 규칙 (Must)
- **보안**: 하드코딩 시크릿 절대 금지.
- **Python**: `boto3` lru_cache 싱글턴 필수.
- **TDD**: 'Vibe Coding'(테스트 없는 구현) 절대 금지.
- **계약 위반**: 계약 범위 외 파일 수정 발견 시 즉시 FAIL 처리.
