# Implementation Plan: Aurora RDS Monitoring

## Overview

Add Aurora RDS as a new monitored resource type (`"AuroraRDS"`) by extending existing modules. The RDS collector gains Aurora classification and metric collection, the alarm manager gains `_AURORA_RDS_ALARMS`, and daily monitor / remediation handler gain `"AuroraRDS"` routing. TDD 사이클(레드-그린-리팩터링)을 준수하며, 기존 테스트 회귀 없이 진행한다.

## Tasks

- [ ] 1. `common/__init__.py` 상수 및 타입 업데이트
  - Add `"AuroraRDS"` to `SUPPORTED_RESOURCE_TYPES`
  - Add `"FreeLocalStorageGB": 10.0` and `"ReplicaLag": 2000000.0` to `HARDCODED_DEFAULTS`
  - Update TypedDict comments for `ResourceInfo`, `AlertMessage`, `RemediationAlertMessage`, `LifecycleAlertMessage` to include `"AuroraRDS"`
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 11.1, 11.2, 11.3, 11.4_

- [ ] 2. RDS Collector Aurora 분류 및 메트릭 수집 (`common/collectors/rds.py`)
  - [ ] 2.1 테스트 작성: `collect_monitored_resources()` Aurora 분류 검증
    - `tests/test_collectors.py`에 테스트 추가
    - Engine `"aurora-mysql"` → `type="AuroraRDS"` 검증
    - Engine `"aurora-postgresql"` → `type="AuroraRDS"` 검증
    - Engine `"mysql"` → `type="RDS"` 유지 검증
    - Engine `"aurora"` → `type="AuroraRDS"` 검증
    - deleting/deleted Aurora 인스턴스 skip 검증
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [ ] 2.2 `collect_monitored_resources()` Aurora 분류 구현
    - `db["Engine"]` 검사: `"aurora" in engine.lower()` → `type="AuroraRDS"`, else `type="RDS"`
    - Skip 로직 및 Monitoring=on 태그 체크는 기존 로직 유지
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [ ]* 2.3 Property 1 테스트: Engine 기반 Aurora 분류
    - **Property 1: Engine-based Aurora Classification**
    - **Validates: Requirements 1.1, 1.2, 1.3**
    - 테스트 파일: `tests/test_pbt_aurora_rds.py`
    - hypothesis 전략: 랜덤 engine 문자열 생성 (aurora 포함/미포함), 분류 결과가 substring 체크와 일치하는지 검증

  - [ ] 2.4 테스트 작성: `get_aurora_metrics()` 메트릭 수집 검증
    - `tests/test_collectors.py`에 테스트 추가
    - Mock CloudWatch에 5개 메트릭 데이터 설정 → 반환 키/값 검증
    - `FreeableMemory` bytes→GB 변환 검증, `FreeLocalStorage` bytes→GB 변환 검증
    - `AuroraReplicaLagMaximum` raw μs 반환 검증
    - 개별 메트릭 데이터 없을 때 skip 검증, 전체 없을 때 None 반환 검증
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [ ] 2.5 `get_aurora_metrics()` 구현
    - 5개 CloudWatch 메트릭 조회: CPUUtilization→"CPU", FreeableMemory→"FreeMemoryGB" (bytes/1073741824), DatabaseConnections→"Connections", FreeLocalStorage→"FreeLocalStorageGB" (bytes/1073741824), AuroraReplicaLagMaximum→"ReplicaLag"
    - 기존 `_collect_metric()` 헬퍼 및 `query_metric()` 재사용
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [ ]* 2.6 Property 2 테스트: Bytes-to-GB 변환 일관성
    - **Property 2: Bytes-to-GB Conversion Consistency**
    - **Validates: Requirements 2.4, 2.6, 4.2, 4.3**
    - 테스트 파일: `tests/test_pbt_aurora_rds.py`
    - hypothesis 전략: 랜덤 양의 float 생성, `transform_threshold(value / BYTES_PER_GB) ≈ value` round-trip 검증

- [ ] 3. Checkpoint — Collector 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Alarm Manager Aurora 알람 정의 (`common/alarm_manager.py`)
  - [ ] 4.1 테스트 작성: `_AURORA_RDS_ALARMS` 및 `_get_alarm_defs("AuroraRDS")` 검증
    - `tests/test_alarm_manager.py`에 테스트 추가
    - `_get_alarm_defs("AuroraRDS")` → 5개 정의 반환 검증 (CPU, FreeMemoryGB, Connections, FreeLocalStorageGB, ReplicaLag)
    - 각 정의의 namespace, dimension_key, comparison, stat, transform_threshold 검증
    - ReplicaLag: stat="Maximum", comparison="GreaterThanThreshold" 검증
    - FreeLocalStorageGB: transform_threshold(10.0) == 10737418240 검증
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [ ] 4.2 `_AURORA_RDS_ALARMS` 상수 및 `_get_alarm_defs()` 분기 구현
    - 5개 알람 정의 추가 (design §2 참조)
    - `_get_alarm_defs()`: `elif resource_type == "AuroraRDS": return _AURORA_RDS_ALARMS`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [ ] 4.3 테스트 작성: 상수 매핑 업데이트 검증
    - `_HARDCODED_METRIC_KEYS["AuroraRDS"]` == `{"CPU", "FreeMemoryGB", "Connections", "FreeLocalStorageGB", "ReplicaLag"}` 검증
    - `_NAMESPACE_MAP["AuroraRDS"]` == `["AWS/RDS"]` 검증
    - `_DIMENSION_KEY_MAP["AuroraRDS"]` == `"DBInstanceIdentifier"` 검증
    - `_METRIC_DISPLAY` FreeLocalStorageGB, ReplicaLag 엔트리 검증
    - `_metric_name_to_key("FreeLocalStorage")` == `"FreeLocalStorageGB"` 검증
    - `_metric_name_to_key("AuroraReplicaLagMaximum")` == `"ReplicaLag"` 검증
    - _Requirements: 5.3, 5.4_

  - [ ] 4.4 상수 매핑 구현
    - `_HARDCODED_METRIC_KEYS`: `"AuroraRDS"` 키 추가
    - `_NAMESPACE_MAP`: `"AuroraRDS": ["AWS/RDS"]` 추가
    - `_DIMENSION_KEY_MAP`: `"AuroraRDS": "DBInstanceIdentifier"` 추가
    - `_METRIC_DISPLAY`: `"FreeLocalStorageGB": ("FreeLocalStorage", "<", "GB")`, `"ReplicaLag": ("AuroraReplicaLagMaximum", ">", "μs")` 추가
    - `_metric_name_to_key()`: `"FreeLocalStorage": "FreeLocalStorageGB"`, `"AuroraReplicaLagMaximum": "ReplicaLag"` 추가
    - _Requirements: 5.3, 5.4_

  - [ ]* 4.5 Property 3 테스트: Aurora 알람 이름 prefix 및 메타데이터
    - **Property 3: Aurora Alarm Name Prefix and Metadata**
    - **Validates: Requirements 5.1, 5.2**
    - 테스트 파일: `tests/test_pbt_aurora_rds.py`
    - hypothesis 전략: 랜덤 DB instance ID × `_AURORA_RDS_ALARMS` 메트릭, 생성된 알람 이름이 `[AuroraRDS] `로 시작하고 AlarmDescription JSON에 `"resource_type":"AuroraRDS"` 포함 검증

- [ ] 5. Alarm Manager 알람 검색 호환 (`common/alarm_manager.py`)
  - [ ] 5.1 테스트 작성: `_find_alarms_for_resource()` AuroraRDS 검색 검증
    - `tests/test_alarm_manager.py`에 테스트 추가
    - `resource_type="AuroraRDS"` → prefix `"[AuroraRDS] "` + suffix `"({db_id})"` 검색 검증
    - `resource_type=None` (default) → `"AuroraRDS"` 포함 fallback 검증
    - _Requirements: 8.1, 8.2_

  - [ ] 5.2 `_find_alarms_for_resource()` 구현 변경
    - default `type_prefixes` fallback 리스트에 `"AuroraRDS"` 추가
    - _Requirements: 8.1, 8.2_

  - [ ]* 5.3 Property 5 테스트: 알람 검색 prefix/suffix
    - **Property 5: Alarm Search Prefix and Suffix**
    - **Validates: Requirements 8.1, 8.2**
    - 테스트 파일: `tests/test_pbt_aurora_rds.py`
    - hypothesis 전략: 랜덤 DB instance ID, `_find_alarms_for_resource()` 호출 시 올바른 prefix/suffix 사용 검증

- [ ] 6. Checkpoint — Alarm Manager 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Daily Monitor 통합 (`daily_monitor/lambda_handler.py`)
  - [ ] 7.1 테스트 작성: `_process_resource()` AuroraRDS 라우팅 검증
    - `tests/test_daily_monitor.py`에 테스트 추가
    - `resource_type="AuroraRDS"` → `collector_mod.get_aurora_metrics()` 호출 검증
    - `FreeLocalStorageGB` 임계치 비교: `current_value < threshold` (낮을수록 위험) 검증
    - _Requirements: 6.1, 6.2, 6.3_

  - [ ] 7.2 `_process_resource()` AuroraRDS 라우팅 구현
    - `if resource_type == "AuroraRDS":` → `metrics = collector_mod.get_aurora_metrics(resource_id, resource_tags)`
    - `"FreeLocalStorageGB"` 를 `"FreeMemoryGB"`, `"FreeStorageGB"` 와 함께 less-than 비교 집합에 추가
    - _Requirements: 6.1, 6.2, 6.3_

  - [ ] 7.3 테스트 작성: `_cleanup_orphan_alarms()` AuroraRDS alive_checker 검증
    - `tests/test_daily_monitor.py`에 테스트 추가
    - `alive_checkers["AuroraRDS"]` == `_find_alive_rds_instances` 검증
    - AuroraRDS 알람 → DB 인스턴스 삭제 → 고아 알람 삭제 시나리오 검증
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ] 7.4 `_cleanup_orphan_alarms()` alive_checkers 업데이트
    - `alive_checkers` 딕셔너리에 `"AuroraRDS": _find_alive_rds_instances` 추가
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ]* 7.5 Property 4 테스트: 알람 분류 정확성
    - **Property 4: Alarm Classification from Name Prefix**
    - **Validates: Requirements 7.2**
    - 테스트 파일: `tests/test_pbt_aurora_rds.py`
    - hypothesis 전략: `[AuroraRDS] ... (db_instance_id)` 패턴 알람 이름 생성, `_classify_alarm()` 출력이 `"AuroraRDS"` 타입과 올바른 ID로 분류되는지 검증

- [ ] 8. Checkpoint — Daily Monitor 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Remediation Handler Aurora 지원 (`remediation_handler/lambda_handler.py`)
  - [ ] 9.1 테스트 작성: `_resolve_rds_aurora_type()` 헬퍼 검증
    - `tests/test_remediation_handler.py`에 테스트 추가
    - Engine `"aurora-mysql"` → `"AuroraRDS"` 반환 검증
    - Engine `"mysql"` → `"RDS"` 반환 검증
    - API 오류 시 `"RDS"` 폴백 검증
    - _Requirements: 9.5_

  - [ ] 9.2 `_resolve_rds_aurora_type()` 헬퍼 구현
    - `describe_db_instances(DBInstanceIdentifier=db_instance_id)` 호출
    - Engine에 `"aurora"` 포함 → `"AuroraRDS"`, 아니면 `"RDS"`
    - `ClientError` 시 `"RDS"` 폴백 + warning 로그
    - _Requirements: 9.5_

  - [ ] 9.3 테스트 작성: `parse_cloudtrail_event()` Aurora RDS 이벤트 검증
    - CreateDBInstance (Aurora engine) → `resource_type="AuroraRDS"` 검증
    - DeleteDBInstance (Aurora engine) → `resource_type="AuroraRDS"` 검증
    - ModifyDBInstance (Aurora engine) → `resource_type="AuroraRDS"` 검증
    - AddTagsToResource (Aurora engine) → `resource_type="AuroraRDS"` 검증
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [ ] 9.4 `parse_cloudtrail_event()` Aurora 분기 구현
    - RDS 이벤트(`_API_MAP`에서 resource_type=="RDS"`) 파싱 후 `_resolve_rds_aurora_type()` 호출하여 `"AuroraRDS"` 세분화
    - `_execute_remediation()`: `"AuroraRDS"` → `rds.stop_db_instance()` (RDS와 동일)
    - `_remediation_action_name()`: `"AuroraRDS": "STOPPED"` 추가
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [ ]* 9.5 Property 6 테스트: CloudTrail 이벤트 Aurora 해석
    - **Property 6: RDS CloudTrail Event Aurora Resolution**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4**
    - 테스트 파일: `tests/test_pbt_aurora_rds.py`
    - hypothesis 전략: 랜덤 DB instance ID × Aurora/non-Aurora engine, mock `describe_db_instances` → 해석 결과 검증

- [ ] 10. Tag Resolver AuroraRDS 지원 (`common/tag_resolver.py`)
  - [ ] 10.1 테스트 작성: `get_resource_tags("AuroraRDS")` → `_get_rds_tags()` 호출 검증
    - `tests/test_alarm_manager.py` 또는 관련 테스트 파일에 추가
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [ ] 10.2 `get_resource_tags()` 분기 업데이트
    - `elif resource_type in ("RDS", "AuroraRDS"):` → `_get_rds_tags()` 호출
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [ ]* 10.3 Property 7 테스트: 태그 기반 임계치 오버라이드
    - **Property 7: Tag-Based Threshold Override for AuroraRDS**
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5**
    - 테스트 파일: `tests/test_pbt_aurora_rds.py`
    - hypothesis 전략: AuroraRDS 메트릭 키 × 랜덤 양의 threshold 값, `get_threshold()` 반환값 및 `transform_threshold` 적용 결과 검증

- [ ] 11. Checkpoint — Remediation + Tag Resolver 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. 통합 와이어링 및 §12 매핑 테이블 업데이트
  - [ ] 12.1 통합 시나리오 테스트 작성
    - `tests/test_alarm_manager.py`에 AuroraRDS 알람 생성 → sync → 삭제 end-to-end 테스트 추가
    - `sync_alarms_for_resource()` 호출 시 5개 알람 생성 검증
    - 태그 변경 후 re-sync 시 임계치 업데이트 검증
    - _Requirements: 6.2, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [ ] 12.2 `.kiro/steering/alarm-rules.md` §12 AuroraRDS 매핑 테이블 추가
    - RDS 테이블 아래에 AuroraRDS 섹션 추가:
      - `Threshold_CPU` → CPU → CPUUtilization → AWS/RDS → 80 → %
      - `Threshold_FreeMemoryGB` → FreeMemoryGB → FreeableMemory → AWS/RDS → 2 → GB → GB→bytes
      - `Threshold_Connections` → Connections → DatabaseConnections → AWS/RDS → 100 → Count
      - `Threshold_FreeLocalStorageGB` → FreeLocalStorageGB → FreeLocalStorage → AWS/RDS → 10 → GB → GB→bytes
      - `Threshold_ReplicaLag` → ReplicaLag → AuroraReplicaLagMaximum → AWS/RDS → 2000000 → μs
    - _Requirements: 2.1, 3.2, 3.3_

- [ ] 13. Final checkpoint — 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- TDD 사이클 준수: 각 구현 태스크에서 테스트 먼저 작성 (레드) → 최소 구현 (그린) → 리팩터링
- Property tests validate universal correctness properties from design document (7 properties)
- `_classify_alarm()`은 기존 `_NEW_FORMAT_RE` 정규식이 `[AuroraRDS]` prefix를 이미 매칭하므로 코드 변경 불필요 (검증만)
- `_build_dimensions()`은 기존 else 분기가 AuroraRDS의 `DBInstanceIdentifier` 디멘션을 처리하므로 변경 불필요
- Checkpoints ensure incremental validation
