# Requirements Document

## Introduction

AWS 리소스(EC2, RDS, ALB, NLB, TG)가 새로 생성될 때 CloudTrail CREATE 이벤트를 감지하여 Remediation_Handler가 즉시 알람을 자동 생성하는 기능.

현재 시스템은 MODIFY/DELETE/TAG_CHANGE 이벤트만 감지하며, 리소스 생성 시점에는 Daily_Monitor가 다음 스케줄(매일 00:00 UTC)에 실행될 때까지 알람이 생성되지 않는다. 이 기능은 CREATE 이벤트를 추가하여 리소스 생성 직후 `Monitoring=on` 태그가 있으면 즉시 알람을 생성하고, 태그가 없으면 스킵한다. 태그가 나중에 추가되는 경우는 기존 TAG_CHANGE 로직이 처리한다.

## Glossary

- **Remediation_Handler**: CloudTrail 이벤트를 수신하여 실시간으로 알람 생성/삭제/동기화를 수행하는 Lambda 함수
- **Daily_Monitor**: 매일 00:00 UTC에 실행되어 전체 리소스를 스캔하고 알람을 동기화하는 Lambda 함수
- **MONITORED_API_EVENTS**: `common/__init__.py`에 정의된 CloudTrail 모니터링 대상 API 이벤트 딕셔너리
- **EventBridge_Rule**: CloudTrail 이벤트를 필터링하여 Remediation_Handler를 트리거하는 EventBridge 규칙 (`CloudTrailModifyRule`)
- **Monitoring_Tag**: 리소스에 부착된 `Monitoring=on` 태그. 이 태그가 있는 리소스만 알람 자동 생성 대상
- **CREATE_Event**: 리소스 생성 시 CloudTrail에 기록되는 API 호출 이벤트 (RunInstances, CreateDBInstance, CreateLoadBalancer, CreateTargetGroup)
- **TAG_CHANGE_Event**: 리소스 태그 변경 시 CloudTrail에 기록되는 API 호출 이벤트 (CreateTags, AddTagsToResource, AddTags 등)
- **ParsedEvent**: Remediation_Handler 내부에서 CloudTrail 이벤트를 파싱한 데이터 클래스
- **_API_MAP**: 이벤트 이름 → (resource_type, id_extractor) 매핑 딕셔너리

## Requirements

### Requirement 1: MONITORED_API_EVENTS에 CREATE 카테고리 추가

**User Story:** As a 시스템 운영자, I want MONITORED_API_EVENTS에 CREATE 카테고리가 정의되어 있기를, so that Remediation_Handler가 리소스 생성 이벤트를 인식할 수 있다.

#### Acceptance Criteria

1. THE MONITORED_API_EVENTS SHALL contain a "CREATE" key with a list of API event names: `RunInstances`, `CreateDBInstance`, `CreateLoadBalancer`, `CreateTargetGroup`
2. WHEN _get_event_category 함수가 CREATE 카테고리의 이벤트 이름을 입력받으면, THE Remediation_Handler SHALL return "CREATE" as the event_category
3. THE MONITORED_API_EVENTS SHALL preserve existing MODIFY, DELETE, TAG_CHANGE categories without modification

### Requirement 2: EventBridge 규칙에 CREATE 이벤트 추가

**User Story:** As a 시스템 운영자, I want EventBridge 규칙이 CREATE 이벤트를 감지하기를, so that 리소스 생성 시 Remediation_Handler가 즉시 트리거된다.

#### Acceptance Criteria

1. THE EventBridge_Rule SHALL include `RunInstances`, `CreateDBInstance`, `CreateLoadBalancer`, `CreateTargetGroup` in the eventName filter list
2. THE EventBridge_Rule SHALL preserve all existing eventName filters (MODIFY, DELETE, TAG_CHANGE events) without modification
3. WHEN a CREATE event occurs, THE EventBridge_Rule SHALL route the event to the Remediation_Handler Lambda function

### Requirement 3: CREATE 이벤트 파싱

**User Story:** As a 시스템 운영자, I want Remediation_Handler가 CREATE 이벤트에서 리소스 ID와 타입을 정확히 추출하기를, so that 올바른 리소스에 대해 알람 생성을 시도할 수 있다.

#### Acceptance Criteria

1. WHEN a RunInstances event is received, THE Remediation_Handler SHALL extract the EC2 instance ID from `responseElements.instancesSet.items[0].instanceId`
2. WHEN a CreateDBInstance event is received, THE Remediation_Handler SHALL extract the RDS DB identifier from `requestParameters.dBInstanceIdentifier`
3. WHEN a CreateLoadBalancer event is received, THE Remediation_Handler SHALL extract the ELB ARN from `responseElements.loadBalancers[0].loadBalancerArn` and resolve the resource_type to ALB or NLB based on the ARN pattern
4. WHEN a CreateTargetGroup event is received, THE Remediation_Handler SHALL extract the TG ARN from `responseElements.targetGroups[0].targetGroupArn` and set resource_type to TG
5. IF a CREATE event lacks the required fields for resource ID extraction, THEN THE Remediation_Handler SHALL raise a ValueError with a descriptive message
6. THE _API_MAP SHALL include entries for all four CREATE events with appropriate resource_type and id_extractor functions

### Requirement 4: CREATE 이벤트 핸들링 — 태그 확인 및 알람 생성

**User Story:** As a 시스템 운영자, I want CREATE 이벤트 수신 시 Monitoring=on 태그가 있는 리소스에만 알람이 생성되기를, so that 모니터링 대상이 아닌 리소스에 불필요한 알람이 생성되지 않는다.

#### Acceptance Criteria

1. WHEN a CREATE event is received and the resource has `Monitoring=on` tag, THE Remediation_Handler SHALL call `create_alarms_for_resource` to create CloudWatch alarms for the resource
2. WHEN a CREATE event is received and the resource does not have `Monitoring=on` tag, THE Remediation_Handler SHALL skip alarm creation and log the skip reason at info level
3. WHEN a CREATE event is received, THE Remediation_Handler SHALL call `get_resource_tags` to retrieve the current tags of the newly created resource
4. IF `get_resource_tags` returns an empty dictionary for a CREATE event, THEN THE Remediation_Handler SHALL skip alarm creation and log a warning

### Requirement 5: CREATE 이벤트와 TAG_CHANGE 이벤트 간 중복 알람 방지

**User Story:** As a 시스템 운영자, I want CREATE 이벤트와 TAG_CHANGE 이벤트가 동시에 발생해도 알람이 중복 생성되지 않기를, so that 불필요한 알람 중복이 방지된다.

#### Acceptance Criteria

1. THE Remediation_Handler SHALL rely on `create_alarms_for_resource` which deletes existing alarms before creating new ones, ensuring idempotent alarm creation regardless of event ordering
2. WHEN both a CREATE event and a TAG_CHANGE event (Monitoring=on) are processed for the same resource, THE Remediation_Handler SHALL produce the same final alarm state as processing either event alone
3. THE Remediation_Handler SHALL use the same `create_alarms_for_resource` function for both CREATE and TAG_CHANGE alarm creation paths

### Requirement 6: CREATE 이벤트 파싱 — RunInstances 특수 처리

**User Story:** As a 시스템 운영자, I want RunInstances 이벤트에서 리소스 ID를 정확히 추출하기를, so that EC2 인스턴스 생성 시 올바른 인스턴스에 알람이 생성된다.

#### Acceptance Criteria

1. WHEN a RunInstances event is received, THE Remediation_Handler SHALL extract the instance ID from `responseElements` (not `requestParameters`), because the instance ID is assigned by AWS at creation time and only available in the response
2. IF the RunInstances responseElements contains multiple instances, THEN THE Remediation_Handler SHALL process only the first instance ID
3. IF the RunInstances responseElements is missing or empty, THEN THE Remediation_Handler SHALL raise a ValueError

### Requirement 7: lambda_handler에서 CREATE 카테고리 라우팅

**User Story:** As a 시스템 운영자, I want lambda_handler가 CREATE 카테고리 이벤트를 올바른 핸들러로 라우팅하기를, so that CREATE 이벤트가 정상적으로 처리된다.

#### Acceptance Criteria

1. WHEN lambda_handler receives an event with event_category "CREATE", THE Remediation_Handler SHALL route it to the `_handle_create` handler function
2. THE Remediation_Handler SHALL return `{"status": "ok"}` after successful CREATE event processing
3. IF an error occurs during CREATE event processing, THEN THE Remediation_Handler SHALL log the error and return `{"status": "error"}`
