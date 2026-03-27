# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - FreeLocalStorageGB 고정 10GB 임계치 사용 (퍼센트 기반 해석 부재)
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: DocDB 및 Aurora RDS Provisioned 인스턴스에서 `_total_local_storage_bytes` 태그가 설정되지 않고, `_resolve_free_local_storage_threshold()` 함수가 존재하지 않아 모든 인스턴스에 10GB 고정 임계치가 적용되는 것을 확인
  - **Test file**: `tests/test_pbt_free_local_storage_pct_threshold_fault.py`
  - Bug Condition (from design): `isBugCondition(input)` where `input.metric == "FreeLocalStorageGB" AND input.resource_type IN ["AuroraRDS", "DocDB"] AND input.is_serverless == false AND NOT hasTag(input.tags, "Threshold_FreeLocalStorageGB")`
  - Expected Behavior (from design): `_resolve_free_local_storage_threshold(tags)` 호출 시 `_total_local_storage_bytes` 기반 퍼센트(기본 20%) 임계치 계산, `cw_bytes == 0.2 * _total_local_storage_bytes`
  - Test assertions:
    - `_resolve_free_local_storage_threshold()` 함수가 존재하고 호출 가능해야 함
    - `_total_local_storage_bytes`가 설정된 태그에서 `_resolve_free_local_storage_threshold(tags)`가 `(display_gb, cw_bytes)` 튜플을 반환하고, `cw_bytes == 0.2 * total_local_storage_bytes`이어야 함
    - 다양한 로컬 스토리지 용량(20GB~500GB)에서 임계치가 10GB 고정값이 아닌 퍼센트 기반이어야 함
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists: `_resolve_free_local_storage_threshold()` 함수가 없고, `_total_local_storage_bytes` 태그도 설정되지 않아 10GB 고정 폴백 발생)
  - Document counterexamples found (e.g., "`_resolve_free_local_storage_threshold` does not exist → ImportError" 또는 "DocDB db.t3.medium (20GB storage) → 10GB 고정 임계치 instead of 4GB (20%)")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.5_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - 기존 FreeMemoryGB 퍼센트 로직, Serverless v2 동작, GB 절대값 태그 오버라이드 보존
  - **IMPORTANT**: Follow observation-first methodology
  - **Test file**: `tests/test_pbt_free_local_storage_pct_threshold_preservation.py`
  - Observe on UNFIXED code:
    - `_resolve_free_memory_threshold({"_total_memory_bytes": "17179869184"})` → `(3.2, 3435973836.8)` (기존 FreeMemoryGB 20% 로직 불변)
    - `_resolve_free_memory_threshold({"Threshold_FreeMemoryPct": "30", "_total_memory_bytes": "17179869184"})` → 30% 기반 계산 (기존 태그 오버라이드 불변)
    - `_get_aurora_alarm_defs({"_is_serverless_v2": "true", ...})` → FreeLocalStorageGB 알람 미포함 (Serverless v2 동작 불변)
    - `get_threshold({"Threshold_FreeLocalStorageGB": "5"}, "FreeLocalStorageGB")` → `5.0` (GB 절대값 태그 동작 불변)
    - `is_threshold_off({"Threshold_FreeLocalStorageGB": "off"}, "FreeLocalStorageGB")` → `True` (off 태그 동작 불변)
    - `_get_alarm_defs("RDS")` → FreeLocalStorageGB 알람 미포함 (일반 RDS 동작 불변)
  - Write property-based tests:
    - Property 2a: `_resolve_free_memory_threshold()` 결과가 수정 전후 동일 (다양한 `_total_memory_bytes`, `Threshold_FreeMemoryPct`, `Threshold_FreeMemoryGB` 태그 조합)
    - Property 2b: Serverless v2 인스턴스에서 `_get_aurora_alarm_defs()` 결과에 FreeLocalStorageGB 알람이 포함되지 않음
    - Property 2c: `Threshold_FreeLocalStorageGB` 태그가 명시적으로 설정된 경우 `get_threshold()` → GB 절대값 사용
    - Property 2d: 일반 RDS(비Aurora) 인스턴스에서 `_get_alarm_defs("RDS")` 결과에 FreeLocalStorageGB 알람 미포함
    - Property 2e: FreeLocalStorageGB 이외 메트릭(CPU, Connections 등)의 `get_threshold()` 동작 불변
  - Verify tests pass on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 3. Fix for FreeLocalStorageGB 퍼센트 기반 임계치 적용

  - [x] 3.1 Add `FreeLocalStoragePct` to `HARDCODED_DEFAULTS` in `common/__init__.py`
    - `HARDCODED_DEFAULTS`에 `"FreeLocalStoragePct": 20.0` 추가
    - _Requirements: 2.3, 2.5_

  - [x] 3.2 Add `_resolve_free_local_storage_threshold()` to `common/alarm_manager.py`
    - `_resolve_free_memory_threshold()` 패턴을 그대로 따르는 3단계 폴백 체인:
      - 1단계: `Threshold_FreeLocalStoragePct` 태그 (명시적 퍼센트) + `_total_local_storage_bytes` 필요
      - 2단계: `_total_local_storage_bytes` 존재 시 `HARDCODED_DEFAULTS["FreeLocalStoragePct"]` (기본 20%) 자동 적용
      - 3단계: `get_threshold(resource_tags, "FreeLocalStorageGB")` GB 절대값 폴백
    - 반환: `(display_threshold_gb, cw_threshold_bytes)` 튜플
    - _Bug_Condition: isBugCondition(input) where input.metric == "FreeLocalStorageGB" AND input.resource_type IN ["AuroraRDS", "DocDB"] AND input.is_serverless == false_
    - _Expected_Behavior: cw_bytes == (pct / 100) * _total_local_storage_bytes, display_gb == round(cw_bytes / 1073741824, 2)_
    - _Preservation: _resolve_free_memory_threshold() 불변, FreeLocalStorageGB 이외 메트릭 불변_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 3.3 Add FreeLocalStorageGB branch to 4 alarm functions in `common/alarm_manager.py`
    - `_create_standard_alarm()`, `_sync_standard_alarms()`, `_create_single_alarm()`, `_recreate_standard_alarm()` 4개 함수에 동일 패턴 적용:
    - 기존 `if metric == "FreeMemoryGB":` 분기 아래에 `elif metric == "FreeLocalStorageGB":` 분기 추가
    - `threshold, cw_threshold = _resolve_free_local_storage_threshold(resource_tags)` 호출
    - _Requirements: 2.1, 2.5_

  - [x] 3.4 Exclude `Threshold_FreeLocalStoragePct` from `_parse_threshold_tags()` in `common/alarm_manager.py`
    - 기존 `if key == "Threshold_FreeMemoryPct": continue` → `if key in ("Threshold_FreeMemoryPct", "Threshold_FreeLocalStoragePct"): continue`
    - _Requirements: 2.2_

  - [x] 3.5 Add `_lookup_instance_class_local_storage()` helper to `common/collectors/rds.py`
    - `_lookup_instance_class_memory()` 패턴을 따르는 로컬 스토리지 조회 함수
    - 모듈 레벨 캐시: `_instance_class_local_storage_cache: dict[str, int | None]`
    - 캐시 hit → 즉시 반환 (API 실패 None도 캐시)
    - 캐시 miss → `describe_db_instance_classes` API 호출 → `StorageInfo` 또는 `MaxStorageSize` 필드에서 로컬 스토리지 용량 추출 (GiB → bytes 변환)
    - API 실패 시 None 반환 + warning 로그
    - _Requirements: 2.3, 2.4_

  - [x] 3.6 Enrich `_total_local_storage_bytes` in `_enrich_aurora_metadata()` (Provisioned 분기) in `common/collectors/rds.py`
    - Provisioned Aurora 인스턴스에서 `_lookup_instance_class_local_storage(instance_class)` 호출
    - 조회 성공 시 `tags["_total_local_storage_bytes"] = str(local_storage_bytes)` 설정
    - 조회 실패 시 warning 로그 + 태그 미설정 (3단계 폴백으로 진입)
    - _Requirements: 2.1, 2.3_

  - [x] 3.7 Enrich `_total_local_storage_bytes` in DocDB `collect_monitored_resources()` in `common/collectors/docdb.py`
    - `_lookup_instance_class_local_storage()` 함수를 `common/collectors/rds.py`에서 import
    - 인스턴스 클래스 정보는 `db["DBInstanceClass"]`에서 추출
    - 조회 성공 시 `tags["_total_local_storage_bytes"] = str(local_storage_bytes)` 설정
    - 조회 실패 시 warning 로그 + 태그 미설정
    - _Requirements: 2.1, 2.3_

  - [x] 3.8 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - FreeLocalStorageGB 퍼센트 기반 임계치 적용 확인
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run `pytest tests/test_pbt_free_local_storage_pct_threshold_fault.py -v`
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed: `_resolve_free_local_storage_threshold()`가 `_total_local_storage_bytes` 기반 퍼센트 임계치를 계산)
    - _Requirements: 2.1, 2.2, 2.3, 2.5_

  - [x] 3.9 Verify preservation tests still pass
    - **Property 2: Preservation** - 기존 FreeMemoryGB 퍼센트 로직, Serverless v2 동작, GB 절대값 태그 오버라이드 보존
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run `pytest tests/test_pbt_free_local_storage_pct_threshold_preservation.py -v`
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions: FreeMemoryGB 로직 불변, Serverless v2 동작 불변, GB 태그 오버라이드 유지)
    - Confirm all tests still pass after fix (no regressions)

- [x] 4. Checkpoint - Ensure all tests pass
  - Run `pytest tests/ -v` to verify all existing tests + new PBT tests pass
  - Ensure no regressions in `test_collectors.py`, `test_alarm_manager.py`, `test_pbt_freemem_pct_threshold_fault.py`, `test_pbt_freemem_pct_threshold_preservation.py` etc.
  - Ensure all tests pass, ask the user if questions arise.
