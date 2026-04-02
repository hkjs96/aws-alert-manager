# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Direction-Threshold 공백 및 TagName: 접두사 누락
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Scope the property to concrete failing cases for reproducibility
  - Test file: `tests/test_pbt_alarm_naming_format_fault.py`
  - Use `hypothesis` with strategies for resource_type (from `EC2, RDS, ALB, NLB, TG, AuroraRDS, DocDB, ElastiCache, NAT`), resource_id, resource_name, metric (from `_METRIC_DISPLAY` keys), and threshold (positive floats)
  - Property: for all valid inputs, `_pretty_alarm_name()` output must contain `{direction} {threshold}` (with space between direction and threshold) AND suffix must match `(TagName: {short_id})`
  - Verify `_create_dynamic_alarm()` also produces suffix `(TagName: {short_id})` and `{direction} {threshold}` with space
  - Verify `_find_alarms_for_resource()` suffix set contains `(TagName: {short_id})` pattern
  - Verify `_NEW_FORMAT_RE` regex extracts pure resource_id from `(TagName: {resource_id})` suffix
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists)
  - Document counterexamples found (e.g., `_pretty_alarm_name("EC2", "i-abc", "srv", "CPU", 80.0)` produces `>=80%` without space and `(i-abc)` without TagName: prefix)
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - 255자 Truncate, Short_ID, 레거시 검색, AlarmDescription 보존
  - **IMPORTANT**: Follow observation-first methodology
  - Test file: `tests/test_pbt_alarm_naming_format_preservation.py`
  - Observe on UNFIXED code:
    - `_pretty_alarm_name()` with long labels (>200 chars) → output ≤ 255 chars, label truncated first, display_metric preserved
    - `_pretty_alarm_name("ALB", alb_arn, ...)` → suffix uses Short_ID `{name}/{hash}` (not full ARN)
    - `_classify_alarm("[EC2] srv CPUUtilization >=80% (i-abc)")` → extracts resource_type="EC2" correctly
    - `_build_alarm_description(...)` → resource_id field contains full ARN/ID unchanged
  - Write property-based tests:
    - **Truncate preservation**: for all inputs, `len(_pretty_alarm_name(...)) <= 255` and truncate order is label → display_metric
    - **Short_ID preservation**: for all ALB/NLB/TG ARN inputs, suffix contains `{name}/{hash}` (Short_ID extraction unchanged)
    - **Legacy search preservation**: `_find_alarms_for_resource()` legacy prefix search (`resource_id` prefix) still works
    - **resource_type parsing preservation**: `_classify_alarm()` extracts `[EC2]`, `[RDS]` etc. correctly from new format names
    - **AlarmDescription preservation**: `_build_alarm_description()` stores full ARN/ID in resource_id field
  - Verify tests PASS on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Implement alarm naming format fix

  - [x] 3.1 Fix `_pretty_alarm_name()` in `common/alarm_naming.py`
    - Change `threshold_part`: `f" {direction}{thr_str}{unit} "` → `f" {direction} {thr_str}{unit} "` (add space after direction)
    - Change `suffix`: `f"({short_id})"` → `f"(TagName: {short_id})"`
    - _Bug_Condition: isBugCondition(create) where threshold_part has no space between direction and threshold, and suffix has no TagName: prefix_
    - _Expected_Behavior: alarmName contains `{direction} {threshold}` (with space) AND suffix matches `(TagName: {short_id})`_
    - _Preservation: 255-char truncate logic (label → display_metric order), Short_ID extraction unchanged_
    - _Requirements: 2.1, 2.2, 3.1, 3.2_

  - [x] 3.2 Fix `_create_dynamic_alarm()` in `common/alarm_builder.py`
    - Change `threshold_part`: `f" {direction}{thr_str} "` → `f" {direction} {thr_str} "` (add space after direction)
    - Change `suffix`: `f"({short_id})"` → `f"(TagName: {short_id})"`
    - Update all truncation branches that build `name` to use the new suffix format
    - _Bug_Condition: isBugCondition(create) where dynamic alarm threshold_part has no space and suffix has no TagName: prefix_
    - _Expected_Behavior: dynamic alarm name contains `{direction} {threshold}` (with space) AND suffix matches `(TagName: {short_id})`_
    - _Preservation: 255-char truncate logic preserved for dynamic alarms_
    - _Requirements: 2.3, 3.1_

  - [x] 3.3 Fix `_find_alarms_for_resource()` in `common/alarm_search.py`
    - Change suffix matching: `f"({short_id})"` → `f"(TagName: {short_id})"`
    - Change legacy Full_ARN compat: `f"({resource_id})"` → `f"(TagName: {resource_id})"`
    - _Bug_Condition: isBugCondition(search) where suffixPattern is `({short_id})` missing TagName: prefix_
    - _Expected_Behavior: suffix matching uses `(TagName: {short_id})` to find new format alarms_
    - _Preservation: Legacy prefix-based search (`resource_id` prefix) continues to work_
    - _Requirements: 2.4, 3.3_

  - [x] 3.4 Fix `_classify_alarm()` / `_NEW_FORMAT_RE` in `daily_monitor/lambda_handler.py`
    - Change regex: `r"^\[(\w+)\]\s.*\((.+)\)$"` → `r"^\[(\w+)\]\s.*\(TagName:\s(.+)\)$"`
    - This matches `(TagName: {resource_id})` and captures only the pure resource_id
    - _Bug_Condition: isBugCondition(parse) where regex captures `TagName: {resource_id}` instead of `{resource_id}`_
    - _Expected_Behavior: regex extracts pure resource_id from `(TagName: {resource_id})` suffix_
    - _Preservation: resource_type extraction (`[EC2]`, `[RDS]` etc.) unchanged_
    - _Requirements: 2.5, 3.4_

  - [x] 3.5 Update `.kiro/steering/alarm-rules.md` format guide
    - Update format: `{direction}{threshold}{unit}` → `{direction} {threshold}{unit}`
    - Update format: `({resource_id})` → `(TagName: {resource_id})`
    - _Requirements: 2.1, 2.2_

  - [x] 3.6 Update existing tests in `tests/test_alarm_manager.py`
    - Update all alarm name format assertions to expect `{direction} {threshold}` (with space) instead of `{direction}{threshold}`
    - Update all suffix assertions to expect `(TagName: {short_id})` instead of `({short_id})`
    - Affected tests: `test_pretty_alarm_name_ec2_cpu`, `test_pretty_alarm_name_no_name_tag`, `test_pretty_alarm_name_disk_root`, `test_pretty_alarm_name_disk_data`, `test_pretty_alarm_name_rds_free_memory`, `test_pretty_alarm_name_rds_connections`, `test_pretty_alarm_name_float_threshold`, `test_pretty_alarm_name_short_inputs_unchanged`, and all ALB/NLB/TG suffix tests
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.7 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Direction-Threshold 공백 및 TagName: 접두사
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run `tests/test_pbt_alarm_naming_format_fault.py`
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 3.8 Verify preservation tests still pass
    - **Property 2: Preservation** - 255자 Truncate, Short_ID, 레거시 검색, AlarmDescription 보존
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run `tests/test_pbt_alarm_naming_format_preservation.py`
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all preservation tests still pass after fix (no regressions)

- [x] 4. Checkpoint - Ensure all tests pass
  - Run full test suite: `pytest tests/ -x -q`
  - Ensure all tests pass, ask the user if questions arise
