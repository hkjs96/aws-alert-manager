# Implementation Plan: Tag-Driven Alarm Engine

## Overview

태그 기반 알람 엔진의 3가지 핵심 개선사항을 구현한다:
1. `_resolve_metric_dimensions()` 디멘션 필터링 개선 (`_select_best_dimensions()` 헬퍼 추가)
2. `Threshold_*=off` 태그로 하드코딩/동적 알람 비활성화 + 기존 알람 자동 삭제
3. `sync_alarms_for_resource()` 동적 알람 생성/삭제/업데이트 + `deleted` 키 추가

TDD 사이클(레드→그린→리팩터)을 따르며, 각 기능 단위로 테스트 → 구현 순서로 진행한다.

## Tasks

- [x] 1. `is_threshold_off()` 함수 추가 (tag_resolver.py)
  - [x] 1.1 `is_threshold_off()` 단위 테스트 작성 (tests/test_tag_resolver.py)
    - `off`, `OFF`, `Off`, `oFf` 등 대소문자 변형 → `True`
    - 양의 숫자 문자열, 빈 문자열, 태그 미설정 → `False`
    - _Requirements: 8.1, 8.2, 8.3_
  - [x] 1.2 `is_threshold_off()` 구현 (common/tag_resolver.py)
    - `resource_tags.get(f"Threshold_{metric_name}", "").strip().lower() == "off"` 로직
    - import 경로에 `is_threshold_off` 추가
    - _Requirements: 8.1, 8.2, 8.3_
  - [ ]* 1.3 Property 8 PBT 작성 (tests/test_pbt_tag_driven_alarm.py)
    - **Property 8: is_threshold_off() 정확성**
    - off 문자열의 모든 대소문자 변형 → True, 양의 숫자/빈 문자열 → False
    - **Validates: Requirements 8.1, 8.3**

- [x] 2. `_select_best_dimensions()` 헬퍼 추가 + `_resolve_metric_dimensions()` 수정 (alarm_manager.py)
  - [x] 2.1 `_select_best_dimensions()` 단위 테스트 작성 (tests/test_alarm_manager.py)
    - Primary_Dimension_Key만 포함된 조합 우선 선택
    - AZ 미포함 + 디멘션 수 최소 선택
    - 모든 조합에 AZ 포함 시 디멘션 수 최소 선택 (AZ 허용)
    - 빈 리스트 입력 시 빈 리스트 반환
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_
  - [x] 2.2 `_select_best_dimensions()` 구현 (common/alarm_manager.py)
    - 우선순위: primary_dim_key만 → AZ 미포함 최소 디멘션 → 최소 디멘션 (AZ 허용)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_
  - [x] 2.3 `_resolve_metric_dimensions()`에서 `_select_best_dimensions()` 호출하도록 수정
    - `metrics[0]["Dimensions"]` → `_select_best_dimensions(metrics, dim_key)` 교체
    - _Requirements: 1.1, 1.2_
  - [ ]* 2.4 Property 1 PBT 작성 (tests/test_pbt_tag_driven_alarm.py)
    - **Property 1: 디멘션 선택 우선순위**
    - 임의의 list_metrics 결과에 대해 우선순위 규칙 검증
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**

- [x] 3. `_parse_threshold_tags()`에 off 값 명시적 처리 추가 (alarm_manager.py)
  - [x] 3.1 `_parse_threshold_tags()` off 제외 단위 테스트 작성 (tests/test_alarm_manager.py)
    - `Threshold_CustomMetric=off` → 결과에서 제외
    - `Threshold_CustomMetric=OFF` → 결과에서 제외
    - 양의 숫자 태그는 정상 포함
    - _Requirements: 2.1, 2.2_
  - [x] 3.2 `_parse_threshold_tags()` 수정 — off 값 명시적 스킵 로직 추가
    - `float()` 변환 전에 `value.strip().lower() == "off"` 체크 추가
    - _Requirements: 2.1, 2.2_
  - [ ]* 3.3 Property 2 PBT 작성 (tests/test_pbt_tag_driven_alarm.py)
    - **Property 2: off 태그 파싱 제외**
    - 임의의 태그 딕셔너리에서 off 값 메트릭이 결과에 포함되지 않음을 검증
    - **Validates: Requirements 2.1, 2.2**

- [x] 4. Checkpoint — 기반 함수 검증
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. `create_alarms_for_resource()`에 off 체크 추가 (alarm_manager.py)
  - [x] 5.1 하드코딩 알람 off 스킵 단위 테스트 작성 (tests/test_alarm_manager.py)
    - `Threshold_CPU=off` → CPU 알람 생성 스킵
    - `Threshold_Disk_root=off` → root Disk 알람 생성 스킵
    - off 미설정 메트릭은 정상 생성
    - _Requirements: 3.1, 3.3, 4.1_
  - [x] 5.2 `create_alarms_for_resource()` 수정 — 하드코딩 알람 루프에 `is_threshold_off()` 체크 추가
    - 표준 알람: `is_threshold_off(resource_tags, metric)` → True이면 스킵
    - `_create_disk_alarms()` 수정: 경로별 `is_threshold_off(resource_tags, f"Disk_{suffix}")` 체크
    - `alarm_manager.py` import에 `is_threshold_off` 추가
    - _Requirements: 3.1, 3.3, 4.1_
  - [ ]* 5.3 Property 3 PBT 작성 (tests/test_pbt_tag_driven_alarm.py)
    - **Property 3: Create_Path off 메트릭 스킵**
    - off 설정된 하드코딩 메트릭이 create 결과에 포함되지 않음을 검증
    - **Validates: Requirements 3.1, 3.3, 4.1**

- [x] 6. `sync_alarms_for_resource()` 동적 알람 + off 처리 추가 (alarm_manager.py)
  - [x] 6.1 sync 동적 알람 생성/삭제/업데이트 단위 테스트 작성 (tests/test_alarm_manager.py)
    - 새 동적 태그 추가 → `created` 목록에 포함
    - 동적 태그 제거 → 기존 동적 알람 `deleted` 목록에 포함
    - 동적 태그 임계치 변경 → `updated` 목록에 포함
    - 동적 태그 임계치 동일 → `ok` 목록에 포함
    - _Requirements: 5.1, 5.2, 6.1, 6.2, 7.1, 7.2, 7.3_
  - [x] 6.2 sync 하드코딩 off 삭제 단위 테스트 작성 (tests/test_alarm_manager.py)
    - `Threshold_CPU=off` + 기존 CPU 알람 → `deleted` 목록에 포함
    - off 삭제 로깅 검증
    - _Requirements: 3.2, 4.2, 4.3_
  - [x] 6.3 `sync_alarms_for_resource()` 수정 — 결과에 `deleted` 키 추가 + 동적 알람 동기화 로직 구현
    - 결과 딕셔너리에 `"deleted": []` 추가
    - 하드코딩 알람 off 체크: `is_threshold_off()` → 기존 알람 삭제 + `deleted` 추가
    - 동적 알람 동기화: `_parse_threshold_tags()` 결과와 기존 동적 알람 비교
      - 새 동적 메트릭 → `_create_dynamic_alarm()` → `created`
      - 태그 제거된 동적 알람 → `delete_alarms` → `deleted`
      - 임계치 변경 → 재생성 → `updated`
      - 임계치 동일 → `ok`
    - _Requirements: 3.2, 4.2, 4.3, 5.1, 5.2, 6.1, 6.2, 7.1, 7.2, 7.3_
  - [ ]* 6.4 Property 4 PBT 작성 (tests/test_pbt_tag_driven_alarm.py)
    - **Property 4: Sync_Path off 메트릭 삭제**
    - off 태그 설정된 하드코딩 메트릭의 기존 알람이 deleted에 포함됨을 검증
    - **Validates: Requirements 3.2, 4.2**
  - [ ]* 6.5 Property 5 PBT 작성 (tests/test_pbt_tag_driven_alarm.py)
    - **Property 5: Sync_Path 동적 알람 신규 생성**
    - 새 동적 태그의 알람이 created에 포함됨을 검증
    - **Validates: Requirements 5.1, 5.2**
  - [ ]* 6.6 Property 6 PBT 작성 (tests/test_pbt_tag_driven_alarm.py)
    - **Property 6: Sync_Path 동적 알람 삭제**
    - 태그 제거된 동적 알람이 deleted에 포함됨을 검증
    - **Validates: Requirements 6.1, 6.2**
  - [ ]* 6.7 Property 7 PBT 작성 (tests/test_pbt_tag_driven_alarm.py)
    - **Property 7: Sync_Path 동적 알람 임계치 동기화**
    - 임계치 변경 → updated, 동일 → ok 검증
    - **Validates: Requirements 7.1, 7.2, 7.3**

- [x] 7. Checkpoint — 전체 기능 검증
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. 통합 와이어링 및 최종 검증
  - [x] 8.1 `alarm_manager.py` import 정리 및 `is_threshold_off` export 확인
    - `from common.tag_resolver import ..., is_threshold_off` 추가 확인
    - _Requirements: 8.2_
  - [x] 8.2 기존 테스트 회귀 검증 (tests/test_alarm_manager.py, tests/test_tag_resolver.py)
    - 기존 테스트가 모두 통과하는지 확인
    - off 미설정 리소스의 기존 동작(하드코딩 기본값 생성) 유지 확인
    - _Requirements: 전체_

- [x] 9. Final checkpoint — 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- TDD 사이클: 각 기능 단위로 테스트 먼저 작성 → 구현 → 리팩터링
- Property 테스트는 `hypothesis` 라이브러리 사용, `@settings(max_examples=100)`
- 코딩 거버넌스: boto3 lru_cache 싱글턴, ClientError만 catch, 함수 복잡도 제한 준수
- 기존 코드 구조 최대한 유지하며 최소 변경으로 구현
