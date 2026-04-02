# Implementation Plan: TG 알람 LB 타입 분리

## Overview

NLB TG에 ALB 전용 메트릭(`RequestCountPerTarget`, `TGResponseTime`) 알람이 생성되는 버그 수정. `_get_alarm_defs()`에 `resource_tags` 파라미터를 추가하여 `_lb_type` 기반 TG 알람 필터링 구현, 호출부 4곳 업데이트, `_HARDCODED_METRIC_KEYS` 동적화. TDD 레드-그린-리팩터링 사이클 준수 (거버넌스 §8).

## Tasks

- [x] 1. 버그 조건 탐색 테스트 작성 (수정 전)
  - **Property 1: Bug Condition** — NLB TG에 ALB 전용 알람 생성 버그
  - **CRITICAL**: 이 PBT 테스트는 수정 전 코드에서 반드시 FAIL해야 함 — 실패가 버그 존재를 증명
  - **DO NOT** 테스트 실패 시 코드나 테스트를 수정하지 말 것
  - **NOTE**: 이 테스트는 기대 동작을 인코딩함 — 수정 후 PASS하면 버그 해결 확인
  - **GOAL**: 버그를 재현하는 반례(counterexample)를 도출
  - **Scoped PBT Approach**: `resource_type="TG"`, `_lb_type="network"`로 범위 한정, 유효한 TG ARN + NLB ARN 조합 생성
  - 테스트 파일: `tests/test_pbt_tg_alarm_lb_type_split.py`
  - moto mock 환경에서 `create_alarms_for_resource(tg_arn, "TG", {"_lb_type": "network", "_lb_arn": nlb_arn, ...})` 호출
  - 생성된 알람의 메트릭 키 집합 검사:
    - `HealthyHostCount` IN alarm_metrics (기대)
    - `UnHealthyHostCount` IN alarm_metrics (기대)
    - `RequestCountPerTarget` NOT IN alarm_metrics (수정 전 코드에서 FAIL 예상 — 4개 모두 생성됨)
    - `TGResponseTime` NOT IN alarm_metrics (수정 전 코드에서 FAIL 예상)
  - 수정 전 코드에서 실행 → **EXPECTED OUTCOME: FAIL** (버그 존재 증명)
  - 반례 문서화: "`create_alarms_for_resource(nlb_tg_arn, 'TG', {'_lb_type': 'network', ...})`가 4개 알람을 생성하며 `RequestCountPerTarget`과 `TGResponseTime` 포함"
  - 태스크 완료 조건: 테스트 작성, 실행, 실패 문서화 완료
  - _Requirements: 1.1, 1.2, 2.1, 2.4_

- [x] 2. Preservation 속성 테스트 작성 (수정 전)
  - **Property 2: Preservation** — ALB TG 및 비-TG 리소스 알람 동작 유지
  - **IMPORTANT**: 관찰 우선(observation-first) 방법론 준수
  - 테스트 파일: `tests/test_pbt_tg_alarm_lb_type_split.py`
  - 수정 전 코드에서 비-버그 조건 리소스의 동작을 관찰:
    - 관찰: ALB TG(`_lb_type="application"`)에 `create_alarms_for_resource()` 호출 → 4개 알람 생성 (HealthyHostCount, UnHealthyHostCount, RequestCountPerTarget, TGResponseTime)
    - 관찰: EC2에 `_get_alarm_defs("EC2")` 호출 → EC2 알람 정의 반환 (CPU, Memory, Disk, StatusCheckFailed)
    - 관찰: RDS에 `_get_alarm_defs("RDS")` 호출 → RDS 알람 정의 반환 (6개)
    - 관찰: ALB에 `_get_alarm_defs("ALB")` 호출 → ALB 알람 정의 반환 (3개)
    - 관찰: NLB에 `_get_alarm_defs("NLB")` 호출 → NLB 알람 정의 반환 (5개)
  - PBT 작성:
    - ALB TG 속성: `_lb_type="application"` TG에 대해 `create_alarms_for_resource()` 호출 시 4개 알람 생성 확인
    - 비-TG 속성: `resource_type ∈ {EC2, RDS, ALB, NLB}` × 랜덤 resource_id에 대해 `_get_alarm_defs()` 반환값이 기존과 동일한지 검증
  - 수정 전 코드에서 실행 → **EXPECTED OUTCOME: PASS** (기존 동작 기준선 확인)
  - 태스크 완료 조건: 테스트 작성, 실행, 수정 전 코드에서 PASS 확인
  - _Requirements: 3.1, 3.2, 3.3_

- [x] 3. NLB TG 알람 필터링 버그 수정

  - [x] 3.1 `_get_alarm_defs()` 시그니처 확장 및 NLB TG 필터링 구현
    - 파일: `common/alarm_manager.py`
    - `_get_alarm_defs(resource_type: str)` → `_get_alarm_defs(resource_type: str, resource_tags: dict | None = None)` 변경
    - `resource_type == "TG"` AND `resource_tags.get("_lb_type") == "network"` 인 경우: `_TG_ALARMS`에서 `metric`이 `RequestCountPerTarget` 또는 `TGResponseTime`인 항목 제외 → 2개만 반환
    - `resource_tags`가 `None`이거나 `_lb_type != "network"`인 경우: 기존과 동일하게 4개 반환 (하위 호환)
    - _Bug_Condition: isBugCondition(resource_type, resource_tags) where resource_type == "TG" AND resource_tags.get("_lb_type") == "network" AND _get_alarm_defs("TG") returns 4 defs including RequestCountPerTarget, TGResponseTime_
    - _Expected_Behavior: NLB TG → 2개 알람 정의(HealthyHostCount, UnHealthyHostCount)만 반환_
    - _Preservation: resource_tags=None 또는 _lb_type!="network" → 기존 동작 유지_
    - _Requirements: 2.1, 2.4, 3.1, 3.3_

  - [x] 3.2 호출부 업데이트 — `create_alarms_for_resource()`
    - `_get_alarm_defs(resource_type)` → `_get_alarm_defs(resource_type, resource_tags)` 변경
    - _Requirements: 2.1, 2.4_

  - [x] 3.3 호출부 업데이트 — `sync_alarms_for_resource()`
    - `_get_alarm_defs(resource_type)` → `_get_alarm_defs(resource_type, resource_tags)` 변경
    - _Requirements: 2.3_

  - [x] 3.4 호출부 업데이트 — `_create_single_alarm()`
    - `_get_alarm_defs(resource_type)` → `_get_alarm_defs(resource_type, resource_tags)` 변경
    - _Requirements: 2.1_

  - [x] 3.5 호출부 업데이트 — `_recreate_alarm_by_name()`
    - `_get_alarm_defs(resource_type)` → `_get_alarm_defs(resource_type, resource_tags)` 변경
    - _Requirements: 2.3_

  - [x] 3.6 `_HARDCODED_METRIC_KEYS` 동적화
    - NLB TG에서 `_parse_threshold_tags()`가 `RequestCountPerTarget`과 `TGResponseTime`을 동적 메트릭으로 오인하지 않도록 처리
    - 방법: `_parse_threshold_tags()`에서 `_HARDCODED_METRIC_KEYS` 대신 `_get_alarm_defs()` 결과에서 메트릭 키 집합을 동적 추출하는 헬퍼 사용, 또는 `_parse_threshold_tags()`에 `resource_tags` 전달하여 `_get_alarm_defs()` 기반 하드코딩 키 계산
    - NLB TG: hardcoded = `{"HealthyHostCount", "UnHealthyHostCount"}` (2개)
    - ALB TG: hardcoded = `{"HealthyHostCount", "UnHealthyHostCount", "RequestCountPerTarget", "TGResponseTime"}` (4개)
    - _Requirements: 1.4, 2.4_

  - [x] 3.7 버그 조건 탐색 테스트 재실행 — 수정 후 PASS 확인
    - **Property 1: Expected Behavior** — NLB TG에 2개 알람만 생성
    - **IMPORTANT**: 태스크 1의 동일한 테스트를 재실행 — 새 테스트 작성 금지
    - 태스크 1의 테스트가 기대 동작을 인코딩하고 있으므로, PASS하면 버그 해결 확인
    - **EXPECTED OUTCOME: PASS** (버그 수정 확인)
    - _Requirements: 2.1, 2.4_

  - [x] 3.8 Preservation 테스트 재실행 — 수정 후에도 PASS 유지 확인
    - **Property 2: Preservation** — ALB TG 및 비-TG 리소스 알람 동작 유지
    - **IMPORTANT**: 태스크 2의 동일한 테스트를 재실행 — 새 테스트 작성 금지
    - **EXPECTED OUTCOME: PASS** (회귀 없음 확인)
    - _Requirements: 3.1, 3.2, 3.3_

- [x] 4. Checkpoint — 전체 테스트 통과 확인
  - 기존 테스트 + 새 테스트 모두 통과 확인
  - Ensure all tests pass, ask the user if questions arise.
