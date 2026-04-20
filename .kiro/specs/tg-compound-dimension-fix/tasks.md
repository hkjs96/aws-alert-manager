# Implementation Plan: TG 복합 디멘션 수정

## Overview

TG 알람의 `TargetGroup` 단일 디멘션 → `TargetGroup` + `LoadBalancer` 복합 디멘션 수정, NLB TG namespace 동적 결정, 레거시 `[ELB]` TG 알람 정리. TDD 레드-그린-리팩터링 사이클 준수.

## Tasks

- [x] 1. 버그 조건 탐색 테스트 작성 (수정 전)
  - **Property 1: Bug Condition** — TG 알람 단일 디멘션 버그
  - **CRITICAL**: 이 PBT 테스트는 수정 전 코드에서 반드시 FAIL해야 함 — 실패가 버그 존재를 증명
  - **DO NOT** 테스트 실패 시 코드나 테스트를 수정하지 말 것
  - **NOTE**: 이 테스트는 기대 동작을 인코딩함 — 수정 후 PASS하면 버그 해결 확인
  - **GOAL**: 버그를 재현하는 반례(counterexample)를 도출
  - **Scoped PBT Approach**: TG 리소스(`resource_type="TG"`)에 대해 유효한 TG ARN + LB ARN 조합으로 범위 한정
  - 테스트 파일: `tests/test_pbt_tg_compound_dimension.py`
  - `_create_standard_alarm()` 호출 후 `put_metric_alarm`에 전달된 Dimensions 검사:
    - `TargetGroup` 디멘션 존재 확인
    - `LoadBalancer` 디멘션 존재 확인 (수정 전 코드에서 FAIL 예상)
    - `len(dimensions) >= 2` 확인
  - NLB TG에 대해 namespace가 `AWS/NetworkELB`인지 확인 (수정 전 코드에서 FAIL 예상 — `AWS/ApplicationELB` 하드코딩)
  - 수정 전 코드에서 실행 → **EXPECTED OUTCOME: FAIL** (버그 존재 증명)
  - 반례 문서화: "TG 알람 Dimensions에 LoadBalancer 누락", "NLB TG namespace가 AWS/ApplicationELB로 잘못 설정"
  - 태스크 완료 조건: 테스트 작성, 실행, 실패 문서화 완료
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Preservation 속성 테스트 작성 (수정 전)
  - **Property 2: Preservation** — 비TG 리소스 디멘션 불변
  - **IMPORTANT**: 관찰 우선(observation-first) 방법론 준수
  - 테스트 파일: `tests/test_pbt_tg_compound_dimension.py`
  - 수정 전 코드에서 비TG 리소스의 동작을 관찰:
    - 관찰: ALB ARN으로 `_create_standard_alarm()` 호출 → `LoadBalancer` 단일 디멘션, namespace `AWS/ApplicationELB`
    - 관찰: NLB ARN으로 `_create_standard_alarm()` 호출 → `LoadBalancer` 단일 디멘션, namespace `AWS/NetworkELB`
    - 관찰: EC2 `_create_standard_alarm()` 호출 → `InstanceId` 단일 디멘션
    - 관찰: RDS `_create_standard_alarm()` 호출 → `DBInstanceIdentifier` 단일 디멘션
  - PBT 작성: `resource_type ∈ {ALB, NLB, EC2, RDS}` × 랜덤 resource_id에 대해 `_create_standard_alarm()` 호출 시 디멘션이 기존 로직과 동일한지 검증
  - 수정 전 코드에서 실행 → **EXPECTED OUTCOME: PASS** (기존 동작 기준선 확인)
  - 태스크 완료 조건: 테스트 작성, 실행, 수정 전 코드에서 PASS 확인
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 3. 버그 수정 구현

  - [x] 3.1 `_build_dimensions()` 헬퍼 추가 및 `_resolve_tg_namespace()` 헬퍼 추가
    - 파일: `common/alarm_manager.py`
    - `_build_dimensions(alarm_def, resource_id, resource_type, resource_tags)` → `list[dict]`:
      - `resource_type == "TG"`: `TargetGroup` + `LoadBalancer` 복합 디멘션 반환. `TargetGroup` 값은 `_extract_elb_dimension(resource_id)`, `LoadBalancer` 값은 `_extract_elb_dimension(resource_tags["_lb_arn"])`
      - `resource_type in ("ALB", "NLB")`: `LoadBalancer` 단일 디멘션 반환
      - 그 외 (EC2, RDS): `{dim_key: resource_id}` 단일 디멘션 반환
      - `alarm_def.get("extra_dimensions", [])` 추가
    - `_resolve_tg_namespace(alarm_def, resource_tags)` → `str`:
      - `resource_tags.get("_lb_type") == "network"` → `"AWS/NetworkELB"`
      - 그 외 → `alarm_def["namespace"]` (기본값 `"AWS/ApplicationELB"`)
    - 단위 테스트: `tests/test_alarm_manager.py`에 `_build_dimensions()`, `_resolve_tg_namespace()` 테스트 추가
    - _Bug_Condition: isBugCondition(input) where resource_type == "TG" AND "LoadBalancer" NOT IN dimensions_
    - _Expected_Behavior: TG → TargetGroup + LoadBalancer 복합 디멘션, NLB TG → AWS/NetworkELB namespace_
    - _Preservation: ALB/NLB/EC2/RDS 디멘션 로직 불변_
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.6_

  - [x] 3.2 `_create_standard_alarm()` 수정
    - 기존 디멘션 구성 코드를 `_build_dimensions()` 호출로 교체
    - TG인 경우 namespace를 `_resolve_tg_namespace()`로 결정
    - _Requirements: 2.1_

  - [x] 3.3 `_create_single_alarm()` 수정
    - 동일하게 `_build_dimensions()` + `_resolve_tg_namespace()` 적용
    - _Requirements: 2.2_

  - [x] 3.4 `_recreate_standard_alarm()` 수정
    - 동일하게 `_build_dimensions()` + `_resolve_tg_namespace()` 적용
    - _Requirements: 2.3_

  - [x] 3.5 `_find_alarms_for_resource()` 수정 (버그 2: 레거시 [ELB] TG 알람 정리)
    - TG 리소스에 대해서도 `[ELB]` prefix 검색 추가
    - 기존 `if resource_type in ("ALB", "NLB"):` → `if resource_type in ("ALB", "NLB", "TG"):`
    - 단위 테스트: `tests/test_alarm_manager.py`에 TG `[ELB]` prefix 검색 테스트 추가
    - _Requirements: 2.4, 3.5_

  - [x] 3.6 버그 조건 탐색 테스트 재실행 — 수정 후 PASS 확인
    - **Property 1: Expected Behavior** — TG 복합 디멘션 생성
    - **IMPORTANT**: 태스크 1의 동일한 테스트를 재실행 — 새 테스트 작성 금지
    - 태스크 1의 테스트가 기대 동작을 인코딩하고 있으므로, PASS하면 버그 해결 확인
    - **EXPECTED OUTCOME: PASS** (버그 수정 확인)
    - _Requirements: 2.1, 2.2, 2.3, 3.6_

  - [x] 3.7 Preservation 테스트 재실행 — 수정 후에도 PASS 유지 확인
    - **Property 2: Preservation** — 비TG 리소스 디멘션 불변
    - **IMPORTANT**: 태스크 2의 동일한 테스트를 재실행 — 새 테스트 작성 금지
    - **EXPECTED OUTCOME: PASS** (회귀 없음 확인)
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 4. 테스트 인프라 개선
  - 파일: `infra-test/lb-tg-alarm-lab/template.yaml`
  - `TestEc2Instance.Properties.UserData` 변경:
    - 기존: `python3 -m http.server 80 &` (불안정, 크래시 시 재시작 없음)
    - 변경: `httpd`(Apache) systemd 서비스로 설치·실행
    - Health Check용 `/var/www/html/index.html`에 "OK" 응답 생성
  - 효과: ALB HTTP Health Check 즉시 통과, NLB TCP Health Check 즉시 통과, TG `HealthyHostCount` 메트릭 자동 생성
  - _Requirements: 해당 없음 (인프라 안정성 개선)_

- [x] 5. Checkpoint — 전체 테스트 통과 확인
  - 기존 테스트 + 새 테스트 모두 통과 확인
  - Ensure all tests pass, ask the user if questions arise.
