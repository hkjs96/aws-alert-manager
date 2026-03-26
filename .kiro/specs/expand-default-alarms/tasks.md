# Implementation Plan: 기본 알람 정의 확장 (expand-default-alarms)

## Overview

리소스 유형별 하드코딩 기본 알람 정의를 확장한다. 데이터 전용 변경이며, 기존 헬퍼 함수(`_build_dimensions`, `_resolve_tg_namespace`, `_create_standard_alarm`, `_parse_threshold_tags`)는 수정하지 않는다. TDD 레드-그린-리팩터링 사이클(거버넌스 §8)을 리소스 유형별로 반복한다.

변경 파일: `common/alarm_manager.py`, `common/__init__.py`, `tests/test_alarm_manager.py`, `tests/test_pbt_expand_alarm_defs.py`

## Tasks

- [x] 1. EC2 기본 알람 확장 — StatusCheckFailed
  - [x] 1.1 Red: `tests/test_alarm_manager.py`에 EC2 StatusCheckFailed 실패 테스트 작성
    - `test_get_alarm_defs_ec2` 기대 개수를 4로, 기대 메트릭 집합에 `StatusCheckFailed` 추가
    - `_HARDCODED_METRIC_KEYS["EC2"]`에 `StatusCheckFailed` 포함 검증
    - `_METRIC_DISPLAY["StatusCheckFailed"]` == `("StatusCheckFailed", ">", "")` 검증
    - `_metric_name_to_key("StatusCheckFailed")` == `"StatusCheckFailed"` 검증
    - `HARDCODED_DEFAULTS["StatusCheckFailed"]` == `0.0` 검증
    - StatusCheckFailed 알람 정의의 `stat` == `"Maximum"`, `comparison` == `"GreaterThanThreshold"`, `namespace` == `"AWS/EC2"`, `dimension_key` == `"InstanceId"` 검증
    - 실행 → 실패 확인
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 1.2 Green: EC2 StatusCheckFailed 데이터 정의 추가
    - `common/__init__.py`: `HARDCODED_DEFAULTS`에 `"StatusCheckFailed": 0.0` 추가
    - `common/alarm_manager.py`: `_METRIC_DISPLAY`에 `"StatusCheckFailed": ("StatusCheckFailed", ">", "")` 추가
    - `common/alarm_manager.py`: `_EC2_ALARMS`에 StatusCheckFailed 알람 정의 딕셔너리 추가 (`namespace="AWS/EC2"`, `metric_name="StatusCheckFailed"`, `dimension_key="InstanceId"`, `stat="Maximum"`, `comparison="GreaterThanThreshold"`, `period=300`, `evaluation_periods=1`)
    - `common/alarm_manager.py`: `_HARDCODED_METRIC_KEYS["EC2"]`에 `"StatusCheckFailed"` 추가
    - `common/alarm_manager.py`: `_metric_name_to_key` 매핑에 `"StatusCheckFailed": "StatusCheckFailed"` 추가
    - 실행 → 통과 확인
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 1.3 Refactor: EC2 테스트 정리 및 전체 테스트 재실행
    - 기존 `test_ec2_creates_cpu_memory_disk_alarms` 테스트의 기대 알람 수를 4로 업데이트 (StatusCheckFailed 추가)
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 3.1_

- [x] 2. RDS 기본 알람 확장 — ReadLatency, WriteLatency
  - [x] 2.1 Red: `tests/test_alarm_manager.py`에 RDS ReadLatency/WriteLatency 실패 테스트 작성
    - `test_get_alarm_defs_rds` 기대 개수를 6으로, 기대 메트릭 집합에 `ReadLatency`, `WriteLatency` 추가
    - `_HARDCODED_METRIC_KEYS["RDS"]`에 `ReadLatency`, `WriteLatency` 포함 검증
    - `_METRIC_DISPLAY["ReadLatency"]` == `("ReadLatency", ">", "s")`, `_METRIC_DISPLAY["WriteLatency"]` == `("WriteLatency", ">", "s")` 검증
    - `_metric_name_to_key("ReadLatency")` == `"ReadLatency"`, `_metric_name_to_key("WriteLatency")` == `"WriteLatency"` 검증
    - `HARDCODED_DEFAULTS["ReadLatency"]` == `0.02`, `HARDCODED_DEFAULTS["WriteLatency"]` == `0.02` 검증
    - 각 알람 정의의 `stat` == `"Average"`, `comparison` == `"GreaterThanThreshold"`, `namespace` == `"AWS/RDS"`, `dimension_key` == `"DBInstanceIdentifier"` 검증
    - 실행 → 실패 확인
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [x] 2.2 Green: RDS ReadLatency/WriteLatency 데이터 정의 추가
    - `common/__init__.py`: `HARDCODED_DEFAULTS`에 `"ReadLatency": 0.02`, `"WriteLatency": 0.02` 추가
    - `common/alarm_manager.py`: `_METRIC_DISPLAY`에 `"ReadLatency": ("ReadLatency", ">", "s")`, `"WriteLatency": ("WriteLatency", ">", "s")` 추가
    - `common/alarm_manager.py`: `_RDS_ALARMS`에 ReadLatency, WriteLatency 알람 정의 딕셔너리 추가 (`namespace="AWS/RDS"`, `dimension_key="DBInstanceIdentifier"`, `stat="Average"`, `comparison="GreaterThanThreshold"`, `period=300`, `evaluation_periods=1`)
    - `common/alarm_manager.py`: `_HARDCODED_METRIC_KEYS["RDS"]`에 `"ReadLatency"`, `"WriteLatency"` 추가
    - `common/alarm_manager.py`: `_metric_name_to_key` 매핑에 `"ReadLatency": "ReadLatency"`, `"WriteLatency": "WriteLatency"` 추가
    - 실행 → 통과 확인
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [x] 2.3 Refactor: RDS 테스트 정리 및 전체 테스트 재실행
    - 기존 `test_rds_creates_four_alarms` 테스트의 기대 알람 수를 6으로 업데이트
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 4.1, 4.2_

- [x] 3. Checkpoint — EC2/RDS 확장 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. ALB 기본 알람 확장 — ELB5XX, TargetResponseTime
  - [x] 4.1 Red: `tests/test_alarm_manager.py`에 ALB ELB5XX/TargetResponseTime 실패 테스트 작성
    - `test_get_alarm_defs_alb` 기대 개수를 3으로, 기대 메트릭 집합에 `ELB5XX`, `TargetResponseTime` 추가
    - `_HARDCODED_METRIC_KEYS["ALB"]`가 `{"RequestCount", "ELB5XX", "TargetResponseTime"}` 검증
    - `_METRIC_DISPLAY["ELB5XX"]` == `("HTTPCode_ELB_5XX_Count", ">", "")` 검증
    - `_METRIC_DISPLAY["TargetResponseTime"]` == `("TargetResponseTime", ">", "s")` 검증
    - `_metric_name_to_key("HTTPCode_ELB_5XX_Count")` == `"ELB5XX"` 검증
    - `_metric_name_to_key("TargetResponseTime")` == `"TargetResponseTime"` 검증
    - `HARDCODED_DEFAULTS["ELB5XX"]` == `50.0`, `HARDCODED_DEFAULTS["TargetResponseTime"]` == `5.0` 검증
    - ELB5XX 알람: `dimension_key` == `"LoadBalancer"`, `stat` == `"Sum"` 검증 (LB 레벨 단일 디멘션)
    - TargetResponseTime 알람: `dimension_key` == `"LoadBalancer"`, `stat` == `"Average"` 검증 (LB 레벨)
    - 실행 → 실패 확인
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 8.4_

  - [x] 4.2 Green: ALB ELB5XX/TargetResponseTime 데이터 정의 추가
    - `common/__init__.py`: `HARDCODED_DEFAULTS`에 `"ELB5XX": 50.0`, `"TargetResponseTime": 5.0` 추가
    - `common/alarm_manager.py`: `_METRIC_DISPLAY`에 `"ELB5XX": ("HTTPCode_ELB_5XX_Count", ">", "")`, `"TargetResponseTime": ("TargetResponseTime", ">", "s")` 추가
    - `common/alarm_manager.py`: `_ALB_ALARMS`에 ELB5XX, TargetResponseTime 알람 정의 딕셔너리 추가 (`namespace="AWS/ApplicationELB"`, `dimension_key="LoadBalancer"`, `period=60`, `evaluation_periods=1`)
    - `common/alarm_manager.py`: `_HARDCODED_METRIC_KEYS["ALB"]`에 `"ELB5XX"`, `"TargetResponseTime"` 추가
    - `common/alarm_manager.py`: `_metric_name_to_key` 매핑에 `"HTTPCode_ELB_5XX_Count": "ELB5XX"`, `"TargetResponseTime": "TargetResponseTime"` 추가
    - 실행 → 통과 확인
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

  - [x] 4.3 Refactor: ALB 테스트 정리 및 전체 테스트 재실행
    - 기존 `test_alb_extracts_dimension_from_arn` 테스트의 기대 알람 수를 3으로 업데이트
    - ALB 새 알람의 `LoadBalancer` 단일 디멘션 검증 (TargetGroup 디멘션 미포함 확인)
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 1.3, 1.4, 8.4_

- [x] 5. NLB 기본 알람 확장 — TCPClientReset, TCPTargetReset
  - [x] 5.1 Red: `tests/test_alarm_manager.py`에 NLB TCPClientReset/TCPTargetReset 실패 테스트 작성
    - `test_get_alarm_defs_nlb` 기대 개수를 5로, 기대 메트릭 집합에 `TCPClientReset`, `TCPTargetReset` 추가
    - `_HARDCODED_METRIC_KEYS["NLB"]`가 `{"ProcessedBytes", "ActiveFlowCount", "NewFlowCount", "TCPClientReset", "TCPTargetReset"}` 검증
    - `_METRIC_DISPLAY["TCPClientReset"]` == `("TCP_Client_Reset_Count", ">", "")`, `_METRIC_DISPLAY["TCPTargetReset"]` == `("TCP_Target_Reset_Count", ">", "")` 검증
    - `_metric_name_to_key("TCP_Client_Reset_Count")` == `"TCPClientReset"`, `_metric_name_to_key("TCP_Target_Reset_Count")` == `"TCPTargetReset"` 검증
    - `HARDCODED_DEFAULTS["TCPClientReset"]` == `100.0`, `HARDCODED_DEFAULTS["TCPTargetReset"]` == `100.0` 검증
    - 각 알람: `dimension_key` == `"LoadBalancer"`, `stat` == `"Sum"`, `namespace` == `"AWS/NetworkELB"` 검증
    - 실행 → 실패 확인
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 5.2 Green: NLB TCPClientReset/TCPTargetReset 데이터 정의 추가
    - `common/__init__.py`: `HARDCODED_DEFAULTS`에 `"TCPClientReset": 100.0`, `"TCPTargetReset": 100.0` 추가
    - `common/alarm_manager.py`: `_METRIC_DISPLAY`에 `"TCPClientReset": ("TCP_Client_Reset_Count", ">", "")`, `"TCPTargetReset": ("TCP_Target_Reset_Count", ">", "")` 추가
    - `common/alarm_manager.py`: `_NLB_ALARMS`에 TCPClientReset, TCPTargetReset 알람 정의 딕셔너리 추가 (`namespace="AWS/NetworkELB"`, `dimension_key="LoadBalancer"`, `stat="Sum"`, `period=60`, `evaluation_periods=1`)
    - `common/alarm_manager.py`: `_HARDCODED_METRIC_KEYS["NLB"]`에 `"TCPClientReset"`, `"TCPTargetReset"` 추가
    - `common/alarm_manager.py`: `_metric_name_to_key` 매핑에 `"TCP_Client_Reset_Count": "TCPClientReset"`, `"TCP_Target_Reset_Count": "TCPTargetReset"` 추가
    - 실행 → 통과 확인
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 5.3 Refactor: NLB 테스트 정리 및 전체 테스트 재실행
    - NLB 새 알람의 `LoadBalancer` 단일 디멘션 검증
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 2.3, 8.4_

- [x] 6. Checkpoint — ALB/NLB 확장 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. TG 기본 알람 확장 — RequestCountPerTarget, TGResponseTime
  - [x] 7.1 Red: `tests/test_alarm_manager.py`에 TG RequestCountPerTarget/TGResponseTime 실패 테스트 작성
    - `test_get_alarm_defs_tg` 기대 개수를 4로, 기대 메트릭 집합에 `RequestCountPerTarget`, `TGResponseTime` 추가
    - `_HARDCODED_METRIC_KEYS["TG"]`가 `{"HealthyHostCount", "UnHealthyHostCount", "RequestCountPerTarget", "TGResponseTime"}` 검증
    - `_METRIC_DISPLAY["RequestCountPerTarget"]` == `("RequestCountPerTarget", ">", "")` 검증
    - `_METRIC_DISPLAY["TGResponseTime"]` == `("TargetResponseTime", ">", "s")` 검증 (CloudWatch 메트릭 이름은 `TargetResponseTime`, 내부 키는 `TGResponseTime`)
    - `_metric_name_to_key("RequestCountPerTarget")` == `"RequestCountPerTarget"` 검증
    - `HARDCODED_DEFAULTS["RequestCountPerTarget"]` == `1000.0`, `HARDCODED_DEFAULTS["TGResponseTime"]` == `5.0` 검증
    - RequestCountPerTarget 알람: `dimension_key` == `"TargetGroup"`, `stat` == `"Sum"` 검증 (TG 레벨 → `_build_dimensions`가 복합 디멘션 생성)
    - TGResponseTime 알람: `dimension_key` == `"TargetGroup"`, `stat` == `"Average"` 검증
    - 실행 → 실패 확인
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.7, 5.8, 5.9, 5.10_

  - [x] 7.2 Green: TG RequestCountPerTarget/TGResponseTime 데이터 정의 추가
    - `common/__init__.py`: `HARDCODED_DEFAULTS`에 `"RequestCountPerTarget": 1000.0`, `"TGResponseTime": 5.0` 추가
    - `common/alarm_manager.py`: `_METRIC_DISPLAY`에 `"RequestCountPerTarget": ("RequestCountPerTarget", ">", "")`, `"TGResponseTime": ("TargetResponseTime", ">", "s")` 추가
    - `common/alarm_manager.py`: `_TG_ALARMS`에 RequestCountPerTarget, TGResponseTime 알람 정의 딕셔너리 추가 (`namespace="AWS/ApplicationELB"`, `dimension_key="TargetGroup"`, `period=60`, `evaluation_periods=1`)
    - `common/alarm_manager.py`: `_HARDCODED_METRIC_KEYS["TG"]`에 `"RequestCountPerTarget"`, `"TGResponseTime"` 추가
    - `common/alarm_manager.py`: `_metric_name_to_key` 매핑에 `"RequestCountPerTarget": "RequestCountPerTarget"` 추가 (TGResponseTime은 메타데이터 기반 해석이므로 매핑 불필요)
    - 실행 → 통과 확인
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.7, 5.8, 5.9, 5.10_

  - [x] 7.3 Refactor: TG 테스트 정리 및 전체 테스트 재실행
    - TG 새 알람의 `TargetGroup` + `LoadBalancer` 복합 디멘션 검증 테스트 추가
    - TG 새 알람의 NLB TG 네임스페이스 동적 결정 검증 (`_lb_type == "network"` → `AWS/NetworkELB`)
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 5.3, 5.4, 5.5, 5.6, 8.2, 8.5_

- [x] 8. 동적 태그 호환성 검증
  - [x] 8.1 `tests/test_alarm_manager.py`에 동적 태그 제외 테스트 추가
    - 새 하드코딩 키(`ELB5XX`, `TargetResponseTime`, `TCPClientReset`, `TCPTargetReset`, `StatusCheckFailed`, `ReadLatency`, `WriteLatency`, `RequestCountPerTarget`, `TGResponseTime`)에 대해 `Threshold_{key}` 태그가 있을 때 `_parse_threshold_tags()`가 해당 키를 결과에서 제외하는지 검증
    - 하드코딩 키가 아닌 동적 메트릭 태그는 정상 반환되는지 검증
    - _Requirements: 6.1, 6.2, 6.3_

- [x] 9. Checkpoint — 전체 데이터 정의 및 단위 테스트 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Property-Based Tests 작성
  - [ ]* 10.1 PBT Property 1: 알람 정의 완전성 (Alarm Definition Completeness)
    - **Property 1: 알람 정의 완전성**
    - **Validates: Requirements 1.1, 1.2, 2.1, 2.2, 3.1, 4.1, 4.2, 5.1, 5.2, 6.3**
    - 파일: `tests/test_pbt_expand_alarm_defs.py`
    - `hypothesis.strategies.sampled_from(["EC2", "RDS", "ALB", "NLB", "TG"])`로 랜덤 리소스 유형 생성
    - `_get_alarm_defs(resource_type)` 반환값의 메트릭 키 집합이 기대 집합의 상위집합인지 검증
    - 각 알람 정의에 `namespace`, `metric_name`, `dimension_key`, `stat`, `comparison` 필드 존재 검증

  - [ ]* 10.2 PBT Property 2: LB 레벨 메트릭 단일 디멘션 (LB-Level Single Dimension)
    - **Property 2: LB 레벨 단일 디멘션**
    - **Validates: Requirements 1.3, 1.4, 2.3, 8.4**
    - 파일: `tests/test_pbt_expand_alarm_defs.py`
    - 랜덤 ALB/NLB ARN 생성 (`hypothesis.strategies.text` 기반 ARN suffix)
    - `dimension_key == "LoadBalancer"`인 알람 정의에 대해 `_build_dimensions()` 호출
    - 결과 디멘션이 `LoadBalancer` 단일이고 `TargetGroup` 미포함 검증

  - [ ]* 10.3 PBT Property 3: TG 메트릭 복합 디멘션 (TG Compound Dimension)
    - **Property 3: TG 복합 디멘션**
    - **Validates: Requirements 5.3, 5.4, 8.2, 8.5**
    - 파일: `tests/test_pbt_expand_alarm_defs.py`
    - 랜덤 TG ARN + LB ARN 조합 생성
    - 모든 TG 알람 정의(`RequestCountPerTarget`, `TGResponseTime` 포함)에 대해 `_build_dimensions()` 호출
    - 결과에 `TargetGroup` + `LoadBalancer` 복합 디멘션 존재 검증

  - [ ]* 10.4 PBT Property 4: TG 네임스페이스 동적 결정 (TG Namespace Resolution)
    - **Property 4: TG 네임스페이스 동적 결정**
    - **Validates: Requirements 5.5, 5.6**
    - 파일: `tests/test_pbt_expand_alarm_defs.py`
    - `_lb_type`을 `hypothesis.strategies.sampled_from(["network", "application", ""])` + 미포함 케이스로 생성
    - 모든 TG 알람 정의에 대해 `_resolve_tg_namespace()` 호출
    - `_lb_type == "network"` → `"AWS/NetworkELB"`, 그 외 → `"AWS/ApplicationELB"` 검증

  - [ ]* 10.5 PBT Property 5: 태그 임계치 오버라이드 (Tag Threshold Override)
    - **Property 5: 태그 임계치 오버라이드**
    - **Validates: Requirements 6.1**
    - 파일: `tests/test_pbt_expand_alarm_defs.py`
    - 새 하드코딩 메트릭 키 중 랜덤 선택 + 랜덤 양수 float 임계치 생성
    - `Threshold_{metric_key}` 태그 설정 후 `get_threshold()` 호출
    - 반환값이 태그 값과 일치하는지 검증 (하드코딩 기본값이 아닌)

  - [ ]* 10.6 PBT Property 6: 동적 태그 하드코딩 키 제외 (Dynamic Tag Hardcoded Key Exclusion)
    - **Property 6: 동적 태그 하드코딩 키 제외**
    - **Validates: Requirements 6.2**
    - 파일: `tests/test_pbt_expand_alarm_defs.py`
    - 랜덤 리소스 유형 + 하드코딩 키와 비하드코딩 키를 혼합한 `Threshold_*` 태그 집합 생성
    - `_parse_threshold_tags()` 호출 결과에 하드코딩 키가 포함되지 않는지 검증
    - 비하드코딩 키만 결과에 포함되는지 검증

- [x] 11. Final checkpoint — 전체 테스트 통과 확인
  - 전체 단위 테스트 + PBT 테스트 재실행
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- `*` 표시된 태스크는 선택적이며 빠른 MVP를 위해 건너뛸 수 있음
- 각 태스크는 특정 요구사항을 참조하여 추적 가능
- 기존 헬퍼 함수(`_build_dimensions`, `_resolve_tg_namespace`, `_create_standard_alarm`, `_parse_threshold_tags`)는 변경하지 않음
- TG `TargetResponseTime`은 내부 키 `TGResponseTime`을 사용하여 ALB 레벨 `TargetResponseTime`과 충돌 방지
- `StatusCheckFailed` 기본 임계치는 `0.0` (`GreaterThanThreshold` → 값 > 0이면 알람 발생)
- `HTTPCode_ELB_5XX_Count`는 LB 레벨 전용 (`LoadBalancer` 단일 디멘션)
