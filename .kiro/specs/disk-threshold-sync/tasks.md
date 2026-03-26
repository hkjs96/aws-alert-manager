# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Fault Condition** - 디스크 알람 경로별 임계치 조회 누락
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate `sync_alarms_for_resource` uses `"Disk"` key instead of `"Disk_{suffix}"` for path-specific thresholds
  - **Scoped PBT Approach**: For deterministic bug, scope property to concrete failing cases: disk alarms with path dimensions and path-specific tags (`Threshold_Disk_root`, `Threshold_Disk_data`)
  - **Test file**: `tests/test_pbt_disk_threshold_fault.py`
  - **Strategy**: Use hypothesis to generate disk paths (from a set like `/`, `/data`, `/var/log`) and corresponding threshold values (integers 1-100)
  - **Setup**: Mock `_get_cw_client()` to return `describe_alarms` response with disk alarms containing `Dimensions: [{Name: "path", Value: <path>}]` and `Threshold: <tag_threshold>`
  - **Setup**: Mock `_find_alarms_for_resource` to return alarm names containing `disk_used_percent`
  - **Setup**: Set `resource_tags` with `Threshold_Disk_{suffix}=<tag_threshold>` where suffix comes from `disk_path_to_tag_suffix(path)`
  - **Assertion**: When existing alarm threshold matches the path-specific tag threshold, the alarm should be in `result["ok"]` (not `result["updated"]`)
  - **Bug Condition from design**: `isBugCondition(input)` - resource has existing disk alarms with path dimensions AND resource_tags contains `Threshold_Disk_{disk_path_to_tag_suffix(path)}` AND `get_threshold(tags, "Disk") != get_threshold(tags, "Disk_{suffix}")`
  - Run test on UNFIXED code - expect FAILURE (confirms bug: `get_threshold` called with `"Disk"` instead of `"Disk_{suffix}"`)
  - **EXPECTED OUTCOME**: Test FAILS because sync uses `get_threshold(tags, "Disk")` → 80 (default) instead of `get_threshold(tags, "Disk_root")` → tag value, causing threshold mismatch and unnecessary recreate
  - Document counterexamples found to understand root cause
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - 비디스크 메트릭 및 기본값 폴백 동작 유지
  - **IMPORTANT**: Follow observation-first methodology
  - **Test file**: `tests/test_pbt_disk_threshold_preservation.py`
  - **Observation 1**: For non-disk metrics (CPU, Memory, etc.), `sync_alarms_for_resource` calls `get_threshold(resource_tags, metric)` with the metric name directly - this should be unchanged
  - **Observation 2**: For disk alarms without path-specific tags, `get_threshold(tags, "Disk_root")` falls back to default (80) - same as `get_threshold(tags, "Disk")` → 80
  - **Observation 3**: When no disk alarms exist, `needs_recreate = True` is set and `create_alarms_for_resource` is called
  - **Property test 1 - Non-disk metric preservation**: For any non-disk metric alarm (CPU, Memory, etc.) with any threshold tag value, sync result should be identical before and after fix. Use hypothesis to generate metric names from non-disk set and threshold values
  - **Property test 2 - Default fallback preservation**: For disk alarms where resource has NO path-specific tags (no `Threshold_Disk_*` keys), sync should use default threshold (80) and produce same result before and after fix
  - **Property test 3 - No disk alarms triggers recreate**: When `_find_alarms_for_resource` returns alarm names that don't contain `disk_used_percent`, the disk alarm branch should set `needs_recreate = True`
  - **Setup**: Mock `_get_cw_client()`, `_find_alarms_for_resource`, `_get_alarm_defs`, `create_alarms_for_resource` as needed
  - Verify tests PASS on UNFIXED code (confirms baseline behavior to preserve)
  - **EXPECTED OUTCOME**: Tests PASS (these test non-buggy code paths that should remain unchanged)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 3. Fix for disk threshold sync path-specific tag lookup

  - [x] 3.1 Implement the fix in `sync_alarms_for_resource`
    - In `common/alarm_manager.py`, in the `sync_alarms_for_resource` function's disk alarm sync block (dynamic_dimensions branch)
    - For each alarm from `describe_alarms` response, extract `path` from `alarm["Dimensions"]` where `Name == "path"`, default to `"/"`
    - Convert path to tag suffix using `disk_path_to_tag_suffix(path)` (already available via import from `common.tag_resolver`)
    - Change `get_threshold(resource_tags, "Disk")` to `get_threshold(resource_tags, f"Disk_{suffix}")`
    - Ensure `disk_path_to_tag_suffix` is imported if not already
    - _Bug_Condition: isBugCondition(input) where sync calls get_threshold with "Disk" instead of "Disk_{suffix}" for path-specific disk alarms_
    - _Expected_Behavior: For each disk alarm, extract path from Dimensions → convert to suffix → call get_threshold(tags, "Disk_{suffix}") for path-specific threshold lookup_
    - _Preservation: Non-disk metric sync, default fallback when no path-specific tags, no-disk-alarm recreate trigger, create_alarms_for_resource unchanged_
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4_

  - [x] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - 디스크 알람 경로별 임계치 조회
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior: sync should use `get_threshold(tags, "Disk_{suffix}")` for path-specific thresholds
    - Run `pytest tests/test_pbt_disk_threshold_fault.py -v`
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed - path-specific thresholds are now correctly looked up)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - 비디스크 메트릭 및 기본값 폴백 동작 유지
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run `pytest tests/test_pbt_disk_threshold_preservation.py -v`
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions in non-disk metrics, default fallback, and recreate trigger)
    - Confirm all tests still pass after fix (no regressions)

- [x] 4. Checkpoint - Ensure all tests pass
  - Run `pytest tests/test_pbt_disk_threshold_fault.py tests/test_pbt_disk_threshold_preservation.py -v`
  - Ensure all property-based tests pass
  - Ensure no regressions in existing tests: `pytest tests/ -v`
  - Ask the user if questions arise
