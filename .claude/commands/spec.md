# /spec — 기능 스펙 조회/생성

Kiro Specs(`.kiro/specs/`)를 조회하거나 새 스펙을 생성한다.

## 사용법

- `/spec` — 전체 스펙 목록 출력
- `/spec {name}` — 해당 스펙의 requirements.md, design.md, tasks.md 를 읽고 요약

$ARGUMENTS가 비어 있으면 `ls .kiro/specs/`로 전체 목록을 보여준다.
$ARGUMENTS가 있으면 `.kiro/specs/$ARGUMENTS/` 아래의 세 문서를 읽고 핵심 내용을 요약한다.

## 새 스펙 생성

사용자가 새 기능을 요청하면:

1. `.kiro/specs/{feature-name}/` 디렉토리 생성
2. `requirements.md` — EARS 포맷 (`WHEN ... THE ... SHALL ...`), User Story + Acceptance Criteria
3. `design.md` — 설계 결정, 데이터 흐름, 컴포넌트 구조
4. `tasks.md` — 체크박스 계층적 구현 계획 (TDD 단위)

기존 스펙(`aws-monitoring-engine/` 등)의 포맷을 참고하여 동일한 구조로 작성한다.
