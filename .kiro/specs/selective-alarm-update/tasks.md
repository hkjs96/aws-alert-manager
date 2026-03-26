# Implementation Plan

- [x] 1. 버그 조건 탐색 테스트 작성
  - **Property 1: Fault Condition** - 변경된 알람만 개별 삭제·재생성 (미수정 코드에서 실패 확인)
  - **CRITICAL**: 이 테스트는 미수정 코드에서 반드시 FAIL해야 함 - 실패가 버그 존재를 증명
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: 이 테스트는 기대 동작을 인코딩함 - 수정 후 통과 시 버그 해결 검증
  - **GOAL**: `result["ok"]` 알람까지 삭제되는 반례를 확인하여 근본 원인 분석 검증
  - **Scoped PBT Approach**: `result["updated"]`가 비어있지 않고 `result["ok"]`도 비어있지 않은 구체적 케이스로 범위 한정
  - 테스트 파일: `tests/test_pbt_selective_alarm_fault.py`
  - `Threshold_Disk_data=90` 변경 시나리오: `sync_alarms_for_resource` 호출 후 `_delete_all_alarms_for_resource`가 호출되는지 mock으로 확인
  - `result["ok"]` 목록의 CPU/Memory 알람이 삭제되지 않아야 함을 assert
  - 미수정 코드에서 실행 → FAIL 예상 (버그 존재 확인)
  - 반례 문서화: `result["ok"]` 알람이 `_delete_all_alarms_for_resource`로 삭제됨
  - 테스트 작성 및 실행 후 실패 확인 시 완료로 표시
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.3_

- [x] 2. 보존 속성 테스트 작성 (수정 전)
  - **Property 2: Preservation** - 변경되지 않은 알람 및 최초 생성 동작 유지
  - **IMPORTANT**: 관찰 우선 방법론 적용
  - 테스트 파일: `tests/test_pbt_selective_alarm_preservation.py`
  - 관찰 1: 알람 없음(최초 생성) → `create_alarms_for_resource` 전체 호출 (미수정 코드에서 확인)
  - 관찰 2: `result["ok"]`만 존재 → 아무 삭제/재생성도 발생하지 않음 (미수정 코드에서 확인)
  - 관찰 3: `result["ok"]` 알람은 sync 후에도 그대로 유지됨 (미수정 코드에서 확인)
  - 위 관찰된 동작을 property-based test로 작성
  - 미수정 코드에서 실행 → PASS 예상 (기준 동작 확인)
  - 테스트 작성 및 실행 후 통과 확인 시 완료로 표시
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 3. selective-alarm-update 버그 수정

  - [x] 3.1 `_metric_name_to_key` 헬퍼 함수 추가
    - `CPUUtilization` → `"CPU"`, `mem_used_percent` → `"Memory"`, `disk_used_percent` → `"Disk"` 매핑
    - `common/alarm_manager.py`에 추가
    - _Bug_Condition: isBugCondition(input) where result["updated"] not empty AND result["ok"] not empty_
    - _Requirements: 2.1, 2.3_

  - [x] 3.2 `_recreate_alarm_by_name` 헬퍼 함수 추가
    - `describe_alarms`로 기존 알람 설정(Dimensions 포함) 조회
    - `_metric_name_to_key`로 메트릭 타입 식별
    - `delete_alarms(AlarmNames=[alarm_name])`으로 해당 알람만 삭제
    - `put_metric_alarm`으로 재생성 (Disk 알람은 기존 Dimensions 재사용)
    - _Bug_Condition: isBugCondition(input) where result["updated"] not empty AND result["ok"] not empty_
    - _Expected_Behavior: result["updated"] 알람만 개별 삭제·재생성, result["ok"] 알람 유지_
    - _Requirements: 2.1, 2.3_

  - [x] 3.3 `_create_single_alarm` 헬퍼 함수 추가
    - 전체 삭제 없이 단일 메트릭 알람만 생성
    - `result["created"]` 메트릭 처리용 (신규 알람 추가 시)
    - _Expected_Behavior: 기존 알람 삭제 없이 신규 알람만 생성_
    - _Requirements: 2.2_

  - [x] 3.4 `sync_alarms_for_resource` 마지막 블록 수정
    - 기존: `if needs_recreate: create_alarms_for_resource(...)`
    - 변경: `result["updated"]` 각 알람에 `_recreate_alarm_by_name` 호출, `result["created"]` 각 메트릭에 `_create_single_alarm` 호출
    - _Bug_Condition: isBugCondition(input) where result["updated"] not empty AND result["ok"] not empty_
    - _Expected_Behavior: result["updated"] 알람만 개별 삭제·재생성, result["created"] 메트릭만 신규 생성_
    - _Preservation: 최초 생성(알람 없음) 경로는 변경 없음, result["ok"]만 존재 시 아무 동작 없음_
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4_

  - [x] 3.5 버그 조건 탐색 테스트 통과 확인
    - **Property 1: Expected Behavior** - 변경된 알람만 개별 삭제·재생성
    - **IMPORTANT**: task 1에서 작성한 동일 테스트 재실행 - 새 테스트 작성 금지
    - `tests/test_pbt_selective_alarm_fault.py` 실행
    - **EXPECTED OUTCOME**: 테스트 PASS (버그 수정 확인)
    - _Requirements: 2.1, 2.3_

  - [x] 3.6 보존 테스트 통과 확인
    - **Property 2: Preservation** - 변경되지 않은 알람 및 최초 생성 동작 유지
    - **IMPORTANT**: task 2에서 작성한 동일 테스트 재실행 - 새 테스트 작성 금지
    - `tests/test_pbt_selective_alarm_preservation.py` 실행
    - **EXPECTED OUTCOME**: 테스트 PASS (회귀 없음 확인)
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 4. 체크포인트 - 모든 테스트 통과 확인
  - 모든 테스트 통과 확인, 문제 발생 시 사용자에게 문의
