# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Fault Condition** - 알림 메시지에 TagName 누락 확인
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Scope the property to the three alert functions (`send_alert`, `send_remediation_alert`, `send_lifecycle_alert`) with any `tag_name` string
  - Create `tests/test_pbt_tagname_fault.py` using `hypothesis`
  - Mock `_get_sns_client` to capture published SNS messages
  - Property: For any `tag_name` (non-empty string), calling `send_alert(resource_id, resource_type, metric_name, value, threshold, tag_name=tag_name)` should produce a message containing `(TagName: <tag_name>)`
  - Property: For empty/None `tag_name`, message should contain `(TagName: N/A)`
  - Test all three functions: `send_alert`, `send_remediation_alert`, `send_lifecycle_alert`
  - isBugCondition: `input.function IN ['send_alert', 'send_remediation_alert', 'send_lifecycle_alert'] AND NOT input.message CONTAINS '(TagName:'`
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (functions don't accept `tag_name` parameter, confirming the bug exists)
  - Document counterexamples: current message format lacks `(TagName: ...)` pattern entirely
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - 기존 JSON 필드 및 send_error_alert 형식 유지
  - **IMPORTANT**: Follow observation-first methodology
  - Create `tests/test_pbt_tagname_preservation.py` using `hypothesis`
  - Mock `_get_sns_client` to capture published SNS messages
  - Observe on UNFIXED code:
    - `send_alert("i-abc", "EC2", "CPU", 95.0, 80.0)` produces dict with keys `alert_type`, `resource_id`, `resource_type`, `metric_name`, `current_value`, `threshold`, `timestamp`, `message`
    - `send_remediation_alert("i-abc", "EC2", "changed", "STOPPED")` produces dict with keys `alert_type`, `resource_id`, `resource_type`, `change_summary`, `action_taken`, `timestamp`, `message`
    - `send_lifecycle_alert("i-abc", "EC2", "RESOURCE_DELETED", "msg")` produces dict with keys `alert_type`, `resource_id`, `resource_type`, `message`, `timestamp`
    - `send_error_alert("ctx", Exception("err"))` produces dict with keys `alert_type`, `context`, `error`, `error_type`, `timestamp`, `message` and message format `Operational error in ctx: err` without `(TagName:` substring
  - Property test 1 (JSON 필드 보존): For any valid inputs to `send_alert`, `send_remediation_alert`, `send_lifecycle_alert`, the published message dict must contain all expected keys with correct values for `alert_type`, `resource_id`, `resource_type`
  - Property test 2 (send_error_alert 형식 보존): For any `context` string and `error`, `send_error_alert` message must match `Operational error in {context}: {error}` format and must NOT contain `(TagName:`
  - Property test 3 (SNS 실패 처리 보존): When SNS publish raises an exception, no exception propagates to caller (exception is swallowed and logged)
  - Verify all tests PASS on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.4, 3.5_

- [x] 3. Fix for TagName 알림 메시지 표시 누락

  - [x] 3.1 Implement the fix in `common/sns_notifier.py`
    - Add `_format_tag_name(tag_name: str | None) -> str` helper: returns `tag_name` if truthy, else `"N/A"`
    - Add `tag_name: str = ""` parameter to `send_alert` signature
    - Update `send_alert` message format: `[{resource_type}] {resource_id} (TagName: {formatted}) - {metric_name} exceeded threshold: {current_value} > {threshold}`
    - Add `tag_name: str = ""` parameter to `send_remediation_alert` signature
    - Update `send_remediation_alert` message format: `[{resource_type}] {resource_id} (TagName: {formatted}) - unauthorized change detected. Change: {change_summary}. Action: {action_taken}`
    - Add `tag_name: str = ""` parameter to `send_lifecycle_alert` signature
    - Update `send_lifecycle_alert`: include `(TagName: {formatted})` in `message_text` or message dict
    - Do NOT modify `send_error_alert`, `_publish`, or `_get_topic_arn`
    - _Bug_Condition: isBugCondition(input) where input.function IN ['send_alert', 'send_remediation_alert', 'send_lifecycle_alert'] AND NOT input.message CONTAINS '(TagName:'_
    - _Expected_Behavior: message CONTAINS '(TagName: <tag_name>)' when tag_name is non-empty, '(TagName: N/A)' when empty/None_
    - _Preservation: send_error_alert format unchanged, JSON structure fields preserved, _get_topic_arn routing unchanged, SNS failure handling unchanged_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4, 3.5_

  - [x] 3.2 Update callers to pass `tag_name`
    - In `daily_monitor/lambda_handler.py` `_process_resource`: extract `resource_tags.get("Name", "")` and pass as `tag_name` to `send_alert`
    - In `remediation_handler/lambda_handler.py` `_handle_modify`: extract Name tag from `get_resource_tags` result, pass to `perform_remediation`
    - In `remediation_handler/lambda_handler.py` `perform_remediation`: add `tag_name: str = ""` parameter, pass to `send_remediation_alert`
    - In `remediation_handler/lambda_handler.py` `_handle_delete`: extract Name tag, pass to `send_lifecycle_alert`
    - In `remediation_handler/lambda_handler.py` `_handle_tag_change`: extract Name tag, pass to `send_lifecycle_alert`
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.3 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - 알림 메시지에 TagName 포함 확인
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1 (`tests/test_pbt_tagname_fault.py`)
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.4 Verify preservation tests still pass
    - **Property 2: Preservation** - 기존 JSON 필드 및 send_error_alert 형식 유지
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2 (`tests/test_pbt_tagname_preservation.py`)
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)

- [x] 4. Checkpoint - Ensure all tests pass
  - Run full test suite: `pytest tests/test_pbt_tagname_fault.py tests/test_pbt_tagname_preservation.py -v`
  - Ensure all property-based tests pass
  - Ensure existing tests in `tests/test_sns_notifier.py` still pass
  - Ask the user if questions arise
