# Implementation Plan: RDS Aurora Alarm Optimization

## Overview

기존 `AuroraRDS` 알람 시스템을 5개 축으로 개선한다: (1) Collector 메타데이터 enrichment, (2) 인스턴스 변형별 알람 라우팅, (3) 퍼센트 기반 FreeableMemory 임계치, (4) Serverless v2 전용 알람, (5) KI-008 삭제 이벤트 수정. TDD 사이클(레드-그린-리팩터링)을 준수하며, 기존 테스트 회귀 없이 진행한다. Python 3.12, moto, hypothesis 사용.

## Tasks

- [ ] 1. `common/__init__.py` 상수 업데이트
  - `HARDCODED_DEFAULTS`에 신규 키 추가: `"ReaderReplicaLag": 2000000.0`, `"ACUUtilization": 80.0`, `"ServerlessDatabaseCapacity": 128.0`, `"FreeMemoryPct": 20.0`
  - _Requirements: 3.4, 5.4, 7.4, 7.5_

- [ ] 2. RDS Collector 메타데이터 enrichment (`common/collectors/rds.py`)
  - [ ] 2.1 테스트 작성: `_enrich_aurora_metadata()` 및 `_INSTANCE_CLASS_MEMORY_MAP` 검증
    - `tests/test_collectors.py`에 테스트 추가
    - moto로 Aurora 클러스터/인스턴스 생성 후 `collect_monitored_resources()` 호출
    - Provisioned Writer (w/ readers): `_db_instance_class`, `_is_serverless_v2="false"`, `_is_cluster_writer="true"`, `_has_readers="true"`, `_total_memory_bytes` 검증
    - Provisioned Reader: `_is_cluster_writer="false"` 검증
    - Writer-only 클러스터: `_has_readers="false"` 검증
    - Serverless v2: `_is_serverless_v2="true"`, `_max_acu`, `_min_acu`, `_total_memory_bytes = max_acu * 2 * 1073741824` 검증
    - 일반 RDS 인스턴스: Aurora 전용 내부 태그 미포함 검증
    - `_INSTANCE_CLASS_MEMORY_MAP` 주요 엔트리 검증 (db.r6g.large=16GiB 등)
    - `describe_db_clusters` 실패 시 graceful degradation 검증
    - 알 수 없는 인스턴스 클래스: `_total_memory_bytes` 미포함 + warning 로그 검증
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 4.1, 4.2, 4.3, 6.1, 6.2, 6.3, 6.4, 8.1, 8.2, 8.3_

  - [ ] 2.2 `_enrich_aurora_metadata()`, `_get_cluster_info()`, `_INSTANCE_CLASS_MEMORY_MAP` 구현
    - `_INSTANCE_CLASS_MEMORY_MAP`: design §1 참조, 주요 인스턴스 클래스 → 메모리 bytes 매핑
    - `_get_cluster_info(cluster_id)`: `describe_db_clusters` 래퍼, `ClientError` 시 `None` 반환 + error 로그
    - `_enrich_aurora_metadata(db_instance, tags)`: 클러스터 정보 조회 후 `_db_instance_class`, `_is_serverless_v2`, `_is_cluster_writer`, `_has_readers`, `_max_acu`, `_min_acu`, `_total_memory_bytes` 태그 설정
    - `collect_monitored_resources()`에서 `resource_type == "AuroraRDS"` 시 `_enrich_aurora_metadata()` 호출
    - 클러스터별 캐싱 (collection loop 내 로컬 dict)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 4.1, 4.2, 4.3, 6.1, 6.2, 6.3, 6.4, 8.1, 8.2, 8.3_

  - [ ]* 2.3 Property 1 테스트: Aurora Collector Enrichment Completeness
    - **Property 1: Aurora Collector Enrichment Completeness**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 4.2, 4.3, 8.1, 8.2**
    - 테스트 파일: `tests/test_pbt_aurora_alarm_optimization.py`
    - hypothesis 전략: 랜덤 인스턴스 클래스 (`"db.serverless"` 포함), 랜덤 writer/reader boolean, 랜덤 클러스터 멤버 수, 랜덤 ACU 값 생성 → enrichment 로직 실행 → 모든 내부 태그가 입력 메타데이터와 일치하는지 검증

  - [ ]* 2.4 Property 2 테스트: Non-Aurora RDS Tag Exclusion
    - **Property 2: Non-Aurora RDS Tag Exclusion**
    - **Validates: Requirements 1.5**
    - 테스트 파일: `tests/test_pbt_aurora_alarm_optimization.py`
    - hypothesis 전략: `"aurora"` 미포함 랜덤 engine 문자열 생성 → collector 실행 → `_is_cluster_writer`, `_is_serverless_v2`, `_has_readers` 키 미포함 검증

- [ ] 3. Checkpoint — Collector enrichment 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Alarm Manager 변형별 알람 라우팅 (`common/alarm_manager.py`)
  - [ ] 4.1 테스트 작성: `_get_aurora_alarm_defs()` 6개 변형 검증
    - `tests/test_alarm_manager.py`에 테스트 추가
    - Provisioned Writer (w/ readers): `{CPU, FreeMemoryGB, Connections, FreeLocalStorageGB, ReplicaLag}` 검증
    - Provisioned Writer (no readers): `{CPU, FreeMemoryGB, Connections, FreeLocalStorageGB}` 검증
    - Provisioned Reader: `{CPU, FreeMemoryGB, Connections, FreeLocalStorageGB, ReaderReplicaLag}` 검증
    - Serverless v2 Writer (w/ readers): `{CPU, FreeMemoryGB, Connections, ACUUtilization, ServerlessDatabaseCapacity, ReplicaLag}` 검증
    - Serverless v2 Writer (no readers): `{CPU, FreeMemoryGB, Connections, ACUUtilization, ServerlessDatabaseCapacity}` 검증
    - Serverless v2 Reader: `{CPU, FreeMemoryGB, Connections, ACUUtilization, ServerlessDatabaseCapacity, ReaderReplicaLag}` 검증
    - 신규 알람 정의 스키마 검증: `_AURORA_READER_REPLICA_LAG`, `_AURORA_ACU_UTILIZATION`, `_AURORA_SERVERLESS_CAPACITY`
    - _Requirements: 2.1, 2.2, 3.1, 3.2, 4.4, 7.1, 7.2, 7.3, 11.1, 11.2_

  - [ ] 4.2 `_get_aurora_alarm_defs()` 및 신규 알람 정의 상수 구현
    - `_AURORA_READER_REPLICA_LAG`, `_AURORA_ACU_UTILIZATION`, `_AURORA_SERVERLESS_CAPACITY` 상수 추가
    - `_get_aurora_alarm_defs(resource_tags)`: base(CPU, FreeMemoryGB, Connections) + 조건부 추가 로직
    - `_get_alarm_defs()` AuroraRDS 분기를 `_get_aurora_alarm_defs()` 호출로 변경
    - _Requirements: 2.1, 2.2, 3.1, 3.2, 4.4, 7.1, 7.2, 7.3, 11.1, 11.2_

  - [ ] 4.3 테스트 작성: 상수 매핑 업데이트 검증
    - `_METRIC_DISPLAY`: `ReaderReplicaLag`, `ACUUtilization`, `ServerlessDatabaseCapacity` 엔트리 검증
    - `_HARDCODED_METRIC_KEYS["AuroraRDS"]`: 8개 키 전체 포함 검증
    - `_metric_name_to_key()`: `"AuroraReplicaLag"` → `"ReaderReplicaLag"`, `"ACUUtilization"` → `"ACUUtilization"`, `"ServerlessDatabaseCapacity"` → `"ServerlessDatabaseCapacity"` 검증
    - _Requirements: 3.5, 7.6, 12.3_

  - [ ] 4.4 상수 매핑 구현
    - `_METRIC_DISPLAY` 신규 엔트리 추가
    - `_HARDCODED_METRIC_KEYS["AuroraRDS"]` 확장 (8개 키)
    - `_metric_name_to_key()` 신규 매핑 추가
    - _Requirements: 3.5, 7.6, 12.3_

  - [ ]* 4.5 Property 3 테스트: Alarm Variant Routing
    - **Property 3: Alarm Variant Routing**
    - **Validates: Requirements 2.1, 2.2, 3.1, 3.2, 4.4, 7.1, 7.2, 7.3, 11.1, 11.2**
    - 테스트 파일: `tests/test_pbt_aurora_alarm_optimization.py`
    - hypothesis 전략: `_is_serverless_v2`, `_is_cluster_writer`, `_has_readers` 3개 boolean 조합 생성 → `_get_alarm_defs("AuroraRDS", tags)` 호출 → 반환된 metric key 집합이 Variant Classification 테이블과 정확히 일치하는지 검증

- [ ] 5. Checkpoint — Alarm variant routing 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. 퍼센트 기반 FreeableMemory 임계치 (`common/alarm_manager.py`)
  - [ ] 6.1 테스트 작성: `_resolve_free_memory_threshold()` 검증
    - `tests/test_alarm_manager.py`에 테스트 추가
    - `Threshold_FreeMemoryPct=20`, `_total_memory_bytes=17179869184` (16GiB) → threshold = 3435973836.8 bytes 검증
    - `Threshold_FreeMemoryPct=20` + `Threshold_FreeMemoryGB=4` 동시 존재 → 퍼센트 우선 검증
    - `Threshold_FreeMemoryPct=150` (무효) → GB 폴백 + warning 로그 검증
    - `Threshold_FreeMemoryPct=20` + `_total_memory_bytes` 미존재 → GB 폴백 + warning 로그 검증
    - `Threshold_FreeMemoryPct` 미존재 → 기존 GB 로직 유지 검증
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 6.5_

  - [ ] 6.2 `_resolve_free_memory_threshold()` 구현
    - `resource_tags`에서 `Threshold_FreeMemoryPct` 확인
    - 유효 범위 (0 < pct < 100) 및 `_total_memory_bytes` 존재 시: `(pct / 100) * total_memory_bytes` 계산
    - 무효 시 warning 로그 + GB 폴백
    - `_create_standard_alarm()` 및 `_recreate_standard_alarm()`에서 FreeMemoryGB 메트릭 처리 시 호출
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 6.5_

  - [ ]* 6.3 Property 5 테스트: Percentage-Based Memory Threshold Calculation
    - **Property 5: Percentage-Based Memory Threshold Calculation**
    - **Validates: Requirements 5.1, 5.2, 5.3**
    - 테스트 파일: `tests/test_pbt_aurora_alarm_optimization.py`
    - hypothesis 전략: 랜덤 유효 퍼센트 (0 < pct < 100) × 랜덤 양의 `_total_memory_bytes` → 계산 결과 = `(pct / 100) * total_memory_bytes` 검증. 양쪽 태그 동시 존재 시 퍼센트 우선 검증.

  - [ ]* 6.4 Property 6 테스트: Instance Memory Capacity Lookup
    - **Property 6: Instance Memory Capacity Lookup**
    - **Validates: Requirements 6.1, 6.2**
    - 테스트 파일: `tests/test_pbt_aurora_alarm_optimization.py`
    - hypothesis 전략: `_INSTANCE_CLASS_MEMORY_MAP` 키에서 랜덤 선택 → lookup 결과 검증. 랜덤 양의 `max_acu` float → Serverless v2 메모리 = `max_acu * 2 * 1073741824` 검증.

- [ ] 7. Checkpoint — 퍼센트 임계치 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Aurora 메트릭 수집 조건부 분기 (`common/collectors/rds.py`)
  - [ ] 8.1 테스트 작성: `get_aurora_metrics()` 변형별 메트릭 수집 검증
    - `tests/test_collectors.py`에 테스트 추가
    - Serverless v2: `ACUUtilization`, `ServerlessDatabaseCapacity` 수집, `FreeLocalStorageGB` 미수집 검증
    - Provisioned: `FreeLocalStorageGB` 수집, `ACUUtilization`/`ServerlessDatabaseCapacity` 미수집 검증
    - Writer (w/ readers): `ReplicaLag` (AuroraReplicaLagMaximum) 수집 검증
    - Reader: `ReaderReplicaLag` (AuroraReplicaLag) 수집 검증
    - Writer (no readers): replica lag 메트릭 미수집 검증
    - _Requirements: 9.1, 9.2, 9.3, 10.1, 10.2, 10.3_

  - [ ] 8.2 `get_aurora_metrics()` 조건부 분기 구현
    - `resource_tags` 기반 조건부 메트릭 수집:
      - Always: CPUUtilization, FreeableMemory, DatabaseConnections
      - `_is_serverless_v2 != "true"`: FreeLocalStorage
      - `_is_serverless_v2 == "true"`: ACUUtilization, ServerlessDatabaseCapacity
      - `_is_cluster_writer == "true"` & `_has_readers == "true"`: AuroraReplicaLagMaximum → ReplicaLag
      - `_is_cluster_writer == "false"`: AuroraReplicaLag → ReaderReplicaLag
    - _Requirements: 9.1, 9.2, 9.3, 10.1, 10.2, 10.3_

  - [ ]* 8.3 Property 4 테스트: Metric Collection Matches Alarm Variant
    - **Property 4: Metric Collection Matches Alarm Variant**
    - **Validates: Requirements 9.1, 9.2, 9.3, 10.1, 10.2, 10.3**
    - 테스트 파일: `tests/test_pbt_aurora_alarm_optimization.py`
    - hypothesis 전략: 랜덤 Aurora 변형 태그 생성 → `get_aurora_metrics()` (mock CW) 및 `_get_alarm_defs()` 호출 → 메트릭 키가 알람 키의 부분집합인지 검증

- [ ] 9. Checkpoint — 메트릭 수집 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Remediation Handler KI-008 수정 (`remediation_handler/lambda_handler.py`)
  - [ ] 10.1 테스트 작성: `_handle_delete()` Aurora 삭제 이벤트 알람 정리 검증
    - `tests/test_remediation_handler.py`에 테스트 추가
    - `_resolve_rds_aurora_type()` 실패 (인스턴스 삭제됨) → `"RDS"` 폴백 시나리오
    - 폴백 시 `[RDS]` + `[AuroraRDS]` 양쪽 prefix 알람 검색/삭제 검증
    - `_resolve_rds_aurora_type()` 반환값 `(resource_type, is_fallback)` 튜플 검증
    - `is_fallback=True` + DELETE 이벤트 → `resource_type=""` 으로 `delete_alarms_for_resource()` 호출 검증
    - warning 로그 출력 검증
    - _Requirements: 13.1, 13.2, 13.3_

  - [ ] 10.2 `_resolve_rds_aurora_type()` 튜플 반환 및 `_handle_delete()` 수정
    - `_resolve_rds_aurora_type()`: `(resource_type, is_fallback)` 튜플 반환으로 변경
    - 성공 시 `("AuroraRDS", False)` 또는 `("RDS", False)`, 실패 시 `("RDS", True)`
    - `parse_cloudtrail_event()`에서 튜플 언패킹 적용
    - `_handle_delete()`: `is_fallback=True` 시 `delete_alarms_for_resource(resource_id, "")` 호출 (전체 prefix 검색)
    - warning 로그 추가
    - _Requirements: 13.1, 13.2, 13.3_

  - [ ]* 10.3 Property 7 테스트: Delete Event Alarm Cleanup Across Prefixes
    - **Property 7: Delete Event Alarm Cleanup Across Prefixes (KI-008)**
    - **Validates: Requirements 13.1, 13.2, 13.3**
    - 테스트 파일: `tests/test_pbt_aurora_alarm_optimization.py`
    - hypothesis 전략: 랜덤 DB instance ID, `_resolve_rds_aurora_type()` 실패 시나리오 → `delete_alarms_for_resource()` 호출 인자가 빈 `resource_type`인지 검증

- [ ] 11. Checkpoint — KI-008 수정 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Daily Monitor 통합 및 Steering 문서 업데이트
  - [ ] 12.1 테스트 작성: `_process_resource()` 신규 메트릭 임계치 비교 검증
    - `tests/test_daily_monitor.py`에 테스트 추가
    - `ReaderReplicaLag`: `current_value > threshold` (높을수록 위험) 검증
    - `ACUUtilization`: `current_value > threshold` 검증
    - `ServerlessDatabaseCapacity`: `current_value > threshold` 검증
    - _Requirements: 9.1, 10.1, 10.2_

  - [ ] 12.2 `_process_resource()` 업데이트 (필요 시)
    - 신규 메트릭 키가 기존 greater-than 비교 로직에 포함되는지 확인
    - `FreeMemoryGB` less-than 비교 집합은 기존 유지 (변경 불필요)
    - _Requirements: 9.1, 10.1, 10.2_

  - [ ] 12.3 `.kiro/steering/alarm-rules.md` §12 AuroraRDS 매핑 테이블 업데이트
    - 기존 AuroraRDS 테이블에 신규 행 추가:
      - `Threshold_ReaderReplicaLag` → ReaderReplicaLag → AuroraReplicaLag → AWS/RDS → 2000000 → μs
      - `Threshold_ACUUtilization` → ACUUtilization → ACUUtilization → AWS/RDS → 80 → %
      - `Threshold_ServerlessDatabaseCapacity` → ServerlessDatabaseCapacity → ServerlessDatabaseCapacity → AWS/RDS → 128 → ACU
      - `Threshold_FreeMemoryPct` → FreeMemoryPct → (FreeableMemory 퍼센트 변환) → AWS/RDS → 20 → %
    - _Requirements: 12.1_

  - [ ] 12.4 `docs/KNOWN-ISSUES.md` KI-006, KI-007, KI-008 업데이트
    - KI-006: Serverless v2 FreeLocalStorage → 엔진 능동 대응 (알람 스킵) 반영
    - KI-007: Writer-only ReplicaLag → 엔진 능동 대응 (알람 스킵) 반영
    - KI-008: 삭제 이벤트 수정 완료 반영
    - _Requirements: 12.2_

- [ ] 13. Final checkpoint — 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- TDD 사이클 준수: 각 구현 태스크에서 테스트 먼저 작성 (레드) → 최소 구현 (그린) → 리팩터링
- Property tests validate universal correctness properties from design document (7 properties)
- 기존 `_AURORA_RDS_ALARMS` 정적 리스트는 `_get_aurora_alarm_defs()` 동적 빌더로 대체됨
- `_resolve_rds_aurora_type()` 시그니처 변경 시 `parse_cloudtrail_event()` 호출부도 함께 수정 필요
- Checkpoints ensure incremental validation
