# Implementation Plan: alarm-manager-modularize

## Overview

`alarm_manager.py`(2086줄)를 책임별 7개 모듈로 분리하고, Facade 패턴으로 전환하는 리팩터링 구현 계획이다. 의존성 없는 모듈부터 추출하여 각 단계마다 전체 테스트(607개) 통과를 보장한다.

## Tasks

### Phase 1: 바닥부터 추출 (의존성 없는 모듈 먼저)

- [x] 1. `common/alarm_registry.py` 추출 — 순수 데이터 모듈
  - [x] 1.1 `common/alarm_registry.py` 생성 및 알람 정의 데이터 이동
    - `alarm_manager.py`에서 `_EC2_ALARMS`, `_RDS_ALARMS`, `_ALB_ALARMS`, `_NLB_ALARMS`, `_TG_ALARMS`, `_AURORA_RDS_ALARMS`, `_DOCDB_ALARMS` 7개 알람 정의 리스트를 이동
    - `_AURORA_READER_REPLICA_LAG`, `_AURORA_ACU_UTILIZATION`, `_AURORA_SERVERLESS_CAPACITY` 보조 정의 이동
    - `_HARDCODED_METRIC_KEYS`, `_NAMESPACE_MAP`, `_DIMENSION_KEY_MAP`, `_METRIC_DISPLAY`, `_NLB_TG_EXCLUDED_METRICS` 매핑 테이블 이동
    - `_get_alarm_defs()`, `_get_aurora_alarm_defs()`, `_get_hardcoded_metric_keys()`, `_metric_name_to_key()` 함수 이동
    - public 인터페이스: `get_alarm_defs()`, `get_hardcoded_metric_keys()`, `metric_name_to_key()`, `get_metric_display()`, `get_namespace_list()`, `get_dimension_key()` 제공
    - `logger = logging.getLogger(__name__)` 패턴 적용
    - _Requirements: 1.2, 2.1, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 6.1, 6.2, 6.3, 6.4, 6.5, 9.2, 9.5, 11.2_
  - [x] 1.2 `alarm_manager.py`에서 alarm_registry re-export 추가
    - `from common.alarm_registry import get_alarm_defs as _get_alarm_defs` 등 기존 내부 심볼을 re-export
    - `_HARDCODED_METRIC_KEYS`, `_METRIC_DISPLAY`, `_NAMESPACE_MAP`, `_DIMENSION_KEY_MAP`, `_metric_name_to_key` 등 모든 참조 심볼 re-export
    - 원본 데이터/함수 정의를 `alarm_manager.py`에서 제거
    - _Requirements: 3.4, 3.5, 8.1_
  - [x]* 1.3 Property test: 레지스트리 완전성 검증
    - **Property 2: 레지스트리 완전성 (Registry Completeness)**
    - `tests/test_pbt_registry_completeness.py` 생성
    - ∀ resource_type ∈ SUPPORTED_RESOURCE_TYPES: `get_alarm_defs(resource_type)` 반환 메트릭 집합이 리팩터링 전과 동일
    - **Validates: Requirements 4.1, 6.1, 6.2**

- [x] 2. Checkpoint — Phase 1 Step 1 검증
  - 전체 테스트 실행 (`pytest tests/ -q`), 607개 통과 확인
  - 실패 시 즉시 롤백하고 원인 분석
  - _Requirements: 8.1, 8.2_

- [x] 3. `common/alarm_naming.py` 추출 — alarm_registry만 의존
  - [x] 3.1 `common/alarm_naming.py` 생성 및 이름/메타데이터 함수 이동
    - `_pretty_alarm_name()`, `_alarm_name()`, `_build_alarm_description()`, `_parse_alarm_metadata()`, `_shorten_elb_resource_id()` 함수 이동
    - `alarm_registry`에서 `METRIC_DISPLAY` 참조 (import)
    - public 인터페이스: `pretty_alarm_name()`, `legacy_alarm_name()`, `build_alarm_description()`, `parse_alarm_metadata()`, `shorten_elb_resource_id()` 제공
    - `functools.lru_cache` 기반 boto3 클라이언트 불필요 (순수 로직 모듈)
    - `logger = logging.getLogger(__name__)` 패턴 적용
    - _Requirements: 1.5, 2.3, 9.2, 9.5_
  - [x] 3.2 `alarm_manager.py`에서 alarm_naming re-export 추가
    - `from common.alarm_naming import pretty_alarm_name as _pretty_alarm_name` 등 re-export
    - 원본 함수 정의를 `alarm_manager.py`에서 제거
    - _Requirements: 3.4, 3.5, 8.1_

- [x] 4. Checkpoint — Phase 1 Step 2 검증
  - 전체 테스트 실행 (`pytest tests/ -q`), 607개 통과 확인
  - 실패 시 즉시 롤백하고 원인 분석
  - _Requirements: 8.1, 8.2_

- [x] 5. `common/threshold_resolver.py` 추출 — alarm_registry, tag_resolver만 의존
  - [x] 5.1 `common/threshold_resolver.py` 생성 및 임계치 해석 로직 이동
    - `_resolve_free_memory_threshold()`, `_resolve_free_local_storage_threshold()` 함수 이동
    - 통합 `resolve_threshold(alarm_def, resource_tags)` 진입점 함수 구현
    - 4곳 중복 if/elif 분기를 단일 함수로 통합 (FreeMemoryGB, FreeLocalStorageGB, transform_threshold, 일반 메트릭)
    - `alarm_registry`에서 필요한 데이터 import, `common.tag_resolver`에서 `get_threshold` import
    - `logger = logging.getLogger(__name__)` 패턴 적용
    - _Requirements: 1.3, 2.2, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 9.2, 9.5, 10.2, 10.3_
  - [x] 5.2 `alarm_manager.py`에서 threshold_resolver re-export 추가
    - `from common.threshold_resolver import resolve_free_memory_threshold as _resolve_free_memory_threshold` 등 re-export
    - 원본 함수 정의를 `alarm_manager.py`에서 제거
    - _Requirements: 3.4, 3.5, 8.1_
  - [x]* 5.3 Property test: 임계치 해석 동등성 검증
    - **Property 3: 임계치 해석 동등성 (Threshold Resolution Equivalence)**
    - `tests/test_pbt_threshold_equivalence.py` 생성
    - ∀ alarm_def, resource_tags: `resolve_threshold(alarm_def, tags)` == 기존 4곳 if/elif 분기 결과
    - **Validates: Requirements 5.1, 5.6**

- [x] 6. Checkpoint — Phase 1 Step 3 검증
  - 전체 테스트 실행 (`pytest tests/ -q`), 607개 통과 확인
  - 실패 시 즉시 롤백하고 원인 분석
  - _Requirements: 8.1, 8.2_

- [x] 7. `common/dimension_builder.py` 추출 — alarm_registry, alarm_naming만 의존
  - [x] 7.1 `common/dimension_builder.py` 생성 및 디멘션 빌드 함수 이동
    - `_build_dimensions()`, `_extract_elb_dimension()`, `_resolve_tg_namespace()`, `_resolve_metric_dimensions()`, `_select_best_dimensions()`, `_get_disk_dimensions()` 함수 이동
    - `alarm_registry`에서 `NAMESPACE_MAP`, `DIMENSION_KEY_MAP` import
    - `alarm_naming`에서 `shorten_elb_resource_id` import (ELB 디멘션 추출에 필요 시)
    - `functools.lru_cache` 기반 `_get_cw_client()` 싱글턴 패턴 적용
    - `logger = logging.getLogger(__name__)` 패턴 적용
    - _Requirements: 1.4, 2.4, 9.1, 9.2, 9.4, 9.5, 10.1, 11.1_
  - [x] 7.2 `alarm_manager.py`에서 dimension_builder re-export 추가
    - `from common.dimension_builder import build_dimensions as _build_dimensions` 등 re-export
    - 원본 함수 정의를 `alarm_manager.py`에서 제거
    - _Requirements: 3.4, 3.5, 8.1_

- [x] 8. Checkpoint — Phase 1 완료 검증
  - 전체 테스트 실행 (`pytest tests/ -q`), 607개 통과 확인
  - Phase 1 완료: alarm_registry, alarm_naming, threshold_resolver, dimension_builder 4개 모듈 추출 완료
  - 실패 시 즉시 롤백하고 원인 분석
  - _Requirements: 8.1, 8.2, 8.3_

### Phase 2: 로직 모듈 추출

- [x] 9. `common/alarm_search.py` 추출 — alarm_naming만 의존
  - [x] 9.1 `common/alarm_search.py` 생성 및 검색/삭제 함수 이동
    - `_find_alarms_for_resource()`, `_delete_all_alarms_for_resource()`, `_describe_alarms_batch()`, `_delete_alarm_names()` 함수 이동
    - `alarm_naming`에서 `shorten_elb_resource_id` import
    - `functools.lru_cache` 기반 `_get_cw_client()` 싱글턴 패턴 적용
    - `botocore.exceptions.ClientError`만 catch (거버넌스 §4)
    - `logger = logging.getLogger(__name__)` 패턴 적용
    - _Requirements: 1.7, 2.5, 9.1, 9.2, 9.4, 9.5, 10.1, 11.1_
  - [x] 9.2 `alarm_manager.py`에서 alarm_search re-export 추가
    - `from common.alarm_search import find_alarms_for_resource as _find_alarms_for_resource` 등 re-export
    - 원본 함수 정의를 `alarm_manager.py`에서 제거
    - _Requirements: 3.4, 3.5, 8.1_

- [x] 10. Checkpoint — Phase 2 Step 1 검증
  - 전체 테스트 실행 (`pytest tests/ -q`), 607개 통과 확인
  - 실패 시 즉시 롤백하고 원인 분석
  - _Requirements: 8.1, 8.2_

- [x] 11. `common/alarm_builder.py` 추출 — alarm_registry, threshold_resolver, dimension_builder, alarm_naming 의존
  - [x] 11.1 `common/alarm_builder.py` 생성 및 알람 생성 함수 이동
    - `_create_standard_alarm()`, `_create_disk_alarms()`, `_create_dynamic_alarm()`, `_create_single_alarm()`, `_recreate_alarm_by_name()`, `_recreate_standard_alarm()`, `_recreate_disk_alarm()` 함수 이동
    - 기존 4곳 FreeMemoryGB/FreeLocalStorageGB if/elif 분기를 `threshold_resolver.resolve_threshold()` 단일 호출로 교체
    - `alarm_registry`, `threshold_resolver`, `dimension_builder`, `alarm_naming` import
    - `functools.lru_cache` 기반 `_get_cw_client()` 싱글턴 패턴 적용
    - `botocore.exceptions.ClientError`만 catch (거버넌스 §4)
    - `logger = logging.getLogger(__name__)` 패턴 적용
    - _Requirements: 1.6, 2.6, 5.6, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 11.1_
  - [x] 11.2 `alarm_manager.py`에서 alarm_builder re-export 추가
    - `from common.alarm_builder import create_standard_alarm as _create_standard_alarm` 등 re-export
    - 원본 함수 정의를 `alarm_manager.py`에서 제거
    - _Requirements: 3.4, 3.5, 8.1_

- [x] 12. Checkpoint — Phase 2 Step 2 검증
  - 전체 테스트 실행 (`pytest tests/ -q`), 607개 통과 확인
  - 실패 시 즉시 롤백하고 원인 분석
  - _Requirements: 8.1, 8.2_

- [x] 13. `common/alarm_sync.py` 추출 — alarm_registry, threshold_resolver, alarm_builder, alarm_search 의존
  - [x] 13.1 `common/alarm_sync.py` 생성 및 동기화 함수 이동
    - `_sync_standard_alarms()`, `_sync_disk_alarms()`, `_sync_off_hardcoded()`, `_sync_dynamic_alarms()`, `_apply_sync_changes()` 함수 이동
    - 기존 FreeMemoryGB/FreeLocalStorageGB if/elif 분기를 `threshold_resolver.resolve_threshold()` 단일 호출로 교체
    - `alarm_registry`, `threshold_resolver`, `alarm_builder`, `alarm_search` import
    - `functools.lru_cache` 기반 `_get_cw_client()` 싱글턴 패턴 적용
    - `botocore.exceptions.ClientError`만 catch (거버넌스 §4)
    - `logger = logging.getLogger(__name__)` 패턴 적용
    - _Requirements: 1.8, 2.7, 5.6, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 11.1_
  - [x] 13.2 `alarm_manager.py`에서 alarm_sync re-export 추가
    - `from common.alarm_sync import ...` 등 re-export
    - 원본 함수 정의를 `alarm_manager.py`에서 제거
    - _Requirements: 3.4, 3.5, 8.1_

- [x] 14. Checkpoint — Phase 2 완료 검증
  - 전체 테스트 실행 (`pytest tests/ -q`), 607개 통과 확인
  - Phase 2 완료: alarm_search, alarm_builder, alarm_sync 3개 모듈 추출 완료
  - 실패 시 즉시 롤백하고 원인 분석
  - _Requirements: 8.1, 8.2, 8.3_

### Phase 3: Facade 전환 + 호환성

- [x] 15. `alarm_manager.py`를 Facade로 전환
  - [x] 15.1 `alarm_manager.py`를 Facade 모듈로 정리
    - `create_alarms_for_resource()`, `delete_alarms_for_resource()`, `sync_alarms_for_resource()` 3개 public 함수가 내부 모듈에 위임하도록 전환
    - `_parse_threshold_tags()` 함수는 `alarm_manager.py`에 잔류하거나 `alarm_registry.py`로 이동 (설계 문서 기준)
    - 모든 re-export가 올바르게 설정되어 `from common.alarm_manager import X` 호환성 유지
    - 불필요한 코드 제거, Facade 역할에 맞게 간결화 (~80줄 목표)
    - `logger = logging.getLogger(__name__)` 패턴 유지
    - _Requirements: 1.1, 2.8, 3.1, 3.2, 3.3, 3.4, 3.5, 9.5_
  - [x] 15.2 모듈 의존성 DAG 검증
    - 각 모듈의 import 구문을 확인하여 순환 의존성이 없는지 검증
    - alarm_registry → (없음), alarm_naming → alarm_registry, threshold_resolver → alarm_registry + tag_resolver, dimension_builder → alarm_registry + alarm_naming, alarm_search → alarm_naming, alarm_builder → alarm_registry + threshold_resolver + dimension_builder + alarm_naming, alarm_sync → alarm_registry + threshold_resolver + alarm_builder + alarm_search, alarm_manager → alarm_builder + alarm_search + alarm_sync + alarm_registry
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9_

- [x] 16. Checkpoint — Facade 전환 검증
  - 전체 테스트 실행 (`pytest tests/ -q`), 607개 통과 확인
  - 실패 시 즉시 롤백하고 원인 분석
  - _Requirements: 3.5, 8.1, 8.2_

- [x] 17. 테스트 자동 참조 전환 (선택적 개선)
  - [x] 17.1 기존 테스트의 하드코딩 알람 개수를 레지스트리 참조로 전환
    - `tests/test_pbt_dynamic_alarm_preservation.py` 등에서 `_EXPECTED_ALARM_COUNTS` 하드코딩을 `get_alarm_defs()` 기반 동적 계산으로 교체
    - `from common.alarm_registry import get_alarm_defs` 사용
    - 새 메트릭 추가 시 테스트 코드 수동 업데이트 불필요하도록 개선
    - _Requirements: 7.1, 7.2_

- [x] 18. Final Checkpoint — 전체 리팩터링 완료 검증
  - 전체 테스트 실행 (`pytest tests/ -q`), 607개 통과 확인
  - 기존 PBT 테스트 전부 통과 확인: `test_pbt_dynamic_alarm_preservation.py`, `test_pbt_expand_alb_rds_metrics.py`, `test_pbt_tg_alarm_lb_type_split.py`, `test_pbt_freemem_pct_threshold_preservation.py`, `test_pbt_free_local_storage_pct_threshold_preservation.py`
  - 모듈별 파일 크기 확인: alarm_registry ~450줄, alarm_naming ~150줄, threshold_resolver ~120줄, dimension_builder ~180줄, alarm_search ~120줄, alarm_builder ~300줄, alarm_sync ~250줄, alarm_manager(Facade) ~80줄
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 3.5, 6.1, 6.2, 6.3, 6.4, 6.5, 8.1, 8.3, 11.2, 11.3_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- 각 모듈 추출 단계마다 전체 테스트 실행 체크포인트를 포함하여 회귀 버그를 즉시 감지
- 리팩터링 실행 순서는 의존성 DAG 기반: alarm_registry → alarm_naming → threshold_resolver → dimension_builder → alarm_search → alarm_builder → alarm_sync → Facade 전환
- re-export를 통해 기존 `from common.alarm_manager import X` 호환성을 유지하므로 테스트 코드 변경 불필요
- Property tests validate universal correctness properties (레지스트리 완전성, 임계치 해석 동등성)
- 각 새 모듈은 코딩 거버넌스(§1~§4, §9)를 준수: lru_cache 싱글턴, import 순서, 함수 복잡도 제한, ClientError만 catch, 모듈별 logger