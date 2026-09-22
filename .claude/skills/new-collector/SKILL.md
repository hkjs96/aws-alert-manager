---
name: new-collector
description: AWS 리소스 타입을 백엔드 모니터링에 추가하거나 기존 타입의 정의를 바꿀 때 따르는 체크리스트. backend/common/resource_types/ 아래 스펙 파일을 새로 만들거나 기존 SPEC의 alarm_defs·display·defaults·lifecycle·rgt_filters·identity를 수정할 때, backend/common/collectors/ 수집기 모듈을 추가·수정할 때, CloudTrail 생명주기 이벤트나 새 알람 정의를 추가할 때, 새 리소스 타입을 프론트엔드에 노출할 때 사용한다. 스펙/수집기 인터페이스, 파생되므로 손대면 안 되는 맵, SRE 골든 시그널 기준 메트릭 선정, 단위 환산, IAM 권한, 온보딩 템플릿 3곳 동기화를 다룬다.
---

# 리소스 타입 온보딩

체크리스트 본문은 이 파일에 없다. **SSOT를 읽어라.**

## 읽을 순서

1. `docs/RESOURCE-ONBOARDING.md` — 전체 체크리스트 (SSOT)
2. `docs/ALARM-RULES.md` §6-1 (디멘션), §9-1 (ARN→ID), §10 (TreatMissingData), §13 (Severity)
3. 루트 `AGENTS.md` §5 — 안티패턴 전체 목록 (특히 AP-8·AP-18·AP-19)
4. `backend/common/CLAUDE.md` — 경로와 테스트 명령

## 작업 후

- `docs/RESOURCE-ONBOARDING.md`의 IAM 체크 섹션은 건너뛰지 않는다 — 단위 테스트가 잡지 못하는 유일한 계층이다.
- 배포가 따라오면 `premortem-deploy` 스킬의 점검을 먼저 통과시킨다.
- 검증: `cd backend && pytest tests/ -x -q --tb=short`
