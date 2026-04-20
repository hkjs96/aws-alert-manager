# Implementation Plan

- [x] 1. DeleteTargetGroup 버그 조건 탐색 테스트 작성
  - **Property 1: Bug Condition** - DeleteTargetGroup 이벤트 파싱 실패
  - **CRITICAL**: 이 테스트는 수정 전 코드에서 반드시 FAIL해야 한다 — 실패가 버그 존재를 증명
  - **DO NOT** 테스트 실패 시 코드를 수정하지 말 것
  - **NOTE**: 이 테스트는 기대 동작을 인코딩하며, 수정 후 PASS하면 버그 해결을 검증
  - **GOAL**: 버그 존재를 증명하는 반례(counterexample)를 도출
  - **Scoped PBT Approach**: 결정적 버그이므로 `DeleteTargetGroup` 이벤트 + 랜덤 TG ARN으로 범위 한정
  - 테스트 파일: `tests/test_pbt_tg_delete_cleanup_fault.py`
  - Hypothesis 전략: 랜덤 TG ARN 생성 (`arn:aws:elasticloadbalancing:{region}:{account}:targetgroup/{name}/{hash}`)
  - `DeleteTargetGroup` 이벤트를 `parse_cloudtrail_event()`에 전달
  - 기대 동작 assertion: `resource_type == "TG"`, `event_category == "DELETE"`, `resource_id == targetGroupArn`
  - 수정 전 코드에서 실행 → `ValueError("Unsupported eventName")` 발생으로 FAIL 예상
  - **EXPECTED OUTCOME**: 테스트 FAIL (버그 존재 확인)
  - 반례 문서화: `parse_cloudtrail_event(DeleteTargetGroup event)` → `ValueError` 발생
  - 테스트 작성·실행·실패 문서화 완료 시 태스크 완료 처리
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3_

- [x] 2. 기존 이벤트 동작 보존 테스트 작성 (수정 전)
  - **Property 2: Preservation** - 기존 DELETE/MODIFY/TAG_CHANGE 이벤트 파싱 보존
  - **IMPORTANT**: 관찰 우선(observation-first) 방법론 준수
  - 테스트 파일: `tests/test_pbt_tg_delete_cleanup_preservation.py`
  - 관찰: 수정 전 코드에서 기존 이벤트 파싱 결과 확인
    - `TerminateInstances` → `resource_type="EC2"`, `event_category="DELETE"`
    - `DeleteDBInstance` → `resource_type="RDS"`, `event_category="DELETE"`
    - `DeleteLoadBalancer` → `resource_type` ∈ `{"ALB","NLB"}`, `event_category="DELETE"`
    - `ModifyInstanceAttribute` → `resource_type="EC2"`, `event_category="MODIFY"`
    - `CreateTags`/`DeleteTags` → `resource_type="EC2"`, `event_category="TAG_CHANGE"`
    - `AddTags`/`RemoveTags` → `resource_type` ∈ `{"ALB","NLB"}`, `event_category="TAG_CHANGE"`
  - Hypothesis 전략: `_API_MAP`의 기존 이벤트 중 랜덤 선택 + 해당 이벤트에 맞는 랜덤 리소스 ID 생성
  - Property: 모든 기존 이벤트에 대해 `parse_cloudtrail_event()` 결과의 `resource_type`과 `event_category`가 `_API_MAP`/`MONITORED_API_EVENTS` 매핑과 일치
  - 수정 전 코드에서 실행 → 모든 테스트 PASS 확인
  - **EXPECTED OUTCOME**: 테스트 PASS (기존 동작 기준선 확립)
  - 테스트 작성·실행·통과 확인 시 태스크 완료 처리
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 3. DeleteTargetGroup 버그 수정

  - [x] 3.1 `_extract_tg_id()` 함수 추가 및 3개 레이어 수정
    - `remediation_handler/lambda_handler.py`: `_extract_tg_id(params)` 함수 추가 — `params.get("targetGroupArn")` 반환
    - `remediation_handler/lambda_handler.py`: `_API_MAP`에 `"DeleteTargetGroup": ("TG", _extract_tg_id)` 엔트리 추가 (기존 `DeleteLoadBalancer` 아래)
    - `common/__init__.py`: `MONITORED_API_EVENTS["DELETE"]`에 `"DeleteTargetGroup"` 추가 (기존 `DeleteLoadBalancer` 아래)
    - `template.yaml`: `CloudTrailModifyRule` EventPattern `detail.eventName`에 `DeleteTargetGroup` 추가 (기존 `DeleteLoadBalancer` 아래)
    - _Bug_Condition: isBugCondition(event) where event.detail.eventName == "DeleteTargetGroup" AND 3개 레이어 모두 누락_
    - _Expected_Behavior: parse_cloudtrail_event() → resource_type="TG", event_category="DELETE", resource_id=targetGroupArn_
    - _Preservation: 기존 _API_MAP 엔트리, MONITORED_API_EVENTS 엔트리, EventPattern 엔트리 변경 없음 (순수 추가)_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 3.2 버그 조건 탐색 테스트 통과 확인
    - **Property 1: Expected Behavior** - DeleteTargetGroup 이벤트 파싱 성공
    - **IMPORTANT**: 태스크 1의 동일한 테스트를 재실행 — 새 테스트 작성 금지
    - `tests/test_pbt_tg_delete_cleanup_fault.py` 재실행
    - **EXPECTED OUTCOME**: 테스트 PASS (버그 수정 확인)
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.3 보존 테스트 통과 확인
    - **Property 2: Preservation** - 기존 이벤트 동작 보존
    - **IMPORTANT**: 태스크 2의 동일한 테스트를 재실행 — 새 테스트 작성 금지
    - `tests/test_pbt_tg_delete_cleanup_preservation.py` 재실행
    - **EXPECTED OUTCOME**: 테스트 PASS (회귀 없음 확인)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 3.4 단위 테스트 추가
    - 테스트 파일: `tests/test_remediation_handler.py`에 추가
    - `_extract_tg_id()`: `targetGroupArn` 키에서 ARN 추출 확인
    - `_extract_tg_id()`: `targetGroupArn` 키 없을 때 `None` 반환 확인
    - `_get_event_category("DeleteTargetGroup")` → `"DELETE"` 반환 확인
    - `parse_cloudtrail_event()`: `DeleteTargetGroup` 이벤트 → `resource_type="TG"`, `event_category="DELETE"`, `resource_id=targetGroupArn` 확인
    - `_handle_delete()`: TG 타입 + `Monitoring=on` → `delete_alarms_for_resource` + `send_lifecycle_alert` 호출 확인
    - `_handle_delete()`: TG 타입 + `Monitoring` 태그 없음 → `delete_alarms_for_resource` 호출, `send_lifecycle_alert` 미호출 확인
    - `template.yaml` EventPattern에 `DeleteTargetGroup` 포함 정적 검증
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.6_

- [x] 4. Checkpoint - 전체 테스트 통과 확인
  - `pytest tests/` 전체 실행하여 모든 테스트 통과 확인
  - PBT 테스트 (fault + preservation) 통과 확인
  - 단위 테스트 통과 확인
  - 기존 테스트 회귀 없음 확인
  - 문제 발생 시 사용자에게 확인 요청
