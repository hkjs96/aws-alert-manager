# Implementation Plan: ALB/RDS 메트릭 확장 (expand-alb-rds-metrics)

## Overview

ALB 리소스에 ELB4XX, TargetConnectionError 메트릭을, RDS 리소스에 ConnectionAttempts 메트릭을 추가한다. 데이터 전용 변경이며, 기존 헬퍼 함수는 수정하지 않는다. TDD 레드-그린-리팩터링 사이클(거버넌스 §8)을 리소스 유형별로 반복한다.

변경 파일: `common/alarm_manager.py`, `common/__init__.py`, `tests/test_alarm_manager.py`, `tests/test_pbt_expand_alb_rds_metrics.py`

## Tasks

- [x] 1. ALB 기본 알람 확장 — ELB4XX, TargetConnectionError
  - [x] 1.1 Red: `tests/test_alarm_manager.py`에 ALB ELB4XX/TargetConnectionError 실패 테스트 작성
    - `test_get_alarm_defs_alb` 기대 개수를 5로, 기대 메트릭 집합에 `ELB4XX`, `TargetConnectionError` 추가
    - `_HARDCODED_METRIC_KEYS["ALB"]`가 `{"RequestCount", "ELB5XX", "TargetResponseTime", "ELB4XX", "TargetConnectionError"}` 검증
    - `_METRIC_DISPLAY["ELB4XX"]` == `("HTTPCode_ELB_4XX_Count", ">", "")` 검증
    - `_METRIC_DISPLAY["TargetConnectionError"]` == `("TargetConnectionErrorCount", ">", "")` 검증
    - `_metric_name_to_key("HTTPCode_ELB_4XX_Count")` == `"ELB4XX"` 검증
    - `_metric_name_to_key("TargetConnectionErrorCount")` == `"TargetConnectionError"` 검증
    - `HARDCODED_DEFAULTS["ELB4XX"]` == `100.0`, `HARDCODED_DEFAULTS["TargetConnectionError"]` == `50.0` 검증
    - ELB4XX 알람: `dimension_key` == `"LoadBalancer"`, `stat` == `"Sum"`, `comparison` == `"GreaterThanThreshold"`, `namespace` == `"AWS/ApplicationELB"` 검증
    - TargetConnectionError 알람: `dimension_key` == `"LoadBalancer"`, `stat` == `"Sum"`, `comparison` == `"GreaterThanThreshold"`, `namespace` == `"AWS/ApplicationELB"` 검증
    - 실행 → 실패 확인
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 1.2 Green: ALB ELB4XX/TargetConnectionError 데이터 정의 추가
    - `common/__init__.py`: `HARDCODED_DEFAULTS`에 `"ELB4XX": 100.0`, `"TargetConnectionError": 50.0` 추가
    - `common/alarm_manager.py`: `_METRIC_DISPLAY`에 `"ELB4XX": ("HTTPCode_ELB_4XX_Count", ">", "")`, `"TargetConnectionError": ("TargetConnectionErrorCount", ">", "")` 추가
    - `common/alarm_manager.py`: `_ALB_ALARMS`에 ELB4XX 알람 정의 추가 (`namespace="AWS/ApplicationELB"`, `metric_name="HTTPCode_ELB_4XX_Count"`, `dimension_key="LoadBalancer"`, `stat="Sum"`, `comparison="GreaterThanThreshold"`, `period=60`, `evaluation_periods=1`)
    - `common/alarm_manager.py`: `_ALB_ALARMS`에 TargetConnectionError 알람 정의 추가 (`namespace="AWS/ApplicationELB"`, `metric_name="TargetConnectionErrorCount"`, `dimension_key="LoadBalancer"`, `stat="Sum"`, `comparison="GreaterThanThreshold"`, `period=60`, `evaluation_periods=1`)
    - `common/alarm_manager.py`: `_HARDCODED_METRIC_KEYS["ALB"]`에 `"ELB4XX"`, `"TargetConnectionError"` 추가
    - `common/alarm_manager.py`: `_metric_name_to_key` 매핑에 `"HTTPCode_ELB_4XX_Count": "ELB4XX"`, `"TargetConnectionErrorCount": "TargetConnectionError"` 추가
    - 실행 → 통과 확인
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 1.3 Refactor: ALB 테스트 정리 및 전체 테스트 재실행
    - 기존 `test_alb_extracts_dimension_from_arn` 테스트의 기대 알람 수를 5로 업데이트 (ELB4XX, TargetConnectionError 추가)
    - ALB 새 알람의 `LoadBalancer` 단일 디멘션 검증 (TargetGroup 디멘션 미포함 확인)
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 1.2, 2.2, 6.1, 6.2_

- [x] 2. Checkpoint — ALB 확장 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. RDS 기본 알람 확장 — ConnectionAttempts
  - [x] 3.1 Red: `tests/test_alarm_manager.py`에 RDS ConnectionAttempts 실패 테스트 작성
    - `test_get_alarm_defs_rds` 기대 개수를 7로, 기대 메트릭 집합에 `ConnectionAttempts` 추가
    - `_HARDCODED_METRIC_KEYS["RDS"]`가 `{"CPU", "FreeMemoryGB", "FreeStorageGB", "Connections", "ReadLatency", "WriteLatency", "ConnectionAttempts"}` 검증
    - `_METRIC_DISPLAY["ConnectionAttempts"]` == `("ConnectionAttempts", ">", "")` 검증
    - `_metric_name_to_key("ConnectionAttempts")` == `"ConnectionAttempts"` 검증
    - `HARDCODED_DEFAULTS["ConnectionAttempts"]` == `500.0` 검증
    - ConnectionAttempts 알람: `dimension_key` == `"DBInstanceIdentifier"`, `stat` == `"Sum"`, `comparison` == `"GreaterThanThreshold"`, `namespace` == `"AWS/RDS"` 검증
    - 실행 → 실패 확인
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 3.2 Green: RDS ConnectionAttempts 데이터 정의 추가
    - `common/__init__.py`: `HARDCODED_DEFAULTS`에 `"ConnectionAttempts": 500.0` 추가
    - `common/alarm_manager.py`: `_METRIC_DISPLAY`에 `"ConnectionAttempts": ("ConnectionAttempts", ">", "")` 추가
    - `common/alarm_manager.py`: `_RDS_ALARMS`에 ConnectionAttempts 알람 정의 추가 (`namespace="AWS/RDS"`, `metric_name="ConnectionAttempts"`, `dimension_key="DBInstanceIdentifier"`, `stat="Sum"`, `comparison="GreaterThanThreshold"`, `period=300`, `evaluation_periods=1`)
    - `common/alarm_manager.py`: `_HARDCODED_METRIC_KEYS["RDS"]`에 `"ConnectionAttempts"` 추가
    - `common/alarm_manager.py`: `_metric_name_to_key` 매핑에 `"ConnectionAttempts": "ConnectionAttempts"` 추가
    - 실행 → 통과 확인
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 3.3 Refactor: RDS 테스트 정리 및 전체 테스트 재실행
    - 기존 `test_rds_creates_four_alarms` 테스트의 기대 알람 수를 7로 업데이트 (ConnectionAttempts 추가)
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 3.1, 6.3_

- [x] 4. Checkpoint — RDS 확장 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. 동적 태그 호환성 검증
  - [x] 5.1 `tests/test_alarm_manager.py`에 동적 태그 제외 테스트 추가
    - 새 하드코딩 키(`ELB4XX`, `TargetConnectionError`, `ConnectionAttempts`)에 대해 `Threshold_{key}` 태그가 있을 때 `_parse_threshold_tags()`가 해당 키를 결과에서 제외하는지 검증
    - 하드코딩 키가 아닌 동적 메트릭 태그는 정상 반환되는지 검증
    - _Requirements: 4.1, 4.2, 4.3_

- [x] 6. Checkpoint — 전체 데이터 정의 및 단위 테스트 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Property-Based Tests 작성
  - [x]* 7.1 PBT Property 1: 알람 정의 완전성 (Alarm Definition Completeness)
    - **Property 1: 알람 정의 완전성**
    - **Validates: Requirements 1.1, 2.1, 3.1, 6.1**
    - 파일: `tests/test_pbt_expand_alb_rds_metrics.py`
    - `hypothesis.strategies.sampled_from(["ALB", "RDS"])`로 랜덤 리소스 유형 생성
    - `_get_alarm_defs(resource_type)` 반환값의 메트릭 키 집합이 기대 집합의 상위집합인지 검증
    - ALB: `{RequestCount, ELB5XX, TargetResponseTime, ELB4XX, TargetConnectionError}` 포함 확인
    - RDS: `{CPU, FreeMemoryGB, FreeStorageGB, Connections, ReadLatency, WriteLatency, ConnectionAttempts}` 포함 확인
    - 각 알람 정의에 `namespace`, `metric_name`, `dimension_key`, `stat`, `comparison` 필드 존재 검증

  - [x]* 7.2 PBT Property 2: ALB LB 레벨 메트릭 단일 디멘션 (ALB LB-Level Single Dimension)
    - **Property 2: ALB LB 레벨 단일 디멘션**
    - **Validates: Requirements 1.2, 2.2, 6.2**
    - 파일: `tests/test_pbt_expand_alb_rds_metrics.py`
    - 랜덤 ALB ARN 생성 (`hypothesis.strategies.text` 기반 ARN suffix)
    - `dimension_key == "LoadBalancer"`인 ALB 알람 정의(ELB4XX, TargetConnectionError 포함)에 대해 `_build_dimensions()` 호출
    - 결과 디멘션이 `LoadBalancer` 단일이고 `TargetGroup` 미포함 검증

  - [x]* 7.3 PBT Property 3: 태그 임계치 오버라이드 (Tag Threshold Override)
    - **Property 3: 태그 임계치 오버라이드**
    - **Validates: Requirements 4.1**
    - 파일: `tests/test_pbt_expand_alb_rds_metrics.py`
    - 새 하드코딩 메트릭 키(`ELB4XX`, `TargetConnectionError`, `ConnectionAttempts`) 중 랜덤 선택 + 랜덤 양수 float 임계치 생성
    - `Threshold_{metric_key}` 태그 설정 후 `get_threshold()` 호출
    - 반환값이 태그 값과 일치하는지 검증 (하드코딩 기본값이 아닌)

  - [x]* 7.4 PBT Property 4: 동적 태그 하드코딩 키 제외 (Dynamic Tag Hardcoded Key Exclusion)
    - **Property 4: 동적 태그 하드코딩 키 제외**
    - **Validates: Requirements 4.2**
    - 파일: `tests/test_pbt_expand_alb_rds_metrics.py`
    - 랜덤 리소스 유형(ALB/RDS) + 하드코딩 키와 비하드코딩 키를 혼합한 `Threshold_*` 태그 집합 생성
    - `_parse_threshold_tags()` 호출 결과에 하드코딩 키가 포함되지 않는지 검증
    - 비하드코딩 키만 결과에 포함되는지 검증

- [x] 8. Final checkpoint — 전체 테스트 통과 확인
  - 전체 단위 테스트 + PBT 테스트 재실행
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- `*` 표시된 태스크는 선택적이며 빠른 MVP를 위해 건너뛸 수 있음
- 각 태스크는 특정 요구사항을 참조하여 추적 가능
- 기존 헬퍼 함수(`_build_dimensions`, `_create_standard_alarm`, `_parse_threshold_tags`, `_pretty_alarm_name`)는 변경하지 않음
- `expand-default-alarms` 스펙의 TDD 패턴을 그대로 따름
- PBT 테스트는 설계 문서의 Correctness Properties 4개를 모두 커버
