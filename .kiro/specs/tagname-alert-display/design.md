# TagName Alert Display Bugfix Design

## Overview

SNS 알림 메시지에서 리소스의 Name 태그 값이 `(TagName: <Name 태그 값>)` 형식으로 표시되어야 하지만, 현재 `sns_notifier.py`의 알림 함수들(`send_alert`, `send_remediation_alert`, `send_lifecycle_alert`)이 `resource_id`만 받고 Name 태그 정보를 전달받지 않아 메시지에 TagName이 누락되고 있다.

수정 전략: 각 알림 함수에 `tag_name: str = ""` 파라미터를 추가하고, 메시지 포맷에 `(TagName: <값>)` 을 삽입한다. 호출자(`daily_monitor`, `remediation_handler`)에서 이미 보유하거나 조회 가능한 Name 태그를 전달하도록 수정한다. Name 태그가 없으면 `N/A`로 폴백한다.

## Glossary

- **Bug_Condition (C)**: 알림 함수가 호출될 때 메시지에 Name 태그 값이 포함되지 않는 조건
- **Property (P)**: 알림 메시지에 `(TagName: <Name 태그 값>)` 형식이 포함되는 것
- **Preservation**: 기존 JSON 구조, SNS 실패 처리, 토픽 라우팅, 수집기 로직, `send_error_alert` 형식이 변경 없이 유지되는 것
- **`send_alert`**: `common/sns_notifier.py`의 임계치 초과 알림 발송 함수
- **`send_remediation_alert`**: `common/sns_notifier.py`의 자동 복구 알림 발송 함수
- **`send_lifecycle_alert`**: `common/sns_notifier.py`의 생명주기 알림 발송 함수
- **`get_resource_tags`**: `common/tag_resolver.py`의 AWS API 태그 조회 함수
- **`resource_tags`**: 리소스에 부착된 태그 딕셔너리 (수집기가 반환하는 `ResourceInfo`에 포함)

## Bug Details

### Fault Condition

알림 함수(`send_alert`, `send_remediation_alert`, `send_lifecycle_alert`)가 호출될 때, 함수 시그니처에 `tag_name` 파라미터가 없어 메시지 본문에 Name 태그 값을 포함할 수 없다. 호출자도 Name 태그를 전달하지 않는다.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type AlertFunctionCall (send_alert | send_remediation_alert | send_lifecycle_alert 호출)
  OUTPUT: boolean

  RETURN input.function IN ['send_alert', 'send_remediation_alert', 'send_lifecycle_alert']
         AND input.has_associated_resource = true
         AND NOT input.message CONTAINS '(TagName:'
END FUNCTION
```

### Examples

- `send_alert("i-abc123", "EC2", "CPU", 95.0, 80.0)` → 현재: `[EC2] i-abc123 - CPU exceeded threshold: 95.0 > 80.0` / 기대: `[EC2] i-abc123 (TagName: my-web-server) - CPU exceeded threshold: 95.0 > 80.0`
- `send_remediation_alert("i-abc123", "EC2", "instance type changed", "STOPPED")` → 현재: `[EC2] i-abc123 - unauthorized change detected...` / 기대: `[EC2] i-abc123 (TagName: my-web-server) - unauthorized change detected...`
- `send_lifecycle_alert("i-abc123", "EC2", "RESOURCE_DELETED", "...")` → 현재: 메시지에 TagName 없음 / 기대: 메시지에 `(TagName: my-web-server)` 포함
- Name 태그 없는 리소스: `send_alert("i-xyz789", "EC2", "CPU", 95.0, 80.0)` → 기대: `[EC2] i-xyz789 (TagName: N/A) - CPU exceeded threshold: 95.0 > 80.0`

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- SNS 메시지의 JSON 구조(`alert_type`, `resource_id`, `resource_type`, `timestamp` 등 기존 필드)는 변경 없이 유지
- SNS 발송 실패 시 CloudWatch Logs에 오류 기록 후 예외 삼킴 동작 유지
- 리소스 수집기(EC2, RDS, ELB collector)의 수집 로직과 반환 데이터 변경 없음
- `send_error_alert` 메시지 형식 변경 없음 (운영 컨텍스트 기반이므로 TagName 불필요)
- `_get_topic_arn` 알림 유형별 토픽 라우팅 로직 변경 없음

**Scope:**
`send_error_alert` 및 SNS 발송 인프라(`_publish`, `_get_topic_arn`)는 이번 수정 대상이 아니다. 알림 함수의 `tag_name` 파라미터는 기본값 `""`을 가지므로, 기존 호출 코드가 `tag_name`을 전달하지 않아도 하위 호환성이 유지된다.

## Hypothesized Root Cause

이 버그는 설계 누락(missing feature)에 해당한다:

1. **알림 함수 시그니처 누락**: `send_alert`, `send_remediation_alert`, `send_lifecycle_alert` 함수가 `tag_name` 파라미터를 받지 않아 메시지에 포함할 수 없음
2. **메시지 포맷 누락**: 메시지 문자열 템플릿에 `(TagName: ...)` 부분이 없음
3. **호출자 전달 누락 (daily_monitor)**: `_process_resource`에서 `resource_tags`를 이미 보유하고 있지만 `send_alert` 호출 시 Name 태그를 추출하여 전달하지 않음
4. **호출자 전달 누락 (remediation_handler)**:
   - `perform_remediation`이 `tag_name`을 받지 않고, `_handle_modify`에서 이미 `get_resource_tags`로 조회한 태그를 전달하지 않음
   - `_handle_delete`에서 `send_lifecycle_alert` 호출 시 Name 태그를 메시지에 포함하지 않음
   - `_handle_tag_change`에서 `send_lifecycle_alert` 호출 시 Name 태그를 메시지에 포함하지 않음

## Correctness Properties

Property 1: Fault Condition - 알림 메시지에 TagName 포함

_For any_ 알림 함수 호출에서 `tag_name`이 비어있지 않은 문자열로 전달될 때, 발송되는 SNS 메시지의 `message` 필드에 `(TagName: <tag_name>)` 형식이 포함되어야 한다.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Fault Condition - Name 태그 없을 때 N/A 폴백

_For any_ 알림 함수 호출에서 `tag_name`이 빈 문자열이거나 None일 때, 발송되는 SNS 메시지의 `message` 필드에 `(TagName: N/A)` 형식이 포함되어야 한다.

**Validates: Requirements 2.4**

Property 3: Preservation - 기존 JSON 필드 유지

_For any_ 알림 함수 호출에서, 발송되는 SNS 메시지 dict에 기존 필드(`alert_type`, `resource_id`, `resource_type`, `timestamp` 등)가 모두 존재하고 값이 변경되지 않아야 한다.

**Validates: Requirements 3.1**

Property 4: Preservation - send_error_alert 형식 유지

_For any_ `send_error_alert` 호출에서, 메시지 형식이 기존과 동일하게 유지되어야 하며 `(TagName: ...)` 이 포함되지 않아야 한다.

**Validates: Requirements 3.4**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `common/sns_notifier.py`

**Functions**: `send_alert`, `send_remediation_alert`, `send_lifecycle_alert`

**Specific Changes**:

1. **헬퍼 함수 추가**: `_format_tag_name(tag_name)` 함수를 추가하여 `tag_name`이 비어있거나 None이면 `"N/A"`를, 아니면 원래 값을 반환
2. **`send_alert` 시그니처 변경**: `tag_name: str = ""` 파라미터 추가
3. **`send_alert` 메시지 포맷 변경**: `{resource_id}` 뒤에 `(TagName: {formatted_tag_name})` 삽입
4. **`send_remediation_alert` 시그니처 변경**: `tag_name: str = ""` 파라미터 추가
5. **`send_remediation_alert` 메시지 포맷 변경**: `{resource_id}` 뒤에 `(TagName: {formatted_tag_name})` 삽입
6. **`send_lifecycle_alert` 시그니처 변경**: `tag_name: str = ""` 파라미터 추가
7. **`send_lifecycle_alert` 메시지 포맷 변경**: `message_text`에 `(TagName: {formatted_tag_name})` 접두 또는 JSON `tag_name` 필드 추가

**File**: `daily_monitor/lambda_handler.py`

**Function**: `_process_resource`

**Specific Changes**:

8. **Name 태그 추출**: `resource_tags.get("Name", "")` 로 Name 태그 추출
9. **`send_alert` 호출 수정**: `tag_name=name_tag` 파라미터 추가

**File**: `remediation_handler/lambda_handler.py`

**Functions**: `_handle_modify`, `perform_remediation`, `_handle_delete`, `_handle_tag_change`

**Specific Changes**:

10. **`perform_remediation` 시그니처 변경**: `tag_name: str = ""` 파라미터 추가, `send_remediation_alert` 호출 시 전달
11. **`_handle_modify` 수정**: `get_resource_tags`로 조회한 태그에서 Name 추출 후 `perform_remediation`에 전달
12. **`_handle_delete` 수정**: 태그 조회 시 Name 태그 추출, `send_lifecycle_alert` 호출 시 `tag_name` 전달, `message_text`에 TagName 포함
13. **`_handle_tag_change` 수정**: `get_resource_tags` 호출 결과 또는 CloudTrail 이벤트 태그에서 Name 추출, `send_lifecycle_alert` 호출 시 `tag_name` 전달

## Testing Strategy

### Validation Approach

테스트 전략은 두 단계로 진행한다: 먼저 수정 전 코드에서 버그를 재현하는 반례를 확인하고, 수정 후 버그가 해결되었으며 기존 동작이 보존되는지 검증한다.

### Exploratory Fault Condition Checking

**Goal**: 수정 전 코드에서 알림 메시지에 TagName이 누락되는 것을 확인하여 근본 원인 분석을 검증한다.

**Test Plan**: 각 알림 함수를 호출하고 발송된 SNS 메시지의 `message` 필드에 `(TagName:` 문자열이 포함되지 않음을 확인한다. 수정 전 코드에서 실행하여 실패(TagName 미포함)를 관찰한다.

**Test Cases**:
1. **send_alert TagName 누락**: `send_alert("i-abc", "EC2", "CPU", 95.0, 80.0)` 호출 후 메시지에 `(TagName:` 미포함 확인 (수정 전 코드에서 실패)
2. **send_remediation_alert TagName 누락**: `send_remediation_alert("i-abc", "EC2", "changed", "STOPPED")` 호출 후 메시지에 `(TagName:` 미포함 확인 (수정 전 코드에서 실패)
3. **send_lifecycle_alert TagName 누락**: `send_lifecycle_alert("i-abc", "EC2", "RESOURCE_DELETED", "msg")` 호출 후 메시지에 `(TagName:` 미포함 확인 (수정 전 코드에서 실패)
4. **daily_monitor send_alert 호출 시 tag_name 미전달**: `_process_resource` 실행 후 `send_alert`에 `tag_name` 인자가 전달되지 않음 확인 (수정 전 코드에서 실패)

**Expected Counterexamples**:
- 모든 알림 메시지의 `message` 필드에 `(TagName:` 문자열이 존재하지 않음
- 원인: 함수 시그니처에 `tag_name` 파라미터 부재, 메시지 템플릿에 TagName 포맷 부재

### Fix Checking

**Goal**: 버그 조건이 성립하는 모든 입력에 대해 수정된 함수가 기대 동작을 생성하는지 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := alertFunction_fixed(input)
  IF input.tag_name is not empty THEN
    ASSERT result.message CONTAINS '(TagName: ' + input.tag_name + ')'
  ELSE
    ASSERT result.message CONTAINS '(TagName: N/A)'
  END IF
END FOR
```

### Preservation Checking

**Goal**: 버그 조건이 성립하지 않는 모든 입력에 대해 수정된 함수가 기존과 동일한 결과를 생성하는지 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT send_error_alert_original(input) = send_error_alert_fixed(input)
  ASSERT _get_topic_arn_original(input) = _get_topic_arn_fixed(input)
  ASSERT _publish_original(input) = _publish_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing을 활용하여 다양한 `tag_name` 값(빈 문자열, None, 특수문자 포함, 긴 문자열 등)에 대해 메시지 포맷이 올바른지 검증한다. 기존 JSON 필드 보존도 property test로 검증한다.

**Test Plan**: 수정 전 코드에서 `send_error_alert`, `_get_topic_arn` 등 변경하지 않는 함수의 동작을 관찰한 후, 수정 후에도 동일한 동작을 하는지 property-based test로 검증한다.

**Test Cases**:
1. **JSON 필드 보존**: 수정 후 `send_alert` 메시지에 `alert_type`, `resource_id`, `resource_type`, `timestamp` 등 기존 필드가 모두 존재하는지 검증
2. **send_error_alert 형식 보존**: 수정 후 `send_error_alert` 메시지 형식이 변경되지 않았는지 검증
3. **토픽 라우팅 보존**: 수정 후 `_get_topic_arn` 동작이 변경되지 않았는지 검증
4. **SNS 실패 처리 보존**: SNS 발송 실패 시 예외가 삼켜지는 동작이 유지되는지 검증

### Unit Tests

- `send_alert`에 `tag_name="my-server"` 전달 시 메시지에 `(TagName: my-server)` 포함 확인
- `send_alert`에 `tag_name=""` 전달 시 메시지에 `(TagName: N/A)` 포함 확인
- `send_remediation_alert`에 `tag_name` 전달 시 메시지 포맷 확인
- `send_lifecycle_alert`에 `tag_name` 전달 시 메시지 포맷 확인
- `_format_tag_name` 헬퍼 함수의 None, 빈 문자열, 정상 값 처리 확인
- `daily_monitor._process_resource`에서 `send_alert` 호출 시 `tag_name` 전달 확인
- `remediation_handler.perform_remediation`에서 `send_remediation_alert` 호출 시 `tag_name` 전달 확인

### Property-Based Tests

- 임의의 `tag_name` 문자열에 대해 `send_alert` 메시지가 항상 `(TagName: ...)` 패턴을 포함하는지 검증
- 임의의 `tag_name`(빈 문자열 포함)에 대해 빈 값이면 `N/A`, 아니면 원래 값이 표시되는지 검증
- 임의의 알림 함수 호출에 대해 기존 JSON 필드가 모두 보존되는지 검증

### Integration Tests

- `daily_monitor.lambda_handler` 전체 흐름에서 임계치 초과 시 발송되는 SNS 메시지에 TagName 포함 확인
- `remediation_handler.lambda_handler`에서 MODIFY 이벤트 처리 후 발송되는 SNS 메시지에 TagName 포함 확인
- `remediation_handler._handle_delete`에서 DELETE 이벤트 처리 후 발송되는 SNS 메시지에 TagName 포함 확인
