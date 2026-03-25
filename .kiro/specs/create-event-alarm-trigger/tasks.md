# Implementation Plan: CREATE 이벤트 알람 트리거

## Overview

AWS 리소스(EC2, RDS, ALB, NLB, TG) 생성 시 CloudTrail CREATE 이벤트를 감지하여 `Monitoring=on` 태그가 있으면 즉시 알람을 자동 생성하는 기능을 구현한다. TDD 사이클(거버넌스 §8)에 따라 테스트 → 구현 → 리팩터링 순서로 진행한다.

변경 대상 파일 3개: `common/__init__.py`, `template.yaml`, `remediation_handler/lambda_handler.py`

## Tasks

- [x] 1. MONITORED_API_EVENTS CREATE 카테고리 추가 (Red → Green)
  - [x] 1.1 CREATE 카테고리 단위 테스트 작성 (Red)
    - 테스트 파일: `tests/test_remediation_handler.py`에 추가
    - `MONITORED_API_EVENTS`에 `"CREATE"` 키 존재 확인
    - CREATE 카테고리에 4개 이벤트 포함 확인: `RunInstances`, `CreateDBInstance`, `CreateLoadBalancer`, `CreateTargetGroup`
    - 기존 MODIFY, DELETE, TAG_CHANGE 카테고리 보존 확인
    - `_get_event_category("RunInstances")` → `"CREATE"` 반환 확인
    - `_get_event_category("CreateDBInstance")` → `"CREATE"` 반환 확인
    - **EXPECTED OUTCOME**: 테스트 FAIL (CREATE 카테고리 미존재)
    - _Requirements: 1.1, 1.2, 1.3_
  - [x] 1.2 `common/__init__.py`에 CREATE 카테고리 추가 (Green)
    - `MONITORED_API_EVENTS`에 `"CREATE": ["RunInstances", "CreateDBInstance", "CreateLoadBalancer", "CreateTargetGroup"]` 추가
    - 기존 MODIFY, DELETE, TAG_CHANGE 엔트리 변경 없음
    - 태스크 1.1 테스트 재실행 → PASS 확인
    - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. CREATE용 ID 추출 함수 및 _API_MAP 확장 (Red → Green)
  - [x] 2.1 ID 추출 함수 단위 테스트 작성 (Red)
    - 테스트 파일: `tests/test_remediation_handler.py`에 추가
    - `_extract_run_instances_id`: `responseElements.instancesSet.items[0].instanceId` 추출 확인
    - `_extract_run_instances_id`: 빈 items → `None` 반환 확인
    - `_extract_create_db_id`: `requestParameters.dBInstanceIdentifier` 추출 확인
    - `_extract_create_lb_id`: `responseElements.loadBalancers[0].loadBalancerArn` 추출 확인
    - `_extract_create_lb_id`: 빈 loadBalancers → `None` 반환 확인
    - `_extract_create_tg_id`: `responseElements.targetGroups[0].targetGroupArn` 추출 확인
    - `_extract_create_tg_id`: 빈 targetGroups → `None` 반환 확인
    - **EXPECTED OUTCOME**: 테스트 FAIL (함수 미존재)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  - [x] 2.2 ID 추출 함수 4개 구현 및 _API_MAP 확장 (Green)
    - `remediation_handler/lambda_handler.py`에 추가:
      - `_extract_run_instances_id(resp)`: `resp.instancesSet.items[0].instanceId`
      - `_extract_create_db_id(params)`: `params.dBInstanceIdentifier`
      - `_extract_create_lb_id(resp)`: `resp.loadBalancers[0].loadBalancerArn`
      - `_extract_create_tg_id(resp)`: `resp.targetGroups[0].targetGroupArn`
    - `_API_MAP`에 4개 CREATE 엔트리 추가:
      - `"RunInstances": ("EC2", _extract_run_instances_id)`
      - `"CreateDBInstance": ("RDS", _extract_create_db_id)`
      - `"CreateLoadBalancer": ("ELB", _extract_create_lb_id)`
      - `"CreateTargetGroup": ("TG", _extract_create_tg_id)`
    - 태스크 2.1 테스트 재실행 → PASS 확인
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 3. parse_cloudtrail_event CREATE 이벤트 파싱 (Red → Green)
  - [x] 3.1 CREATE 이벤트 파싱 단위 테스트 작성 (Red)
    - 테스트 파일: `tests/test_remediation_handler.py`에 추가
    - `RunInstances` 이벤트 → `resource_type="EC2"`, `event_category="CREATE"`, `resource_id=instanceId` 확인
    - `CreateDBInstance` 이벤트 → `resource_type="RDS"`, `event_category="CREATE"`, `resource_id=dBInstanceIdentifier` 확인
    - `CreateLoadBalancer` ALB ARN → `resource_type="ALB"`, `event_category="CREATE"` 확인
    - `CreateLoadBalancer` NLB ARN → `resource_type="NLB"`, `event_category="CREATE"` 확인
    - `CreateTargetGroup` → `resource_type="TG"`, `event_category="CREATE"` 확인
    - `RunInstances` responseElements 누락 → `ValueError` 확인
    - `CreateLoadBalancer` responseElements 빈 리스트 → `ValueError` 확인
    - **EXPECTED OUTCOME**: 테스트 FAIL (parse_cloudtrail_event가 responseElements 미처리)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 6.1, 6.2, 6.3_
  - [x] 3.2 parse_cloudtrail_event에 CREATE 분기 추가 (Green)
    - `parse_cloudtrail_event()`에서 CREATE 이벤트인 경우 `detail.responseElements`를 추출 함수에 전달하는 분기 추가
    - `CreateDBInstance`만 기존대로 `requestParameters`에서 추출
    - `RunInstances`, `CreateLoadBalancer`, `CreateTargetGroup`은 `responseElements`에서 추출
    - ELB ARN 기반 ALB/NLB 타입 세분화 (`_resolve_elb_type`) 기존 로직 활용
    - 태스크 3.1 테스트 재실행 → PASS 확인
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 6.1_

  - [ ]* 3.3 Property 1 PBT 작성 — CREATE 이벤트 파싱 정확성
    - **Property 1: CREATE 이벤트 파싱 정확성 (CREATE Event Parsing Accuracy)**
    - **Validates: Requirements 1.2, 3.1, 3.2, 3.3, 3.4, 3.6, 6.1**
    - 테스트 파일: `tests/test_pbt_create_event.py`
    - Hypothesis 전략: 4개 CREATE 이벤트 유형 × 랜덤 리소스 ID 생성
    - Property: `parse_cloudtrail_event()` 반환값의 `resource_id`, `resource_type`, `event_category` 정확성 검증

- [x] 4. _handle_create 핸들러 및 lambda_handler 라우팅 (Red → Green)
  - [x] 4.1 _handle_create 및 라우팅 단위 테스트 작성 (Red)
    - 테스트 파일: `tests/test_remediation_handler.py`에 추가
    - CREATE 이벤트 → `_handle_create` 호출 확인 (라우팅)
    - CREATE + `Monitoring=on` → `create_alarms_for_resource` 호출 확인
    - CREATE + `Monitoring` 태그 없음 → `create_alarms_for_resource` 미호출 + info 로그 확인
    - CREATE + `get_resource_tags` 빈 딕셔너리 반환 → warning 로그 + 알람 생성 스킵 확인
    - CREATE 이벤트 정상 처리 → `{"status": "ok"}` 반환 확인
    - CREATE 이벤트 처리 중 예외 → `{"status": "error"}` 반환 확인
    - **EXPECTED OUTCOME**: 테스트 FAIL (_handle_create 미존재)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 7.1, 7.2, 7.3_
  - [x] 4.2 _handle_create 구현 및 lambda_handler 라우팅 추가 (Green)
    - `_handle_create(parsed)` 함수 구현:
      - `get_resource_tags()` → `has_monitoring_tag()` → `create_alarms_for_resource()` 패턴
      - 빈 태그 → warning 로그 + return
      - Monitoring 태그 없음 → info 로그 + return
    - `lambda_handler()`에 `elif parsed.event_category == "CREATE": _handle_create(parsed)` 추가
    - 태스크 4.1 테스트 재실행 → PASS 확인
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 7.1, 7.2, 7.3_

  - [ ]* 4.3 Property 2 PBT 작성 — Monitoring 태그 게이팅
    - **Property 2: Monitoring 태그 기반 알람 생성 게이팅 (Monitoring Tag Gates Alarm Creation)**
    - **Validates: Requirements 4.1, 4.2, 4.3**
    - 테스트 파일: `tests/test_pbt_create_event.py`에 추가
    - Hypothesis 전략: 랜덤 리소스 ID/타입 + Monitoring 태그 유무 랜덤
    - Property: `Monitoring=on` → `create_alarms_for_resource` 호출, 그 외 → 미호출

  - [ ]* 4.4 Property 4 PBT 작성 — CREATE 라우팅 및 응답
    - **Property 4: CREATE 이벤트 라우팅 및 정상 응답 (CREATE Event Routing and Response)**
    - **Validates: Requirements 7.1, 7.2, 7.3**
    - 테스트 파일: `tests/test_pbt_create_event.py`에 추가
    - Hypothesis 전략: 랜덤 CREATE 이벤트
    - Property: `lambda_handler()` → `{"status": "ok"}` 반환, 예외 시 `{"status": "error"}` 반환

- [x] 5. Checkpoint — 중간 테스트 통과 확인
  - `pytest tests/test_remediation_handler.py` 전체 실행하여 모든 테스트 통과 확인
  - 기존 테스트 회귀 없음 확인
  - 문제 발생 시 사용자에게 확인 요청

- [ ] 6. CREATE-TAG_CHANGE 멱등성 검증
  - [ ]* 6.1 Property 3 PBT 작성 — CREATE-TAG_CHANGE 멱등성
    - **Property 3: CREATE와 TAG_CHANGE 이벤트 간 멱등성 (CREATE-TAG_CHANGE Idempotency)**
    - **Validates: Requirements 5.1, 5.2, 5.3**
    - 테스트 파일: `tests/test_pbt_create_event.py`에 추가
    - Hypothesis 전략: 랜덤 리소스에 대해 CREATE→TAG_CHANGE, TAG_CHANGE→CREATE, 단독 처리 순서 랜덤
    - Property: 어떤 순서로 처리해도 `create_alarms_for_resource` 호출 인자 동일

- [x] 7. template.yaml EventBridge 규칙 업데이트
  - [x] 7.1 EventBridge 규칙 정적 검증 테스트 작성 (Red)
    - 테스트 파일: `tests/test_remediation_handler.py`에 추가
    - `template.yaml` 파싱하여 `CloudTrailModifyRule` EventPattern에 4개 CREATE 이벤트 포함 확인
    - 기존 MODIFY/DELETE/TAG_CHANGE 이벤트 필터 보존 확인
    - **EXPECTED OUTCOME**: 테스트 FAIL (CREATE 이벤트 미포함)
    - _Requirements: 2.1, 2.2_
  - [x] 7.2 template.yaml에 CREATE 이벤트 추가 (Green)
    - `CloudTrailModifyRule` EventPattern `detail.eventName`에 추가:
      - `RunInstances`
      - `CreateDBInstance`
      - `CreateLoadBalancer`
      - `CreateTargetGroup`
    - 기존 이벤트 필터 변경 없음
    - 태스크 7.1 테스트 재실행 → PASS 확인
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 8. Final Checkpoint — 전체 테스트 통과 확인
  - `pytest tests/` 전체 실행하여 모든 테스트 통과 확인
  - PBT 테스트 (`tests/test_pbt_create_event.py`) 통과 확인
  - 단위 테스트 통과 확인
  - 기존 테스트 회귀 없음 확인
  - 문제 발생 시 사용자에게 확인 요청

## Notes

- `*` 표시된 태스크는 선택적이며 빠른 MVP를 위해 스킵 가능
- 각 태스크는 특정 요구사항을 참조하여 추적 가능
- TDD 사이클(Red → Green)에 따라 테스트를 먼저 작성하고 구현
- Property 테스트는 design.md의 4개 Correctness Properties를 검증
- `template.yaml` 변경은 인프라 변경이므로 마지막에 수행
