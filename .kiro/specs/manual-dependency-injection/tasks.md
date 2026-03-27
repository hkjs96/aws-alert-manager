# Implementation Plan: Manual Dependency Injection (Phase 1)

## Overview

바닥부터(의존성 없는 모듈 먼저) 순서로 `*, cw=None` keyword-only 파라미터를 추가한다. 각 단계마다 기존 테스트가 깨지지 않는지 확인하며 점진적으로 진행한다. Phase 1은 단일 계정 환경에서의 DI 인프라 준비만 포함한다.

## Tasks

- [ ] 1. `_clients.py`에 `create_clients_for_account` 팩토리 추가
  - [ ] 1.1 `create_clients_for_account(role_arn, session_name)` 함수 구현
    - STS `AssumeRole`로 임시 자격증명 획득
    - `{"cw", "ec2", "rds", "elbv2"}` 키를 가진 dict 반환
    - `ClientError`는 호출자에게 전파
    - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - [ ]* 1.2 `create_clients_for_account` 단위 테스트 작성
    - moto `@mock_aws`로 STS AssumeRole 모킹
    - 반환 dict 키 검증 (`cw`, `ec2`, `rds`, `elbv2`)
    - 잘못된 role_arn 시 ClientError 전파 검증
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [ ] 2. Checkpoint — 기존 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. `alarm_search.py` 함수에 `*, cw=None` 추가
  - [ ] 3.1 `_find_alarms_for_resource`, `_delete_all_alarms_for_resource`, `_describe_alarms_batch`에 `*, cw=None` 추가
    - 함수 본문 첫 줄에서 `cw = cw or _clients._get_cw_client()` resolve
    - `_delete_all_alarms_for_resource`는 내부 `_find_alarms_for_resource` 호출 시 `cw=cw` 전달
    - 기존 `_delete_alarm_names(cw, ...)` 호출에도 resolve된 cw 전달
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - [ ]* 3.2 alarm_search DI 단위 테스트 작성
    - `cw=None` 호출 시 싱글턴 폴백 검증
    - `cw=mock_cw` 호출 시 주입된 클라이언트 사용 검증
    - `_delete_all_alarms_for_resource(cw=mock)` → `_find_alarms_for_resource`에 동일 mock 전파 검증
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [ ] 4. Checkpoint — 기존 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. `dimension_builder.py` 함수에 `*, cw=None` 추가
  - [ ] 5.1 `_resolve_metric_dimensions`, `_get_disk_dimensions`에 `*, cw=None` 추가
    - 함수 본문 첫 줄에서 `cw = cw or _clients._get_cw_client()` resolve
    - 기존 `cw = _clients._get_cw_client()` 라인을 resolve 패턴으로 교체
    - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - [ ]* 5.2 dimension_builder DI 단위 테스트 작성
    - `_resolve_metric_dimensions(cw=mock)` 시 mock의 `list_metrics` 호출 검증
    - `_get_disk_dimensions(cw=mock)` 시 mock의 `list_metrics` 호출 검증
    - `cw=None` 시 싱글턴 폴백 검증
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [ ] 6. Checkpoint — 기존 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. `alarm_builder.py`의 `_create_single_alarm`, `_recreate_alarm_by_name`에 `*, cw=None` 추가
  - [ ] 7.1 `_create_single_alarm`에 `*, cw=None` 추가
    - 함수 본문 첫 줄에서 `cw = cw or _clients._get_cw_client()` resolve
    - 기존 `cw = _clients._get_cw_client()` 라인을 resolve 패턴으로 교체
    - _Requirements: 3.1, 3.2, 3.5_
  - [ ] 7.2 `_recreate_alarm_by_name`에 `*, cw=None` 추가
    - 함수 본문 첫 줄에서 `cw = cw or _clients._get_cw_client()` resolve
    - 기존 `cw = _clients._get_cw_client()` 라인을 resolve 패턴으로 교체
    - 내부 `describe_alarms`, `delete_alarms`, `put_metric_alarm` 모두 resolve된 cw 사용
    - _Requirements: 3.3, 3.4, 3.5_
  - [ ]* 7.3 alarm_builder DI 단위 테스트 작성
    - `_create_single_alarm(cw=mock)` 시 mock의 `put_metric_alarm` 호출 검증
    - `_recreate_alarm_by_name(cw=mock)` 시 mock의 `describe_alarms`, `delete_alarms`, `put_metric_alarm` 호출 검증
    - `cw=None` 시 싱글턴 폴백 검증
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 8. Checkpoint — 기존 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. `alarm_sync.py` 함수에 `*, cw=None` 추가
  - [ ] 9.1 `_sync_off_hardcoded`, `_sync_dynamic_alarms`, `_apply_sync_changes`에 `*, cw=None` 추가
    - `_sync_off_hardcoded`: `cw = cw or _clients._get_cw_client()` resolve, 내부 `delete_alarms` 호출에 사용
    - `_sync_dynamic_alarms`: `cw = cw or _clients._get_cw_client()` resolve, `_create_dynamic_alarm`, `_delete_alarm_names` 호출에 전달
    - `_apply_sync_changes`: `cw = cw or _clients._get_cw_client()` resolve, `create_alarms_for_resource(cw=cw)`, `_recreate_alarm_by_name(cw=cw)`, `_create_single_alarm(cw=cw)` 호출에 전달
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
  - [ ]* 9.2 alarm_sync DI 단위 테스트 작성
    - `_sync_off_hardcoded(cw=mock)` 시 mock의 `delete_alarms` 호출 검증
    - `_apply_sync_changes(cw=mock)` 시 하위 함수에 cw 전파 검증
    - `cw=None` 시 싱글턴 폴백 검증
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [ ] 10. Checkpoint — 기존 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. `alarm_manager.py` Facade 3개 함수에 `*, cw=None` 추가 + 내부 전달
  - [ ] 11.1 `create_alarms_for_resource`에 `*, cw=None` 추가
    - `cw = cw or _clients._get_cw_client()` resolve
    - `_delete_all_alarms_for_resource(cw=cw)` 전달
    - `_create_disk_alarms(..., cw, ...)`, `_create_standard_alarm(..., cw)` 기존 positional 전달 유지
    - `_create_dynamic_alarm(..., cw, ...)` 기존 positional 전달 유지
    - _Requirements: 1.1, 1.2, 1.7, 8.1, 8.2_
  - [ ] 11.2 `delete_alarms_for_resource`에 `*, cw=None` 추가
    - `_delete_all_alarms_for_resource(resource_id, resource_type, cw=cw)` 전달
    - _Requirements: 1.3, 1.4, 1.7_
  - [ ] 11.3 `sync_alarms_for_resource`에 `*, cw=None` 추가
    - `cw = cw or _clients._get_cw_client()` resolve
    - `_find_alarms_for_resource(cw=cw)`, `create_alarms_for_resource(cw=cw)` 전달
    - `_describe_alarms_batch(cw=cw)` 전달
    - `_sync_off_hardcoded(cw=cw)`, `_sync_dynamic_alarms(cw=cw)`, `_apply_sync_changes(cw=cw)` 전달
    - _Requirements: 1.5, 1.6, 1.7, 8.1, 8.2_
  - [ ]* 11.4 Facade DI 단위 테스트 작성
    - `create_alarms_for_resource(cw=mock)` 시 `_clients._get_cw_client()` 미호출 검증
    - `delete_alarms_for_resource(cw=mock)` 시 mock 전파 검증
    - `sync_alarms_for_resource(cw=mock)` 시 전체 체인에 mock 전파 검증
    - `cw=None` 호출 시 기존 동작과 동일 검증
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 7.1, 7.2, 7.3, 8.1, 8.2_

- [ ] 12. Checkpoint — 기존 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. Property-Based Tests
  - [ ]* 13.1 Property 4: keyword-only 파라미터 선언 검증
    - **Property 4: Keyword-only parameter declaration**
    - `inspect.signature`로 Phase 1 대상 함수들의 `cw` 파라미터가 keyword-only이고 default=None인지 검증
    - 대상: `create_alarms_for_resource`, `delete_alarms_for_resource`, `sync_alarms_for_resource`, `_find_alarms_for_resource`, `_delete_all_alarms_for_resource`, `_describe_alarms_batch`, `_create_single_alarm`, `_recreate_alarm_by_name`, `_sync_off_hardcoded`, `_sync_dynamic_alarms`, `_apply_sync_changes`, `_resolve_metric_dimensions`, `_get_disk_dimensions`
    - **Validates: Requirements 1.7, 2.5, 3.5, 4.5, 5.4**
  - [ ]* 13.2 Property 5: Factory 반환 구조 검증
    - **Property 5: Factory return structure**
    - `create_clients_for_account`가 `{"cw", "ec2", "rds", "elbv2"}` 키를 가진 dict를 반환하는지 검증
    - **Validates: Requirements 6.1, 6.2, 6.3**

- [ ] 14. Final Checkpoint — 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- 바닥부터 순서: `_clients` → `alarm_search` → `dimension_builder` → `alarm_builder` → `alarm_sync` → `alarm_manager`
- 이미 DI가 적용된 함수(`_create_standard_alarm`, `_create_disk_alarms`, `_create_dynamic_alarm`, `_delete_alarm_names`)는 변경 불필요
- 각 모듈 변경 후 체크포인트에서 기존 607개 테스트 통과를 확인
- Property tests validate universal correctness properties from the design document
