# Implementation Plan: Aurora RDS Monitoring

## Overview

Aurora RDS를 새로운 모니터링 리소스 타입(`"AuroraRDS"`)으로 추가한다. 기존 RDS 모듈을 확장하여 Aurora 분류, Aurora 전용 메트릭 수집, 알람 정의, Daily Monitor/Remediation Handler 통합을 구현한다. TDD 사이클(레드→그린→리팩터)을 따르며, 각 기능 단위로 테스트 → 구현 순서로 진행한다.

## Tasks

- [ ] 1. `common/__init__.py` 상수 등록 (HARDCODED_DEFAULTS + SUPPORTED_RESOURCE_TYPES + TypedDict)
  - [ ] 1.1 상수 등록 단위 테스트 작성 (tests/test_common_init.py)
    - `"AuroraRDS"` in `SUPPORTED_RESOURCE_TYPES` 확인
    - `HARDCODED_DEFAULTS["FreeLocalStorageGB"] == 10.0` 확인
    - `HARDCODED_DEFAULTS["ReplicaLag"] == 2000000.0` 확인
    - 기존 공유 메트릭 키(`CPU`, `FreeMemoryGB`, `Connections`) 값 불변 확인
    - _Requirements: 3.1, 3.2, 3.3, 3.4_
  - [ ] 1.2 `common/__init__.py` 수정
    - `HARDCODED_DEFAULTS`에 `"FreeLocalStorageGB": 10.0`, `"ReplicaLag": 2000000.0` 추가
    - `SUPPORTED_RESOURCE_TYPES`에 `"AuroraRDS"` 추가
    - `ResourceInfo`, `AlertMessage`, `RemediationAlertMessage`, `LifecycleAlertMessage` TypedDict 주석에 `"AuroraRDS"` 추가
    - _Requirements: 3.1, 3.2, 3.3, 11.1, 11.2, 11.3, 11.4_

- [ ] 2. RDS Collector Aurora 분류 + `get_aurora_metrics()` (common/collectors/rds.py)
  - [ ] 2.1 Aurora 분류 단위 테스트 작성 (tests/test_collectors.py)
    - Engine=`"aurora-mysql"` + Monitoring=on → `ResourceInfo(type="AuroraRDS")` 반환
    - Engine=`"aurora-postgresql"` + Monitoring=on → `ResourceInfo(type="AuroraRDS")` 반환
    - Engine=`"aurora"` + Monitoring=on → `ResourceInfo(type="AuroraRDS")` 반환
    - Engine=`"mysql"` + Monitoring=on → `ResourceInfo(type="RDS")` 반환 (기존 동작 유지)
    - Engine=`"aurora-mysql"` + status=`"deleting"` → 스킵
    - Engine=`"aurora-mysql"` + Monitoring 태그 없음 → 스킵
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_
  - [ ] 2.2 `collect_monitored_resources()` 수정 — Engine 기반 Aurora 분류 로직 추가
    - `db["Engine"]`에서 `"aurora" in engine.lower()` → `type="AuroraRDS"`, else `type="RDS"`
    - 기존 skip 로직(deleting/deleted), Monitoring=on 체크 유지
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_
  - [ ] 2.3 `get_aurora_metrics()` 단위 테스트 작성 (tests/test_collectors.py)
    - moto로 CloudWatch 데이터포인트 mock → 5개 메트릭 키 반환 확인
    - FreeableMemory bytes→GB 변환 정확성 확인
    - FreeLocalStorage bytes→GB 변환 정확성 확인
    - AuroraReplicaLagMaximum → raw μs 값 반환 확인
    - 개별 메트릭 데이터 없음 → 해당 키 skip
    - 전체 메트릭 데이터 없음 → None 반환
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_
  - [ ] 2.4 `get_aurora_metrics()` 구현 (common/collectors/rds.py)
    - 기존 `_collect_metric()` 헬퍼 + `query_metric()` 재사용
    - CPUUtilization→"CPU", FreeableMemory(bytes→GB)→"FreeMemoryGB", DatabaseConnections→"Connections", FreeLocalStorage(bytes→GB)→"FreeLocalStorageGB", AuroraReplicaLagMaximum→"ReplicaLag"
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_
  - [ ]* 2.5 Property 1 PBT 작성 (tests/test_pbt_aurora_rds.py)
    - **Property 1: Engine-based Aurora Classification**
    - 임의의 engine 문자열에 대해 "aurora" 포함 여부와 분류 결과 일치 검증
    - **Validates: Requirements 1.1, 1.2, 1.3**
  - [ ]* 2.6 Property 2 PBT 작성 (tests/test_pbt_aurora_rds.py)
    - **Property 2: Bytes-to-GB Conversion Consistency**
    - 임의의 양의 float에 대해 GB→bytes→GB 라운드트립 검증
    - **Validates: Requirements 2.4, 2.6, 4.2, 4.3**

- [ ] 3. Checkpoint — Collector 기능 검증
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Alarm Manager Aurora 확장 (common/alarm_manager.py)
  - [ ] 4.1 `_AURORA_RDS_ALARMS` 정의 + `_get_alarm_defs()` 단위 테스트 작성 (tests/test_alarm_manager.py)
    - `_get_alarm_defs("AuroraRDS")` → 5개 알람 정의 반환
    - 각 정의의 metric, namespace, metric_name, dimension_key, comparison, stat 검증
    - FreeableMemory/FreeLocalStorage의 `transform_threshold` GB→bytes 변환 검증
    - ReplicaLag의 stat="Maximum" 검증
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_
  - [ ] 4.2 `_AURORA_RDS_ALARMS` 상수 + `_get_alarm_defs()` 수정 구현
    - 5개 알람 정의 리스트 추가 (CPU, FreeMemoryGB, Connections, FreeLocalStorageGB, ReplicaLag)
    - `_get_alarm_defs()`에 `elif resource_type == "AuroraRDS": return _AURORA_RDS_ALARMS` 추가
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_
  - [ ] 4.3 Alarm Manager 보조 매핑 업데이트 단위 테스트 작성 (tests/test_alarm_manager.py)
    - `_METRIC_DISPLAY`에 `"FreeLocalStorageGB"`, `"ReplicaLag"` 엔트리 존재 확인
    - `_HARDCODED_METRIC_KEYS["AuroraRDS"]` == `{"CPU", "FreeMemoryGB", "Connections", "FreeLocalStorageGB", "ReplicaLag"}` 확인
    - `_NAMESPACE_MAP["AuroraRDS"]` == `["AWS/RDS"]` 확인
    - `_DIMENSION_KEY_MAP["AuroraRDS"]` == `"DBInstanceIdentifier"` 확인
    - _Requirements: 5.3, 5.4_
  - [ ] 4.4 보조 매핑 업데이트 구현 (common/alarm_manager.py)
    - `_METRIC_DISPLAY`에 `"FreeLocalStorageGB": ("FreeLocalStorage", "<", "GB")`, `"ReplicaLag": ("AuroraReplicaLagMaximum", ">", "μs")` 추가
    - `_HARDCODED_METRIC_KEYS`에 `"AuroraRDS"` 엔트리 추가
    - `_NAMESPACE_MAP`에 `"AuroraRDS": ["AWS/RDS"]` 추가
    - `_DIMENSION_KEY_MAP`에 `"AuroraRDS": "DBInstanceIdentifier"` 추가
    - `_find_alarms_for_resource()` 기본 type_prefixes에 `"AuroraRDS"` 추가
    - _Requirements: 5.3, 5.4, 8.1, 8.2_
  - [ ] 4.5 Aurora 알람 생성 통합 테스트 작성 (tests/test_alarm_manager.py)
    - moto로 AuroraRDS 인스턴스 알람 생성 → 알람 이름 `[AuroraRDS] ...` 프리픽스 확인
    - AlarmDescription JSON에 `"resource_type":"AuroraRDS"` 포함 확인
    - 디멘션 `DBInstanceIdentifier` 사용 확인
    - FreeMemoryGB/FreeLocalStorageGB 알람의 CloudWatch threshold가 GB→bytes 변환된 값 확인
    - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - [ ] 4.6 알람 생성 코드 검증 — 기존 `_build_dimensions()`, `_create_standard_alarm()` 동작 확인
    - AuroraRDS는 else 분기(`{"Name": dim_key, "Value": resource_id}`)로 처리됨을 확인
    - 추가 코드 변경 불필요 시 테스트만으로 검증 완료
    - _Requirements: 5.4_
  - [ ]* 4.7 Property 3 PBT 작성 (tests/test_pbt_aurora_rds.py)
    - **Property 3: Aurora Alarm Name Prefix and Metadata**
    - 임의의 AuroraRDS resource_id와 메트릭에 대해 알람 이름 프리픽스 `[AuroraRDS] ` 및 메타데이터 검증
    - **Validates: Requirements 5.1, 5.2**
  - [ ]* 4.8 Property 7 PBT 작성 (tests/test_pbt_aurora_rds.py)
    - **Property 7: Tag-Based Threshold Override for AuroraRDS**
    - 임의의 양의 threshold 태그 값에 대해 알람 임계치가 태그 값(또는 transform 적용 값) 사용 검증
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5**

- [ ] 5. Checkpoint — Alarm Manager 기능 검증
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Alarm Search + Orphan Cleanup Aurora 지원 (alarm_manager.py + daily_monitor)
  - [ ] 6.1 `_find_alarms_for_resource()` AuroraRDS 검색 단위 테스트 작성 (tests/test_alarm_manager.py)
    - `_find_alarms_for_resource(db_id, "AuroraRDS")` → `[AuroraRDS] ` 프리픽스 + `(db_id)` 서픽스 필터 확인
    - resource_type 미지정 시 `[AuroraRDS] ` 프리픽스도 검색 대상에 포함 확인
    - _Requirements: 8.1, 8.2_
  - [ ] 6.2 `_classify_alarm()` AuroraRDS 분류 단위 테스트 작성 (tests/test_alarm_manager.py 또는 tests/test_daily_monitor.py)
    - `[AuroraRDS] my-aurora CPUUtilization >80% (my-aurora-db)` → type=`"AuroraRDS"`, id=`"my-aurora-db"` 추출 확인
    - _Requirements: 7.2_
  - [ ] 6.3 `_cleanup_orphan_alarms()` AuroraRDS 등록 단위 테스트 작성 (tests/test_daily_monitor.py)
    - alive_checkers에 `"AuroraRDS"` 키 존재 확인
    - AuroraRDS 알람 + DB 인스턴스 미존재 → 고아 알람 삭제 확인
    - _Requirements: 7.1, 7.2, 7.3_
  - [ ] 6.4 `_cleanup_orphan_alarms()` 수정 — alive_checkers에 `"AuroraRDS": _find_alive_rds_instances` 추가
    - _Requirements: 7.1_
  - [ ]* 6.5 Property 4 PBT 작성 (tests/test_pbt_aurora_rds.py)
    - **Property 4: Alarm Classification from Name Prefix**
    - 임의의 `[AuroraRDS] ... (db_id)` 패턴 알람 이름에서 type/id 추출 정확성 검증
    - **Validates: Requirements 7.2**
  - [ ]* 6.6 Property 5 PBT 작성 (tests/test_pbt_aurora_rds.py)
    - **Property 5: Alarm Search Prefix and Suffix**
    - 임의의 db_instance_id에 대해 AuroraRDS 알람 검색 프리픽스/서픽스 정확성 검증
    - **Validates: Requirements 8.1, 8.2**

- [ ] 7. Checkpoint — Alarm Search + Orphan Cleanup 검증
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Daily Monitor AuroraRDS 메트릭 라우팅 (daily_monitor/lambda_handler.py)
  - [ ] 8.1 `_process_resource()` AuroraRDS 라우팅 단위 테스트 작성 (tests/test_daily_monitor.py)
    - resource_type=`"AuroraRDS"` → `collector_mod.get_aurora_metrics()` 호출 확인
    - `FreeLocalStorageGB` 메트릭의 less-than 비교 확인 (값 < 임계치 → 알림)
    - resource_type=`"RDS"` → 기존 `get_metrics()` 호출 유지 확인
    - _Requirements: 6.1, 6.2, 6.3_
  - [ ] 8.2 `_process_resource()` 수정 — AuroraRDS 메트릭 수집 라우팅 추가
    - `if resource_type == "AuroraRDS": metrics = collector_mod.get_aurora_metrics(resource_id, resource_tags)`
    - less-than 비교 세트에 `"FreeLocalStorageGB"` 추가
    - _Requirements: 6.2, 6.3_

- [ ] 9. Tag Resolver AuroraRDS 지원 (common/tag_resolver.py)
  - [ ] 9.1 `get_resource_tags()` AuroraRDS 단위 테스트 작성 (tests/test_tag_resolver.py)
    - resource_type=`"AuroraRDS"` → RDS와 동일한 `_get_rds_tags()` 경로 사용 확인
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_
  - [ ] 9.2 `get_resource_tags()` 수정 — `"AuroraRDS"` 분기 추가
    - `elif resource_type in ("RDS", "AuroraRDS"):` 로 변경
    - _Requirements: 10.1_

- [ ] 10. Remediation Handler Aurora 해석 (remediation_handler/lambda_handler.py)
  - [ ] 10.1 `_resolve_rds_aurora_type()` 단위 테스트 작성 (tests/test_remediation_handler.py)
    - Engine=`"aurora-mysql"` → `"AuroraRDS"` 반환
    - Engine=`"mysql"` → `"RDS"` 반환
    - API 오류 시 → `"RDS"` 폴백 + warning 로그
    - _Requirements: 9.1, 9.5_
  - [ ] 10.2 `_resolve_rds_aurora_type()` 구현 (remediation_handler/lambda_handler.py)
    - `describe_db_instances(DBInstanceIdentifier=db_instance_id)` 호출
    - Engine에 `"aurora"` 포함 → `"AuroraRDS"`, 아니면 `"RDS"`
    - `ClientError` 시 `"RDS"` 폴백 + `logger.warning()`
    - _Requirements: 9.1, 9.5_
  - [ ] 10.3 `parse_cloudtrail_event()` Aurora 해석 통합 테스트 작성 (tests/test_remediation_handler.py)
    - CreateDBInstance + aurora-mysql engine → `resource_type="AuroraRDS"` 확인
    - DeleteDBInstance + aurora engine → `resource_type="AuroraRDS"` 확인
    - ModifyDBInstance + aurora engine → `resource_type="AuroraRDS"` 확인
    - AddTagsToResource + aurora engine → `resource_type="AuroraRDS"` 확인
    - RemoveTagsFromResource + aurora engine → `resource_type="AuroraRDS"` 확인
    - CreateDBInstance + mysql engine → `resource_type="RDS"` 유지 확인
    - _Requirements: 9.1, 9.2, 9.3, 9.4_
  - [ ] 10.4 `parse_cloudtrail_event()` 수정 — RDS 이벤트 후 Aurora 해석 호출
    - `_API_MAP`에서 `resource_type == "RDS"` 반환 후 `_resolve_rds_aurora_type()` 호출하여 세분화
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_
  - [ ] 10.5 `_execute_remediation()` AuroraRDS 분기 단위 테스트 작성 (tests/test_remediation_handler.py)
    - resource_type=`"AuroraRDS"` → `rds.stop_db_instance()` 호출 확인 (RDS와 동일 동작)
    - _Requirements: 9.2_
  - [ ] 10.6 `_execute_remediation()` 수정 — AuroraRDS 분기 추가
    - `if resource_type in ("RDS", "AuroraRDS"):` 로 변경 (또는 별도 elif)
    - _Requirements: 9.2_
  - [ ]* 10.7 Property 6 PBT 작성 (tests/test_pbt_aurora_rds.py)
    - **Property 6: RDS CloudTrail Event Aurora Resolution**
    - 임의의 DB instance ID + aurora/non-aurora engine에 대해 해석 결과 검증
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4**

- [ ] 11. Checkpoint — 전체 통합 검증
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. 통합 와이어링 및 최종 검증
  - [ ] 12.1 전체 모듈 import 정리 및 연결 확인
    - `daily_monitor/lambda_handler.py`에서 rds_collector가 AuroraRDS 리소스도 반환하는지 확인
    - `remediation_handler/lambda_handler.py`에서 `_resolve_rds_aurora_type` import 확인
    - `_remediation_action_name()`에 `"AuroraRDS": "STOPPED"` 추가
    - _Requirements: 6.1, 9.1_
  - [ ] 12.2 기존 테스트 회귀 검증
    - 기존 RDS/EC2/ELB/TG 테스트가 모두 통과하는지 확인
    - 기존 RDS 인스턴스(non-Aurora)의 동작 불변 확인
    - _Requirements: 전체_

- [ ] 13. Final checkpoint — 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- TDD 사이클: 각 기능 단위로 테스트 먼저 작성 → 구현 → 리팩터링
- Property 테스트는 `hypothesis` 라이브러리 사용, `@settings(max_examples=100)`
- PBT 파일: `tests/test_pbt_aurora_rds.py` (거버넌스 §8)
- 코딩 거버넌스: boto3 lru_cache 싱글턴, ClientError만 catch, 함수 복잡도 제한 준수
- 기존 RDS 코드를 확장하며 코드 중복 최소화 (거버넌스 §10)
- Aurora와 RDS는 동일한 `describe_db_instances` API를 공유하므로 alive_checker 재사용
