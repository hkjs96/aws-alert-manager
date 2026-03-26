# Implementation Plan: DocumentDB Monitoring (docdb-monitoring)

## Overview

DocumentDB(DocDB)를 새 리소스 타입 `"DocDB"`로 AWS Monitoring Engine에 추가한다. TDD 레드-그린-리팩터링 사이클(거버넌스 §8)을 모듈별로 반복하며, 설계 문서의 Correctness Properties 10개에 대한 PBT 테스트를 포함한다.

변경 파일: `common/collectors/docdb.py` (NEW), `common/alarm_manager.py`, `common/__init__.py`, `daily_monitor/lambda_handler.py`, `remediation_handler/lambda_handler.py`, `common/tag_resolver.py`, `tests/test_collectors.py`, `tests/test_alarm_manager.py`, `tests/test_remediation_handler.py`, `tests/test_daily_monitor.py`, `tests/test_pbt_docdb_monitoring.py` (NEW)

## Tasks

- [x] 1. DocDB Collector 구현 — `common/collectors/docdb.py`
  - [x] 1.1 Red: `tests/test_collectors.py`에 DocDB Collector 실패 테스트 작성
    - `moto`로 RDS mock 환경 구성, Engine `"docdb"` DB 인스턴스 + `Monitoring=on` 태그 생성
    - Engine `"aurora-mysql"`, `"mysql"`, `"postgres"` 인스턴스도 생성 (DocDB Collector가 제외하는지 검증)
    - `collect_monitored_resources()` 호출 → `"docdb"` 엔진만 수집, `type == "DocDB"` 검증
    - `DBInstanceStatus == "deleting"` 인스턴스 skip 검증
    - `Monitoring=on` 태그 없는 DocDB 인스턴스 제외 검증
    - `get_metrics()` 호출 → 6개 메트릭 키 (`CPU`, `FreeMemoryGB`, `FreeLocalStorageGB`, `Connections`, `ReadLatency`, `WriteLatency`) 반환 검증
    - `FreeableMemory` bytes→GB 변환 검증 (예: 2147483648 bytes → 2.0 GB)
    - `FreeLocalStorage` bytes→GB 변환 검증
    - 모든 메트릭 데이터 없을 때 `None` 반환 검증
    - 실행 → `ImportError` 또는 `AttributeError`로 실패 확인
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9_

  - [x] 1.2 Green: `common/collectors/docdb.py` 모듈 생성
    - `functools.lru_cache` 기반 `_get_rds_client()` 싱글턴
    - `collect_monitored_resources()`: `describe_db_instances` paginator → `Engine == "docdb"` 필터 → `Monitoring=on` 태그 확인 → `ResourceInfo(type="DocDB")` 반환
    - `deleting`/`deleted` 상태 인스턴스 skip + info 로그
    - `_get_tags(rds_client, db_arn)` 헬퍼 (RDS Collector 패턴 재사용)
    - `get_metrics(db_instance_id, resource_tags=None)`: 네임스페이스 `AWS/DocDB`, 디멘션 `DBInstanceIdentifier`로 6개 메트릭 조회
    - `FreeableMemory` bytes→GB, `FreeLocalStorage` bytes→GB 변환
    - `base.py`의 `query_metric()` 유틸리티 사용
    - 개별 메트릭 데이터 없으면 skip + info 로그, 모두 없으면 `None` 반환
    - 실행 → 통과 확인
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9_

  - [x] 1.3 Refactor: DocDB Collector 코드 정리 및 전체 테스트 재실행
    - RDS Collector와 중복 로직 확인 (예: `_get_tags` 패턴)
    - 로깅 메시지에 resource_id 컨텍스트 포함 확인
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 1.4_

  - [ ]* 1.4 PBT Property 1: Engine 기반 DocDB 분류 (Engine-based DocDB Classification)
    - **Property 1: Engine-based DocDB Classification**
    - **Validates: Requirements 1.1, 1.2, 1.5**
    - 파일: `tests/test_pbt_docdb_monitoring.py`
    - 랜덤 엔진 문자열 생성 (`"docdb"`, `"aurora-mysql"`, `"aurora-postgresql"`, `"mysql"`, `"postgres"`, 랜덤 문자열 포함)
    - `moto` mock으로 해당 엔진의 DB 인스턴스 생성 + `Monitoring=on` 태그
    - `collect_monitored_resources()` 호출 → `Engine == "docdb"`인 경우에만 수집되는지 검증

- [x] 2. Checkpoint — DocDB Collector 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Alarm Manager DocDB 등록 — `common/alarm_manager.py`, `common/__init__.py`
  - [x] 3.1 Red: `tests/test_alarm_manager.py`에 DocDB 알람 정의 실패 테스트 작성
    - `_get_alarm_defs("DocDB")` 반환값이 6개 알람 정의인지 검증
    - 메트릭 키 집합: `{"CPU", "FreeMemoryGB", "FreeLocalStorageGB", "Connections", "ReadLatency", "WriteLatency"}`
    - 모든 정의의 `namespace == "AWS/DocDB"`, `dimension_key == "DBInstanceIdentifier"` 검증
    - `FreeMemoryGB`, `FreeLocalStorageGB`: `comparison == "LessThanThreshold"`, `transform_threshold` 존재 검증
    - `CPU`, `Connections`, `ReadLatency`, `WriteLatency`: `comparison == "GreaterThanThreshold"` 검증
    - `_HARDCODED_METRIC_KEYS["DocDB"]` == `{"CPU", "FreeMemoryGB", "FreeLocalStorageGB", "Connections", "ReadLatency", "WriteLatency"}` 검증
    - `_NAMESPACE_MAP["DocDB"]` == `["AWS/DocDB"]` 검증
    - `_DIMENSION_KEY_MAP["DocDB"]` == `"DBInstanceIdentifier"` 검증
    - `SUPPORTED_RESOURCE_TYPES`에 `"DocDB"` 포함 검증
    - 실행 → 실패 확인
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 4.1, 4.2, 6.1, 6.2, 6.3_

  - [x] 3.2 Green: DocDB 알람 정의 및 매핑 테이블 추가
    - `common/__init__.py`: `SUPPORTED_RESOURCE_TYPES`에 `"DocDB"` 추가
    - `common/__init__.py`: TypedDict 주석에 `"DocDB"` 추가 (`ResourceInfo`, `AlertMessage`, `RemediationAlertMessage`, `LifecycleAlertMessage`)
    - `common/alarm_manager.py`: `_DOCDB_ALARMS` 리스트 정의 (6개 알람: CPU, FreeMemoryGB, FreeLocalStorageGB, Connections, ReadLatency, WriteLatency)
    - `common/alarm_manager.py`: `_get_alarm_defs()`에 `elif resource_type == "DocDB": return _DOCDB_ALARMS` 추가
    - `common/alarm_manager.py`: `_HARDCODED_METRIC_KEYS`에 `"DocDB": {"CPU", "FreeMemoryGB", "FreeLocalStorageGB", "Connections", "ReadLatency", "WriteLatency"}` 추가
    - `common/alarm_manager.py`: `_NAMESPACE_MAP`에 `"DocDB": ["AWS/DocDB"]` 추가
    - `common/alarm_manager.py`: `_DIMENSION_KEY_MAP`에 `"DocDB": "DBInstanceIdentifier"` 추가
    - `common/alarm_manager.py`: `_find_alarms_for_resource()` 기본 type_prefixes 폴백 목록에 `"DocDB"` 추가
    - 실행 → 통과 확인
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 4.1, 4.2, 6.1, 6.2, 6.3, 6.4, 13.1, 13.2, 13.3, 13.4_

  - [x] 3.3 Refactor: 알람 정의 정리 및 전체 테스트 재실행
    - `_DOCDB_ALARMS`의 `transform_threshold` 승수가 `1073741824` (1 GiB)인지 확인
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 3.4, 3.5_

  - [ ]* 3.4 PBT Property 2: Bytes-to-GB 변환 Round Trip (Bytes-to-GB Conversion Round Trip)
    - **Property 2: Bytes-to-GB Conversion Round Trip**
    - **Validates: Requirements 2.2, 2.3, 3.4, 3.5**
    - 파일: `tests/test_pbt_docdb_monitoring.py`
    - 랜덤 양의 float 생성 (0.001 ~ 10000 범위)
    - `transform_threshold(value / 1073741824) ≈ value` (부동소수점 허용 오차 `1e-6` 내 round-trip) 검증

  - [ ]* 3.5 PBT Property 3: DocDB 알람 정의 정합성 (DocDB Alarm Definition Correctness)
    - **Property 3: DocDB Alarm Definition Correctness**
    - **Validates: Requirements 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 5.3**
    - 파일: `tests/test_pbt_docdb_monitoring.py`
    - `_DOCDB_ALARMS`의 모든 정의에 대해:
      - `namespace == "AWS/DocDB"` 검증
      - `dimension_key == "DBInstanceIdentifier"` 검증
      - `metric` ∈ `{"CPU", "FreeMemoryGB", "FreeLocalStorageGB", "Connections", "ReadLatency", "WriteLatency"}` 검증
      - Memory/Storage 메트릭: `comparison == "LessThanThreshold"` 검증
      - 나머지: `comparison == "GreaterThanThreshold"` 검증

- [x] 4. Checkpoint — Alarm Manager DocDB 등록 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Tag Resolver DocDB 지원 — `common/tag_resolver.py`
  - [x] 5.1 Red: `tests/test_collectors.py` 또는 별도 테스트에 DocDB 태그 조회 실패 테스트 작성
    - `moto` mock으로 DocDB 인스턴스 생성 + 태그 부착
    - `get_resource_tags(db_instance_id, "DocDB")` 호출 → 태그 딕셔너리 반환 검증
    - RDS 태그 조회 경로(`describe_db_instances` + `list_tags_for_resource`)와 동일한 결과 검증
    - 실행 → `"DocDB"`가 지원되지 않아 빈 dict 반환 (warning 로그) 확인
    - _Requirements: 15.1_

  - [x] 5.2 Green: `common/tag_resolver.py`의 `get_resource_tags()`에 DocDB 분기 추가
    - `elif resource_type in ("RDS", "AuroraRDS", "DocDB"):` 로 조건 확장
    - 실행 → 통과 확인
    - _Requirements: 15.1_

  - [ ]* 5.3 PBT Property 10: Tag Resolver DocDB 지원 (Tag Resolver DocDB Support)
    - **Property 10: Tag Resolver DocDB Support**
    - **Validates: Requirements 15.1**
    - 파일: `tests/test_pbt_docdb_monitoring.py`
    - 랜덤 DocDB 리소스 ID 생성
    - `moto` mock으로 DocDB 인스턴스 생성 + 랜덤 태그 부착
    - `get_resource_tags(id, "DocDB")`와 `get_resource_tags(id, "RDS")` 결과가 동일한지 검증

- [x] 6. Checkpoint — Tag Resolver DocDB 지원 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Daily Monitor 통합 — `daily_monitor/lambda_handler.py`
  - [x] 7.1 Red: `tests/test_daily_monitor.py`에 DocDB 통합 실패 테스트 작성
    - `_COLLECTOR_MODULES`에 `docdb_collector` 포함 검증
    - `_cleanup_orphan_alarms()`의 `alive_checkers`에 `"DocDB"` 키 존재 검증
    - DocDB 리소스에 대해 `sync_alarms_for_resource()` 호출 검증
    - DocDB 리소스에 대해 `get_metrics()` 호출 → 임계치 비교 검증
    - `FreeMemoryGB`, `FreeLocalStorageGB` 메트릭에 대해 "낮을수록 위험" 비교 적용 검증
    - 실행 → 실패 확인
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3_

  - [x] 7.2 Green: Daily Monitor에 DocDB Collector 등록
    - `daily_monitor/lambda_handler.py`: `from common.collectors import docdb as docdb_collector` 추가
    - `_COLLECTOR_MODULES`에 `docdb_collector` 추가
    - `_cleanup_orphan_alarms()`의 `alive_checkers`에 `"DocDB": _find_alive_rds_instances` 추가
    - `_process_resource()`: DocDB는 기존 `else` 분기에서 `get_metrics()` 호출로 자동 처리 (별도 분기 불필요)
    - 실행 → 통과 확인
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3_

  - [x] 7.3 Refactor: Daily Monitor 정리 및 전체 테스트 재실행
    - `FreeMemoryGB`, `FreeLocalStorageGB`가 이미 "낮을수록 위험" 비교 세트에 포함되어 있는지 확인
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 7.4_

  - [ ]* 7.4 PBT Property 5: 알람 이름 접두사 분류 (Alarm Classification from Name Prefix)
    - **Property 5: Alarm Classification from Name Prefix**
    - **Validates: Requirements 8.2**
    - 파일: `tests/test_pbt_docdb_monitoring.py`
    - `[DocDB] ... (db_instance_id)` 패턴의 랜덤 알람 이름 생성
    - `_classify_alarm()` 호출 → `"DocDB"` 타입과 올바른 `db_instance_id` 추출 검증

  - [ ]* 7.5 PBT Property 6: 알람 검색 Prefix/Suffix (Alarm Search Prefix and Suffix)
    - **Property 6: Alarm Search Prefix and Suffix**
    - **Validates: Requirements 6.4, 9.1, 9.2**
    - 파일: `tests/test_pbt_docdb_monitoring.py`
    - 랜덤 DB 인스턴스 ID 생성
    - `moto` mock으로 `[DocDB] ... (id)` 알람 생성
    - `_find_alarms_for_resource(id, "DocDB")` 호출 → 접두사 `"[DocDB] "` + 접미사 `"(id)"` 기반 검색 검증
    - `_find_alarms_for_resource(id)` (resource_type 미지정) 호출 → 기본 폴백 목록에 `"DocDB"` 포함 검증

- [x] 8. Checkpoint — Daily Monitor 통합 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Remediation Handler DocDB 지원 — `remediation_handler/lambda_handler.py`
  - [x] 9.1 Red: `tests/test_remediation_handler.py`에 DocDB 실패 테스트 작성
    - `moto` mock으로 Engine `"docdb"` DB 인스턴스 생성
    - `_resolve_rds_aurora_type(db_instance_id)` 호출 → `("DocDB", False)` 반환 검증
    - Engine `"aurora-mysql"` → `("AuroraRDS", False)`, Engine `"mysql"` → `("RDS", False)` 검증
    - `_execute_remediation("DocDB", db_instance_id)` 호출 → `"STOPPED"` 반환 + `stop_db_instance` 호출 검증
    - `_remediation_action_name("DocDB")` → `"STOPPED"` 검증
    - CreateDBInstance CloudTrail 이벤트 (DocDB 엔진) → `parse_cloudtrail_event()` → `resource_type == "DocDB"` 검증
    - DeleteDBInstance CloudTrail 이벤트 (DocDB 인스턴스) → `resource_type == "DocDB"` 검증
    - 실행 → 실패 확인
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 14.1, 14.2, 14.3_

  - [x] 9.2 Green: Remediation Handler에 DocDB 지원 추가
    - `_resolve_rds_aurora_type()`: `engine.lower() == "docdb"` 분기 추가 → `("DocDB", False)` 반환 (Aurora 분기보다 먼저 체크)
    - `_execute_remediation()`: `if resource_type == "DocDB":` 분기 추가 → `stop_db_instance()` 호출 + `"STOPPED"` 반환
    - `_remediation_action_name()`: `"DocDB": "STOPPED"` 매핑 추가
    - 실행 → 통과 확인
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 14.1, 14.2, 14.3_

  - [x] 9.3 Refactor: Remediation Handler 정리 및 전체 테스트 재실행
    - `_resolve_rds_aurora_type()` 함수명 변경 검토 (`_resolve_rds_engine_type()` 권장, 기존 호출부 모두 업데이트)
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 10.5_

  - [ ]* 9.4 PBT Property 7: CloudTrail Engine Resolution
    - **Property 7: CloudTrail Engine Resolution**
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5**
    - 파일: `tests/test_pbt_docdb_monitoring.py`
    - 랜덤 DB 인스턴스 ID + 랜덤 엔진 문자열 (`"docdb"`, `"aurora-mysql"`, `"aurora-postgresql"`, `"mysql"`, `"postgres"`, 랜덤) 생성
    - `moto` mock으로 해당 엔진의 DB 인스턴스 생성
    - `_resolve_rds_aurora_type(id)` 호출 → 엔진별 올바른 리소스 타입 반환 검증
      - `"docdb"` → `"DocDB"`, `"aurora*"` → `"AuroraRDS"`, 기타 → `"RDS"`

  - [ ]* 9.5 PBT Property 9: Remediation Execution for DocDB
    - **Property 9: Remediation Execution for DocDB**
    - **Validates: Requirements 14.1, 14.2, 14.3**
    - 파일: `tests/test_pbt_docdb_monitoring.py`
    - 랜덤 DocDB 리소스 ID 생성
    - `moto` mock으로 DocDB 인스턴스 생성
    - `_execute_remediation("DocDB", id)` 호출 → `"STOPPED"` 반환 검증
    - `_remediation_action_name("DocDB")` → `"STOPPED"` 검증

- [x] 10. Checkpoint — Remediation Handler DocDB 지원 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. 알람 이름/메타데이터 및 태그 임계치 오버라이드 검증
  - [x] 11.1 Red: `tests/test_alarm_manager.py`에 DocDB 알람 생성 통합 테스트 작성
    - `moto` mock으로 DocDB 인스턴스 생성 + `Monitoring=on` 태그
    - `create_alarms_for_resource(db_id, "DocDB", tags)` 호출 → 6개 알람 생성 검증
    - 알람 이름 접두사 `"[DocDB] "` 검증
    - `AlarmDescription` JSON 메타데이터에 `"resource_type":"DocDB"` 포함 검증
    - 디멘션: `[{"Name": "DBInstanceIdentifier", "Value": db_id}]` 검증
    - `Threshold_CPU=90` 태그 → CPU 알람 임계치 90.0 검증
    - `Threshold_FreeMemoryGB=4` 태그 → FreeableMemory 알람 임계치 `4 * 1073741824` bytes 검증
    - 실행 → 실패 확인 (DocDB 알람 정의가 이미 등록되어 있으면 통과할 수 있음)
    - _Requirements: 5.1, 5.2, 5.3, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [x] 11.2 Green: 필요 시 누락된 연결 보완 (대부분 이전 태스크에서 완료)
    - 테스트 통과 확인. 이전 태스크에서 등록한 `_DOCDB_ALARMS`, `_get_alarm_defs()`, 매핑 테이블이 올바르게 동작하는지 검증
    - 실행 → 통과 확인
    - _Requirements: 5.1, 5.2, 5.3, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [ ]* 11.3 PBT Property 4: DocDB 알람 이름 접두사 및 메타데이터 (DocDB Alarm Name Prefix and Metadata)
    - **Property 4: DocDB Alarm Name Prefix and Metadata**
    - **Validates: Requirements 5.1, 5.2**
    - 파일: `tests/test_pbt_docdb_monitoring.py`
    - 랜덤 유효 DB 인스턴스 ID + `_DOCDB_ALARMS`의 랜덤 메트릭 선택
    - `_pretty_alarm_name("DocDB", resource_id, ...)` 호출 → `"[DocDB] "` 접두사 검증
    - `_build_alarm_description("DocDB", resource_id, metric_key)` 호출 → JSON에 `"resource_type":"DocDB"` 포함 검증

  - [ ]* 11.4 PBT Property 8: 태그 기반 임계치 오버라이드 (Tag-Based Threshold Override for DocDB)
    - **Property 8: Tag-Based Threshold Override for DocDB**
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6**
    - 파일: `tests/test_pbt_docdb_monitoring.py`
    - DocDB 메트릭 키 중 랜덤 선택 + 랜덤 양수 float 임계치 생성
    - `Threshold_{metric_key}` 태그 설정 후 `get_threshold()` 호출 → 태그 값 반환 검증
    - `transform_threshold` 존재 시 변환 결과 검증 (예: `FreeMemoryGB` 4.0 → `4.0 * 1073741824` bytes)

- [x] 12. Checkpoint — 알람 생성 및 태그 오버라이드 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. 전체 통합 와이어링 및 최종 검증
  - [x] 13.1 End-to-end 통합 테스트 작성
    - `moto` mock으로 DocDB 인스턴스 생성 + `Monitoring=on` + `Threshold_CPU=90` 태그
    - Daily Monitor `lambda_handler()` 호출 → DocDB 리소스 수집 + 알람 동기화 + 메트릭 점검 검증
    - Remediation Handler: DocDB CreateDBInstance CloudTrail 이벤트 → `resource_type == "DocDB"` + 알람 생성 검증
    - Remediation Handler: DocDB DeleteDBInstance CloudTrail 이벤트 → 알람 삭제 검증
    - 고아 알람 정리: DocDB 인스턴스 삭제 후 `_cleanup_orphan_alarms()` → 고아 알람 삭제 검증
    - _Requirements: 7.1, 7.2, 7.3, 8.1, 8.3, 10.1, 10.2, 12.1, 12.2_

  - [x] 13.2 전체 테스트 스위트 실행 및 회귀 확인
    - `pytest tests/` 전체 실행 → 모든 기존 테스트 + 새 테스트 통과 확인
    - _Requirements: ALL_

- [x] 14. Final checkpoint — 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- `*` 표시된 태스크는 선택적이며 빠른 MVP를 위해 건너뛸 수 있음
- 각 태스크는 특정 요구사항을 참조하여 추적 가능
- DocDB 메트릭은 기존 RDS 메트릭 키를 공유하므로 `HARDCODED_DEFAULTS`, `_METRIC_DISPLAY`, `_metric_name_to_key()`에 추가 항목 불필요
- `MONITORED_API_EVENTS`에 추가 등록 불필요 (DocDB는 RDS와 동일한 CloudTrail API 사용)
- PBT 테스트는 설계 문서의 Correctness Properties 10개를 모두 커버
- TDD 레드-그린-리팩터링 사이클을 모듈별로 반복
