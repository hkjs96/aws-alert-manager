# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - 매핑 누락 인스턴스 클래스의 `_total_memory_bytes` 미설정
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: `_INSTANCE_CLASS_MEMORY_MAP`에 없는 인스턴스 클래스(db.r5.large, db.r6i.large, db.m6i.xlarge, db.t3.nano 등)를 대상으로 property 스코핑
  - **Test file**: `tests/test_pbt_freemem_pct_threshold_fault.py`
  - Bug Condition (from design): `isBugCondition(input)` where `input.is_serverless == false AND input.instance_class NOT IN _INSTANCE_CLASS_MEMORY_MAP AND input.instance_class starts with "db." AND input.instance_class != "db.serverless"`
  - Expected Behavior (from design): enrichment 함수 호출 후 `"_total_memory_bytes" IN tags` AND `_resolve_free_memory_threshold(tags)`가 2단계(퍼센트 기반, 기본 20%)를 적용하여 `실제 메모리 * 0.2`를 임계치로 계산
  - Test assertions:
    - `_enrich_rds_memory(db_instance, tags)` 호출 후 `tags["_total_memory_bytes"]`가 설정되어야 함
    - `_enrich_aurora_metadata(db_instance, tags, cluster_cache)` 호출 후 `tags["_total_memory_bytes"]`가 설정되어야 함
    - `_resolve_free_memory_threshold(tags)`가 3단계 폴백(2GB)이 아닌 2단계(퍼센트 기반)를 적용해야 함
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists: 매핑에 없는 인스턴스 클래스에서 `_total_memory_bytes`가 설정되지 않아 2GB 고정 폴백 발생)
  - Document counterexamples found (e.g., "`_enrich_rds_memory({'DBInstanceClass': 'db.r5.large', ...}, tags)` → `_total_memory_bytes` not in tags → `_resolve_free_memory_threshold` returns (2.0, 2147483648) instead of percent-based threshold")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - 정적 매핑 및 기존 임계치 로직 보존
  - **IMPORTANT**: Follow observation-first methodology
  - **Test file**: `tests/test_pbt_freemem_pct_threshold_preservation.py`
  - Observe on UNFIXED code:
    - `_enrich_rds_memory({'DBInstanceClass': 'db.t3.medium', ...}, tags)` → `tags["_total_memory_bytes"] == str(4 * 1024**3)` (정적 매핑 hit)
    - `_enrich_aurora_metadata({'DBInstanceClass': 'db.r6g.large', ...}, tags, cache)` → `tags["_total_memory_bytes"] == str(16 * 1024**3)` (정적 매핑 hit)
    - `_resolve_free_memory_threshold({"_total_memory_bytes": "17179869184"})` → `(3.2, 3435973836.8)` (기본 20%)
    - `_resolve_free_memory_threshold({"Threshold_FreeMemoryGB": "5"})` → `(5.0, 5368709120.0)` (GB 절대값 폴백)
    - `_resolve_free_memory_threshold({"_is_serverless_v2": "true", "_total_memory_bytes": "..."})` → GB 절대값만 사용
  - Write property-based tests:
    - Property 2a: `_INSTANCE_CLASS_MEMORY_MAP`에 있는 인스턴스 클래스를 무작위 선택 → `_enrich_rds_memory()` 호출 → `tags["_total_memory_bytes"]`가 정적 매핑 값과 동일
    - Property 2b: `_INSTANCE_CLASS_MEMORY_MAP`에 있는 인스턴스 클래스를 무작위 선택 → `_enrich_aurora_metadata()` 호출 (non-serverless) → `tags["_total_memory_bytes"]`가 정적 매핑 값과 동일
    - Property 2c: Serverless v2 인스턴스 → `_resolve_free_memory_threshold()`가 GB 절대값만 사용 (퍼센트 기반 스킵)
    - Property 2d: `Threshold_FreeMemoryPct` 태그 명시 시 → 태그 값 기반 퍼센트 임계치 우선 적용
    - Property 2e: `Threshold_FreeMemoryGB` 태그 명시 시 + `_total_memory_bytes` 미존재 → GB 절대값 사용
  - Verify tests pass on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 3. Fix for 매핑 누락 인스턴스 클래스의 동적 메모리 조회

  - [x] 3.1 Implement `_lookup_instance_class_memory()` helper and integrate into enrichment functions
    - `common/collectors/rds.py`에 `_instance_class_memory_cache: dict[str, int | None]` 모듈 레벨 캐시 딕셔너리 추가
    - `_lookup_instance_class_memory(instance_class: str) -> int | None` 헬퍼 함수 추가:
      - 1순위: `_INSTANCE_CLASS_MEMORY_MAP.get(instance_class)` 정적 매핑 조회
      - 2순위: `_instance_class_memory_cache` 캐시 조회 (API 실패 결과 `None`도 캐시)
      - 3순위: `describe_db_instance_classes(DBInstanceClass=instance_class)` API 호출 → `DBInstanceClasses[0].Memory` (MiB) → bytes 변환 (`* 1024 * 1024`)
      - API 실패 시 `None` 반환 + warning 로그 + 캐시에 `None` 저장
    - `_enrich_aurora_metadata()` Provisioned 분기 수정: `_INSTANCE_CLASS_MEMORY_MAP.get()` → `_lookup_instance_class_memory()` 호출
    - `_enrich_rds_memory()` 수정: `_INSTANCE_CLASS_MEMORY_MAP.get()` → `_lookup_instance_class_memory()` 호출
    - `_resolve_free_memory_threshold()` 자체는 변경하지 않음
    - _Bug_Condition: isBugCondition(input) where input.is_serverless == false AND input.instance_class NOT IN _INSTANCE_CLASS_MEMORY_MAP_
    - _Expected_Behavior: enrichment 후 tags["_total_memory_bytes"] == API 응답 메모리 bytes, _resolve_free_memory_threshold()가 2단계(퍼센트 기반 20%) 적용_
    - _Preservation: 정적 매핑 hit 시 API 호출 없음, Serverless v2 동작 불변, 태그 오버라이드 우선순위 유지, FreeMemoryGB 이외 메트릭 불변_
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - 매핑 누락 인스턴스 클래스의 동적 메모리 조회 성공
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run `pytest tests/test_pbt_freemem_pct_threshold_fault.py -v`
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed: `_lookup_instance_class_memory()`가 API로 메모리를 동적 조회하여 `_total_memory_bytes` 설정)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - 정적 매핑 및 기존 임계치 로직 보존
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run `pytest tests/test_pbt_freemem_pct_threshold_preservation.py -v`
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions: 정적 매핑 인스턴스, Serverless v2, 태그 오버라이드 모두 기존 동작 유지)
    - Confirm all tests still pass after fix (no regressions)

- [x] 4. Checkpoint - Ensure all tests pass
  - Run `pytest tests/ -v` to verify all existing tests + new PBT tests pass
  - Ensure no regressions in `test_collectors.py`, `test_alarm_manager.py` etc.
  - Ensure all tests pass, ask the user if questions arise.
