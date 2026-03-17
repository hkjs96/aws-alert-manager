# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Fault Condition** - Threshold 태그 변경 시 sync_alarms_for_resource 미호출
  - **CRITICAL**: 이 테스트는 수정 전 코드에서 반드시 FAIL해야 함 - 실패가 버그 존재를 증명
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: 이 테스트는 기대 동작을 인코딩함 - 구현 후 통과하면 버그 수정을 검증
  - **GOAL**: 버그가 존재함을 증명하는 반례 도출
  - **Scoped PBT Approach**: 결정론적 버그이므로 구체적인 실패 케이스로 범위 한정
  - `Threshold_CPU=90` CreateTags 이벤트 + `Monitoring=on` 리소스 → `sync_alarms_for_resource` 호출 여부 확인
  - `Threshold_Disk_data=20` CreateTags 이벤트 + `Monitoring=on` EC2 → `sync_alarms_for_resource` 호출 여부 확인
  - `Threshold_Connections=100` AddTagsToResource 이벤트 + `Monitoring=on` RDS → 호출 여부 확인
  - 수정 전 코드에서 실행 - **EXPECTED OUTCOME**: 테스트 FAIL (버그 존재 증명)
  - 반례 문서화: `monitoring_involved = False`로 즉시 `return`하여 `sync_alarms_for_resource` 미호출
  - 테스트 작성, 실행, 실패 문서화 완료 시 태스크 완료 처리
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - 비Threshold 태그 변경 동작 유지
  - **IMPORTANT**: 관찰 우선 방법론 적용
  - 수정 전 코드에서 비버그 입력(Threshold_* 없는 태그 변경)에 대한 동작 관찰
  - 관찰: `Monitoring=on` CreateTags → `create_alarms_for_resource` 호출
  - 관찰: `Monitoring` DeleteTags → 알람 삭제 + lifecycle SNS 알림
  - 관찰: `Name=my-server` CreateTags → 아무것도 호출되지 않음 (무시)
  - 관찰된 동작 패턴을 캡처하는 property-based test 작성
  - 수정 전 코드에서 테스트 실행 - **EXPECTED OUTCOME**: 테스트 PASS (기준 동작 확인)
  - 테스트 작성, 실행, 통과 확인 완료 시 태스크 완료 처리
  - _Requirements: 3.1, 3.2, 3.3_

- [x] 3. Fix for Threshold_* 태그 변경 시 알람 재동기화 누락

  - [x] 3.1 Implement the fix
    - `has_monitoring_tag` import 추가: `common.tag_resolver`에서 import
    - `monitoring_involved = False` 분기에서 `threshold_involved` 확인 조건 추가
    - `Threshold_*` 키 존재 시 `get_resource_tags`로 현재 태그 조회
    - `has_monitoring_tag(tags)` True이면 `sync_alarms_for_resource` 호출
    - `Monitoring=on` 없으면 조용히 종료
    - _Bug_Condition: isBugCondition(input) where event_category=="TAG_CHANGE" AND "Monitoring" NOT IN tag_keys AND ANY key STARTS_WITH "Threshold__"_
    - _Expected_Behavior: sync_alarms_for_resource(resource_id, resource_type, tags) 호출_
    - _Preservation: Monitoring 태그 처리 경로 및 일반 태그 무시 동작 변경 없음_
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3_

  - [x] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Threshold 태그 변경 시 sync_alarms_for_resource 호출
    - **IMPORTANT**: 태스크 1의 동일한 테스트 재실행 - 새 테스트 작성 금지
    - 태스크 1의 테스트가 기대 동작을 인코딩하고 있음
    - 이 테스트가 통과하면 기대 동작이 충족됨을 확인
    - 태스크 1의 버그 조건 탐색 테스트 실행
    - **EXPECTED OUTCOME**: 테스트 PASS (버그 수정 확인)
    - _Requirements: 2.1, 2.2_

  - [x] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - 비Threshold 태그 변경 동작 유지
    - **IMPORTANT**: 태스크 2의 동일한 테스트 재실행 - 새 테스트 작성 금지
    - 태스크 2의 보존 property 테스트 실행
    - **EXPECTED OUTCOME**: 테스트 PASS (회귀 없음 확인)
    - 수정 후에도 모든 테스트 통과 확인 (회귀 없음)

- [x] 4. Checkpoint - Ensure all tests pass
  - 모든 테스트 통과 확인, 질문이 있으면 사용자에게 문의
