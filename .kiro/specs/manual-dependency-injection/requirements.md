# Requirements Document

## Introduction

AWS Monitoring Engine의 core 모듈에 수동 DI(Dependency Injection) 패턴을 도입한다. 함수 시그니처에 keyword-only 파라미터(`*, cw=None`)를 추가하고, `None`이면 기존 `lru_cache` 싱글턴을 사용하여 하위 호환성을 유지한다. Phase 1은 단일 계정 환경에서 `alarm_manager`, `alarm_search`, `alarm_builder`, `alarm_sync`, `dimension_builder` 모듈과 `_clients.py` 팩토리 준비만 포함한다.

## Glossary

- **Monitoring_Engine**: AWS 리소스의 CloudWatch 알람을 자동 생성/삭제/동기화하는 시스템
- **Facade**: `alarm_manager.py`의 public API 함수 (`create_alarms_for_resource`, `delete_alarms_for_resource`, `sync_alarms_for_resource`)
- **DI_Parameter**: 함수 시그니처에서 `*` 뒤에 위치하는 keyword-only 파라미터 (예: `*, cw=None`)
- **Singleton_Client**: `functools.lru_cache` 기반으로 캐시된 boto3 CloudWatch 클라이언트
- **Client_Factory**: `_clients.py`의 `create_clients_for_account` 함수로, STS AssumeRole을 통해 대상 계정의 boto3 클라이언트 세트를 생성하는 팩토리
- **Caller**: Facade 함수 또는 내부 함수를 호출하는 코드 (Lambda Handler, 테스트 코드 등)

## Requirements

### Requirement 1: Facade DI 파라미터 추가

**User Story:** As a developer, I want the Facade functions to accept an optional `cw` parameter, so that I can inject a CloudWatch client for testing or multi-account scenarios.

#### Acceptance Criteria

1. WHEN a Caller invokes `create_alarms_for_resource` without `cw` argument, THE Facade SHALL use the Singleton_Client from `_clients._get_cw_client()`
2. WHEN a Caller invokes `create_alarms_for_resource` with `cw=<client>`, THE Facade SHALL use the provided client for all internal CloudWatch API calls
3. WHEN a Caller invokes `delete_alarms_for_resource` without `cw` argument, THE Facade SHALL use the Singleton_Client from `_clients._get_cw_client()`
4. WHEN a Caller invokes `delete_alarms_for_resource` with `cw=<client>`, THE Facade SHALL use the provided client for all internal CloudWatch API calls
5. WHEN a Caller invokes `sync_alarms_for_resource` without `cw` argument, THE Facade SHALL use the Singleton_Client from `_clients._get_cw_client()`
6. WHEN a Caller invokes `sync_alarms_for_resource` with `cw=<client>`, THE Facade SHALL use the provided client for all internal CloudWatch API calls
7. THE Facade SHALL declare `cw` as a keyword-only parameter with default value `None` using the `*, cw=None` syntax

### Requirement 2: alarm_search DI 파라미터 추가

**User Story:** As a developer, I want alarm_search functions to accept an optional `cw` parameter, so that the injected client propagates through the search/delete chain.

#### Acceptance Criteria

1. WHEN `_find_alarms_for_resource` is called without `cw`, THE alarm_search module SHALL use the Singleton_Client
2. WHEN `_find_alarms_for_resource` is called with `cw=<client>`, THE alarm_search module SHALL use the provided client for `describe_alarms` pagination
3. WHEN `_delete_all_alarms_for_resource` is called with `cw=<client>`, THE alarm_search module SHALL pass the same client to `_find_alarms_for_resource` and use the same client for `delete_alarms` calls
4. WHEN `_describe_alarms_batch` is called with `cw=<client>`, THE alarm_search module SHALL use the provided client for `describe_alarms` calls
5. THE alarm_search module SHALL declare `cw` as a keyword-only parameter with default value `None` on `_find_alarms_for_resource`, `_delete_all_alarms_for_resource`, and `_describe_alarms_batch`

### Requirement 3: alarm_builder DI 파라미터 추가

**User Story:** As a developer, I want `_create_single_alarm` and `_recreate_alarm_by_name` to accept an optional `cw` parameter, so that the injected client reaches functions that currently call `_clients._get_cw_client()` directly.

#### Acceptance Criteria

1. WHEN `_create_single_alarm` is called without `cw`, THE alarm_builder module SHALL use the Singleton_Client
2. WHEN `_create_single_alarm` is called with `cw=<client>`, THE alarm_builder module SHALL use the provided client for `put_metric_alarm` calls
3. WHEN `_recreate_alarm_by_name` is called without `cw`, THE alarm_builder module SHALL use the Singleton_Client
4. WHEN `_recreate_alarm_by_name` is called with `cw=<client>`, THE alarm_builder module SHALL use the provided client for `describe_alarms`, `delete_alarms`, and `put_metric_alarm` calls
5. THE alarm_builder module SHALL declare `cw` as a keyword-only parameter with default value `None` on `_create_single_alarm` and `_recreate_alarm_by_name`

### Requirement 4: alarm_sync DI 파라미터 추가

**User Story:** As a developer, I want alarm_sync functions to accept an optional `cw` parameter, so that the sync chain uses the injected client consistently.

#### Acceptance Criteria

1. WHEN `_sync_off_hardcoded` is called with `cw=<client>`, THE alarm_sync module SHALL use the provided client for `delete_alarms` calls
2. WHEN `_sync_dynamic_alarms` is called with `cw=<client>`, THE alarm_sync module SHALL pass the same client to `_create_dynamic_alarm` and `_delete_alarm_names`
3. WHEN `_apply_sync_changes` is called with `cw=<client>`, THE alarm_sync module SHALL pass the same client to `create_alarms_for_resource`, `_recreate_alarm_by_name`, and `_create_single_alarm`
4. WHEN any alarm_sync function is called without `cw`, THE alarm_sync module SHALL use the Singleton_Client
5. THE alarm_sync module SHALL declare `cw` as a keyword-only parameter with default value `None` on `_sync_off_hardcoded`, `_sync_dynamic_alarms`, and `_apply_sync_changes`

### Requirement 5: dimension_builder DI 파라미터 추가

**User Story:** As a developer, I want dimension_builder functions to accept an optional `cw` parameter, so that `list_metrics` API calls use the injected client.

#### Acceptance Criteria

1. WHEN `_resolve_metric_dimensions` is called with `cw=<client>`, THE dimension_builder module SHALL use the provided client for `list_metrics` calls
2. WHEN `_get_disk_dimensions` is called with `cw=<client>`, THE dimension_builder module SHALL use the provided client for `list_metrics` calls
3. WHEN either function is called without `cw`, THE dimension_builder module SHALL use the Singleton_Client
4. THE dimension_builder module SHALL declare `cw` as a keyword-only parameter with default value `None` on `_resolve_metric_dimensions` and `_get_disk_dimensions`

### Requirement 6: Client Factory 준비

**User Story:** As a developer, I want a `create_clients_for_account` factory function in `_clients.py`, so that the multi-account infrastructure is ready for Phase 3.

#### Acceptance Criteria

1. THE Client_Factory SHALL accept `role_arn` (str) and optional `session_name` (str, default "MonitoringEngine") as parameters
2. THE Client_Factory SHALL return a dictionary with keys `"cw"`, `"ec2"`, `"rds"`, `"elbv2"` mapping to boto3 client objects
3. THE Client_Factory SHALL use STS `AssumeRole` to obtain temporary credentials for the target account
4. IF the STS `AssumeRole` call fails, THEN THE Client_Factory SHALL propagate the `ClientError` to the Caller

### Requirement 7: 하위 호환성 보장

**User Story:** As a developer, I want all existing tests to pass without modification after DI parameters are added, so that the refactoring introduces no regressions.

#### Acceptance Criteria

1. THE Monitoring_Engine SHALL produce identical results when Facade functions are called without `cw` argument compared to the pre-DI behavior
2. THE Monitoring_Engine SHALL produce identical results when Facade functions are called with `cw=None` compared to calling without `cw` argument
3. WHEN existing test code calls any modified function without the new DI_Parameter, THE Monitoring_Engine SHALL execute without errors
4. THE Monitoring_Engine SHALL pass all 607 existing tests after DI parameter additions

### Requirement 8: 클라이언트 전파 일관성

**User Story:** As a developer, I want the injected client to propagate through the entire call chain, so that no internal function falls back to the singleton when a client is explicitly provided.

#### Acceptance Criteria

1. WHEN a Caller provides `cw=<client>` to a Facade function, THE Monitoring_Engine SHALL pass the same client object to every internal function in the call chain that performs CloudWatch API calls
2. WHEN a Caller provides `cw=<client>` to a Facade function, THE Monitoring_Engine SHALL not invoke `_clients._get_cw_client()` during that call
