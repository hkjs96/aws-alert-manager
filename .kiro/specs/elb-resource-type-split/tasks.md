# Implementation Plan: ELB Resource Type Split

## Overview

기존 `resource_type="ELB"`를 `"ALB"`, `"NLB"`, `"TG"`로 세분화하여 알람 이름에서 리소스 유형을 구분하고, 기존 `[ELB]` 알람을 자동 마이그레이션한다. TDD 사이클(레드-그린-리팩터링)을 준수하며, 기존 263개 테스트 회귀 없이 진행한다.

## Tasks

- [x] 1. `common/__init__.py` 상수 및 타입 업데이트
  - `SUPPORTED_RESOURCE_TYPES`를 `["EC2", "RDS", "ALB", "NLB", "TG"]`로 변경 (`"ELB"` 제거)
  - `ResourceInfo`, `AlertMessage`, `RemediationAlertMessage`, `LifecycleAlertMessage`의 `type` 주석을 `"EC2" | "RDS" | "ALB" | "NLB" | "TG"`로 업데이트
  - NLB 메트릭 하드코딩 기본값 추가: `"ProcessedBytes"`, `"ActiveFlowCount"`, `"NewFlowCount"` → `HARDCODED_DEFAULTS`에 추가
  - _Requirements: 7.1_

- [x] 2. ELB Collector `resource_type` 세분화 (`common/collectors/elb.py`)
  - [x] 2.1 테스트 작성: ALB 수집 시 `type="ALB"`, NLB 수집 시 `type="NLB"` 반환 검증
    - `tests/test_collectors.py`에 `TestELBCollector` 클래스에 테스트 추가
    - ALB(`Type=application`) → `ResourceInfo.type == "ALB"` 검증
    - NLB(`Type=network`) → `ResourceInfo.type == "NLB"` 검증
    - TG → `ResourceInfo.type == "TG"` 유지 검증
    - _Requirements: 1.1, 2.1, 3.1_

  - [x] 2.2 `collect_monitored_resources()` 구현 변경
    - `lb.get("Type")` 기반으로 `"ALB"` 또는 `"NLB"` 설정 (기존 `"ELB"` 대체)
    - TG는 기존 `"TG"` 유지
    - _Requirements: 1.1, 2.1, 3.1_

  - [ ]* 2.3 Property 1 테스트: Collector 리소스 타입 매핑 정확성
    - **Property 1: Collector 리소스 타입 매핑 정확성**
    - **Validates: Requirements 1.1, 2.1, 3.1**
    - 테스트 파일: `tests/test_pbt_elb_type_split.py`
    - hypothesis 전략: LB 타입(application/network) + TG 조합 생성, collector 출력의 type 필드 검증

- [x] 3. Alarm Manager 알람 정의 분리 및 상수 매핑 업데이트 (`common/alarm_manager.py`)
  - [x] 3.1 테스트 작성: `_get_alarm_defs("ALB"/"NLB"/"TG")` 반환값 검증
    - `tests/test_alarm_manager.py`에 테스트 추가
    - `_get_alarm_defs("ALB")` → `RequestCount` (AWS/ApplicationELB) 반환
    - `_get_alarm_defs("NLB")` → `ProcessedBytes`, `ActiveFlowCount`, `NewFlowCount` (AWS/NetworkELB) 반환
    - `_get_alarm_defs("TG")` → `RequestCount`, `HealthyHostCount` 반환
    - `_get_alarm_defs("ELB")` → 빈 리스트 반환 (제거됨)
    - `_HARDCODED_METRIC_KEYS`, `_NAMESPACE_MAP`, `_DIMENSION_KEY_MAP` 매핑 검증
    - _Requirements: 4.1, 4.2, 4.3, 7.2, 7.3, 7.4_

  - [x] 3.2 알람 정의 구현 변경
    - `_ELB_ALARMS` → `_ALB_ALARMS` + `_NLB_ALARMS` + `_TG_ALARMS` 분리
    - `_NLB_ALARMS`: `ProcessedBytes`(Sum), `ActiveFlowCount`(Average), `NewFlowCount`(Sum) — `AWS/NetworkELB`, `dimension_key="LoadBalancer"`
    - `_TG_ALARMS`: `RequestCount`(Sum), `HealthyHostCount`(Average) — `dimension_key="TargetGroup"`, TG에 연결된 LB 타입 기반 네임스페이스
    - `_get_alarm_defs()`: `"ALB"`, `"NLB"`, `"TG"` 분기 추가, `"ELB"` 제거
    - `_HARDCODED_METRIC_KEYS`: `"ELB"` → `"ALB"`, `"NLB"`, `"TG"` 키 분리
    - `_NAMESPACE_MAP`: `"ELB"` → `"ALB": ["AWS/ApplicationELB"]`, `"NLB": ["AWS/NetworkELB"]`, `"TG": ["AWS/ApplicationELB", "AWS/NetworkELB"]`
    - `_DIMENSION_KEY_MAP`: `"ELB"` → `"ALB": "LoadBalancer"`, `"NLB": "LoadBalancer"`, `"TG": "TargetGroup"`
    - `_create_standard_alarm()`: `resource_type`이 `"ALB"`, `"NLB"`, `"TG"` 중 하나이고 `dimension_key`가 `"LoadBalancer"` 또는 `"TargetGroup"`이면 ARN suffix 추출
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 7.2, 7.3, 7.4_

  - [ ]* 3.3 Property 2 테스트: 알람 이름 prefix와 resource_type 일치
    - **Property 2: 알람 이름 prefix와 resource_type 일치**
    - **Validates: Requirements 1.2, 2.2, 3.2**
    - 테스트 파일: `tests/test_pbt_elb_type_split.py`
    - hypothesis 전략: resource_type ∈ {ALB, NLB, TG} × 랜덤 resource_id, resource_name, metric, threshold 생성
    - `_pretty_alarm_name()` 반환값이 `[{resource_type}] `로 시작하고 `({resource_id})`로 끝나는지 검증

- [x] 4. Alarm Manager 레거시 `[ELB]` 호환 및 마이그레이션 (`common/alarm_manager.py`)
  - [x] 4.1 테스트 작성: `_find_alarms_for_resource()`가 `[ELB] ` prefix도 검색
    - `tests/test_alarm_manager.py`에 테스트 추가
    - `resource_type="ALB"` 또는 `"NLB"`일 때 `[ELB] ` prefix 알람도 검색 결과에 포함되는지 검증
    - _Requirements: 5.1, 5.2_

  - [x] 4.2 `_find_alarms_for_resource()` 레거시 호환 구현
    - `resource_type`이 `"ALB"` 또는 `"NLB"`일 때 `[ELB] ` prefix도 추가 검색
    - 기존 `type_prefixes` 로직에 `[ELB] ` 추가
    - _Requirements: 5.1, 5.2_

- [x] 5. Checkpoint — 기존 테스트 + 새 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. `common/tag_resolver.py` ALB/NLB 호환 업데이트
  - [x] 6.1 테스트 작성: `get_resource_tags("ALB"/"NLB")` → `_get_elbv2_tags()` 호출 검증
    - 기존 `tests/` 내 tag_resolver 테스트 파일 또는 `tests/test_alarm_manager.py`에 추가
    - _Requirements: 9.2_

  - [x] 6.2 `get_resource_tags()` 분기 업데이트
    - `resource_type in ("ELB", "TG", "ALB", "NLB")` → `_get_elbv2_tags()` 호출
    - _Requirements: 9.2_

- [x] 7. Daily Monitor 고아 알람 정리 업데이트 (`daily_monitor/lambda_handler.py`)
  - [x] 7.1 테스트 작성: `_classify_alarm()` [ALB]/[NLB] prefix 분류 검증
    - `tests/test_daily_monitor.py`의 `TestClassifyAlarm`에 테스트 추가
    - `[ALB] ... (arn)` → `result["ALB"]`에 분류
    - `[NLB] ... (arn)` → `result["NLB"]`에 분류
    - 기존 `[ELB]`, `[TG]` 분류 유지 검증
    - _Requirements: 8.1, 8.2, 8.3, 5.3_

  - [x] 7.2 테스트 작성: `alive_checkers`에 `"ALB"`, `"NLB"` 키 존재 검증
    - `tests/test_daily_monitor.py`에 테스트 추가
    - `"ALB"` → `_find_alive_elb_resources` 연결 검증
    - `"NLB"` → `_find_alive_elb_resources` 연결 검증
    - _Requirements: 8.4_

  - [x] 7.3 `_classify_alarm()` 및 `alive_checkers` 구현 변경
    - `_classify_alarm()`: 기존 `_NEW_FORMAT_RE`가 `[ALB]`, `[NLB]`를 이미 매칭하므로 변경 불필요 (검증만)
    - `alive_checkers` 딕셔너리에 `"ALB"`, `"NLB"` 키 추가 → `_find_alive_elb_resources` 연결
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 5.3_

  - [ ]* 7.4 Property 4 테스트: 알람 분류 정확성 (새 prefix 포함)
    - **Property 4: 알람 분류 정확성 (새 prefix 포함)**
    - **Validates: Requirements 8.1, 8.2, 8.3**
    - 테스트 파일: `tests/test_pbt_elb_type_split.py`
    - hypothesis 전략: type ∈ {ALB, NLB, TG, EC2, RDS} × 랜덤 label, metric_info, resource_id로 알람 이름 생성
    - `_classify_alarm()` 출력이 올바른 resource_type과 resource_id로 분류되는지 검증

- [x] 8. Remediation Handler ALB/NLB 구분 (`remediation_handler/lambda_handler.py`)
  - [x] 8.1 테스트 작성: ARN 기반 resource_type 판별 검증
    - `tests/test_remediation_handler.py` (기존 또는 신규)에 테스트 추가
    - `loadbalancer/app/...` ARN → `resource_type="ALB"` 검증
    - `loadbalancer/net/...` ARN → `resource_type="NLB"` 검증
    - `_execute_remediation("ALB"/"NLB")` → ELBv2 `delete_load_balancer` 호출 검증
    - _Requirements: 9.1_

  - [x] 8.2 `_API_MAP` 및 `_execute_remediation()` 구현 변경
    - ELB 관련 `_API_MAP` 항목: `_extract_elb_id()` 반환 후 ARN에서 `app/` → `"ALB"`, `net/` → `"NLB"` 판별하는 래퍼 함수 추가
    - `_execute_remediation()`: `"ALB"`, `"NLB"` 처리 추가 (ELBv2 `delete_load_balancer` 호출)
    - `_remediation_action_name()`: `"ALB"`, `"NLB"` → `"DELETED"` 매핑 추가
    - _Requirements: 9.1_

  - [ ]* 8.3 Property 5 테스트: ARN 기반 resource_type 판별
    - **Property 5: ARN 기반 resource_type 판별**
    - **Validates: Requirements 9.1**
    - 테스트 파일: `tests/test_pbt_elb_type_split.py`
    - hypothesis 전략: 랜덤 ALB/NLB ARN 생성 (`loadbalancer/app/...` 또는 `loadbalancer/net/...`)
    - 파싱 결과 resource_type이 `"ALB"` 또는 `"NLB"`인지 검증

- [x] 9. Checkpoint — 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. 기존 PBT 확장 및 추가 Property 테스트
  - [x]* 10.1 Property 3 테스트: 새 리소스 타입에 대한 알람 이름 255자 제한
    - **Property 3: 새 리소스 타입에 대한 알람 이름 255자 제한**
    - **Validates: Requirements 6.1, 6.2**
    - `tests/test_pbt_alarm_name_constraint.py`의 `resource_types` 전략에 `"ALB"`, `"NLB"`, `"TG"` 추가
    - 기존 255자 제한 + resource_id 보존 테스트가 새 타입에도 적용되는지 검증

  - [x]* 10.2 Property 6 테스트: ARN suffix 디멘션 추출 일관성
    - **Property 6: ARN suffix 디멘션 추출 일관성**
    - **Validates: Requirements 4.4**
    - 테스트 파일: `tests/test_pbt_elb_type_split.py`
    - hypothesis 전략: 랜덤 ALB/NLB ARN 생성
    - `_extract_elb_dimension()` 반환값이 `loadbalancer/` 이후 suffix와 일치하는지 검증

- [x] 11. 통합 와이어링 및 마이그레이션 검증
  - [x] 11.1 마이그레이션 시나리오 테스트 작성
    - `tests/test_alarm_manager.py`에 마이그레이션 테스트 추가
    - 기존 `[ELB]` 알람이 `sync_alarms_for_resource()` 호출 시 `[ALB]`/`[NLB]` 알람으로 교체되는 시나리오 검증
    - 레거시 + 새 포맷 알람 혼재 시 중복 없이 처리되는 시나리오 검증
    - _Requirements: 5.1, 5.2_

  - [x] 11.2 Daily Monitor `_process_resource()` ALB/NLB 호환 검증
    - `tests/test_daily_monitor.py`에 테스트 추가
    - `resource_type="ALB"` 또는 `"NLB"` 리소스에 대해 `get_metrics` 정상 호출 검증
    - _Requirements: 1.2, 2.2_

- [x] 12. Final checkpoint — 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- TDD 사이클 준수: 각 구현 태스크에서 테스트 먼저 작성 (레드) → 최소 구현 (그린) → 리팩터링
- 기존 263개 테스트 회귀 없이 진행
- Property tests validate universal correctness properties from design document
- Checkpoints ensure incremental validation
