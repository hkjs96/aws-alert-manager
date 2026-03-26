# Threshold Tag Sync Bugfix Design

## Overview

`remediation_handler/lambda_handler.py`의 `_handle_tag_change` 함수가 TAG_CHANGE 이벤트 수신 시
`"Monitoring"` 키가 변경 태그에 포함된 경우에만 처리를 진행하고, `Threshold_CPU`, `Threshold_Disk_data` 등
임계치 태그만 변경된 경우에는 즉시 `return`하여 알람이 재동기화되지 않는 버그를 수정한다.

수정 전략: `_handle_tag_change` 함수에서 `monitoring_involved` 분기 이후, `Threshold_*` 접두사를 가진
태그 키가 존재하는지 추가로 확인하는 분기를 삽입한다. 해당 분기에서 `get_resource_tags`로 현재 태그를
조회하고, `has_monitoring_tag`로 `Monitoring=on` 여부를 확인한 뒤 `sync_alarms_for_resource`를 호출한다.

## Glossary

- **Bug_Condition (C)**: `_handle_tag_change`가 `Threshold_*` 태그 변경을 처리하지 않고 즉시 `return`하는 조건
- **Property (P)**: `Threshold_*` 태그 변경 + `Monitoring=on` 리소스에 대해 `sync_alarms_for_resource`가 호출되는 것
- **Preservation**: `Monitoring` 태그 추가/제거/변경 처리, 일반 태그 무시 등 기존 TAG_CHANGE 처리 동작이 변경 없이 유지되는 것
- **`_handle_tag_change`**: `remediation_handler/lambda_handler.py`의 TAG_CHANGE 이벤트 처리 함수 (버그 위치)
- **`sync_alarms_for_resource`**: `common/alarm_manager.py`의 알람 동기화 함수 (임계치 변경 시 호출 대상)
- **`get_resource_tags`**: `common/tag_resolver.py`의 리소스 태그 조회 함수
- **`has_monitoring_tag`**: `common/tag_resolver.py`의 `Monitoring=on` 여부 확인 함수
- **`monitoring_involved`**: 변경된 태그 키 중 `"Monitoring"`이 포함되어 있는지 나타내는 불리언 변수
- **`tag_keys`**: `_extract_tags_from_params`가 반환하는 변경된 태그 키 집합

## Bug Details

### Fault Condition

`_handle_tag_change` 함수에서 `monitoring_involved = "Monitoring" in tag_keys`를 계산한 후,
`if not monitoring_involved: return`으로 즉시 종료한다. 이 조건은 `Threshold_*` 태그만 변경된 경우를
포함하여 `Monitoring` 키가 없는 모든 TAG_CHANGE 이벤트를 무시한다.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type ParsedEvent { event_category, request_params, resource_id, resource_type }
  OUTPUT: boolean

  tag_keys := extract_tag_keys(input.request_params, input.event_name)

  RETURN input.event_category == "TAG_CHANGE"
         AND "Monitoring" NOT IN tag_keys
         AND ANY key IN tag_keys STARTS_WITH "Threshold_"
END FUNCTION
```

### Examples

- `Threshold_CPU=90` 태그 추가 + `Monitoring=on` 리소스 → 현재: 무시, 기대: CPU 알람 임계치 90으로 재동기화
- `Threshold_Disk_data=20` 태그 추가 + `Monitoring=on` EC2 → 현재: 무시, 기대: `/data` 디스크 알람 임계치 20으로 재동기화
- `Threshold_Memory=75` 태그 수정 + `Monitoring=on` 리소스 → 현재: 무시, 기대: Memory 알람 임계치 75로 재동기화
- `Threshold_CPU=90` 태그 추가 + `Monitoring=on` 없는 리소스 → 현재: 무시, 기대: 조용히 종료 (정상)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- `Monitoring=on` 태그가 추가될 때 `create_alarms_for_resource`를 호출하여 알람을 생성하는 동작
- `Monitoring` 태그가 `on`이 아닌 값으로 변경되거나 삭제될 때 알람 삭제 + lifecycle SNS 알림 발송 동작
- `Monitoring`과 무관한 일반 태그(`Name`, `Env` 등)만 변경될 때 이벤트를 무시하는 동작
- MODIFY 이벤트 수신 시 Auto-Remediation 수행 동작
- DELETE 이벤트 수신 시 알람 삭제 + lifecycle SNS 알림 발송 동작

**Scope:**
`_handle_tag_change` 함수 내에서 `monitoring_involved = False`인 경우의 처리 경로만 변경한다.
`Threshold_*` 접두사가 없는 태그 변경(일반 태그)은 기존과 동일하게 무시된다.
`Monitoring` 태그가 포함된 변경 이벤트의 처리 경로는 전혀 영향받지 않는다.

## Hypothesized Root Cause

`_handle_tag_change` 함수에서 `Monitoring` 태그 관여 여부만 확인하고 `Threshold_*` 태그 변경을
별도로 처리하는 분기가 누락된 것이 근본 원인이다:

1. **단일 조건 분기**: `monitoring_involved` 하나의 조건만으로 TAG_CHANGE 처리 여부를 결정하여,
   `Threshold_*` 태그 변경이라는 또 다른 처리 트리거를 고려하지 않음

2. **알람 생성과 동기화의 분리 인식 부재**: `Monitoring=on` 추가 시 알람을 생성(`create`)하는 경로는
   구현되어 있으나, 임계치 태그 변경 시 알람을 동기화(`sync`)하는 경로가 누락됨

3. **`sync_alarms_for_resource` 호출 경로 부재**: `sync_alarms_for_resource`는 `daily_monitor`에서만
   호출되고, TAG_CHANGE 이벤트 핸들러에서는 호출되지 않아 실시간 임계치 반영이 불가능한 구조

4. **`has_monitoring_tag` 미활용**: `common/tag_resolver.py`에 `has_monitoring_tag` 함수가 존재하지만
   `_handle_tag_change`에서 `Threshold_*` 처리 시 활용되지 않음

## Correctness Properties

Property 1: Fault Condition - Threshold 태그 변경 시 알람 재동기화

_For any_ TAG_CHANGE 이벤트에서 변경된 태그 키 중 `Threshold_` 접두사를 가진 키가 존재하고
해당 리소스에 `Monitoring=on` 태그가 있을 때, 수정된 `_handle_tag_change` 함수 SHALL
`sync_alarms_for_resource`를 호출하여 해당 리소스의 CloudWatch 알람을 즉시 재동기화해야 한다.

**Validates: Requirements 2.1, 2.2**

Property 2: Preservation - 비Threshold 태그 변경 동작 유지

_For any_ TAG_CHANGE 이벤트에서 변경된 태그 키 중 `Threshold_` 접두사를 가진 키가 없을 때,
수정된 `_handle_tag_change` 함수 SHALL 기존 함수와 동일한 동작을 수행하여 `Monitoring` 태그
처리 및 일반 태그 무시 동작을 그대로 보존해야 한다.

**Validates: Requirements 3.1, 3.2, 3.3**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `remediation_handler/lambda_handler.py`

**Function**: `_handle_tag_change`

**Specific Changes**:

1. **`has_monitoring_tag` import 추가**: `common.tag_resolver`에서 `has_monitoring_tag` import

2. **`sync_alarms_for_resource` import 추가**: `common.alarm_manager`에서 `sync_alarms_for_resource` import

3. **`Threshold_*` 키 존재 여부 확인**: `monitoring_involved = False` 분기에서 즉시 `return`하기 전,
   `tag_keys`에 `Threshold_` 접두사를 가진 키가 있는지 확인하는 조건 추가

4. **현재 태그 조회**: `Threshold_*` 키가 존재하면 `get_resource_tags`로 현재 리소스 태그 조회

5. **`Monitoring=on` 확인 후 sync 호출**: `has_monitoring_tag(tags)`가 `True`이면
   `sync_alarms_for_resource(resource_id, resource_type, tags)` 호출

**변경 전 코드**:
```python
monitoring_involved = "Monitoring" in tag_keys

if not monitoring_involved:
    logger.debug(
        "TAG_CHANGE for %s %s does not involve Monitoring tag: skipping",
        parsed.resource_type, parsed.resource_id,
    )
    return
```

**변경 후 코드**:
```python
monitoring_involved = "Monitoring" in tag_keys
threshold_involved = any(k.startswith("Threshold_") for k in tag_keys)

if not monitoring_involved:
    if threshold_involved:
        tags = get_resource_tags(parsed.resource_id, parsed.resource_type)
        if has_monitoring_tag(tags):
            logger.info(
                "Threshold tag changed on monitored %s %s: syncing alarms",
                parsed.resource_type, parsed.resource_id,
            )
            from common.alarm_manager import sync_alarms_for_resource
            sync_alarms_for_resource(parsed.resource_id, parsed.resource_type, tags)
        else:
            logger.debug(
                "Threshold tag changed on %s %s but Monitoring=on not set: skipping",
                parsed.resource_type, parsed.resource_id,
            )
    else:
        logger.debug(
            "TAG_CHANGE for %s %s does not involve Monitoring or Threshold tags: skipping",
            parsed.resource_type, parsed.resource_id,
        )
    return
```

## Testing Strategy

### Validation Approach

테스트 전략은 두 단계로 진행한다: 먼저 수정 전 코드에서 `Threshold_*` 태그 변경이 무시되는 버그를
재현하는 반례를 확인하고, 수정 후 알람 재동기화가 올바르게 수행되며 기존 동작이 보존되는지 검증한다.

### Exploratory Fault Condition Checking

**Goal**: 수정 전 코드에서 `_handle_tag_change`가 `Threshold_*` 태그 변경을 무시하고
`sync_alarms_for_resource`를 호출하지 않는 것을 확인하여 근본 원인 분석을 검증한다.
근본 원인이 반증되면 재분석이 필요하다.

**Test Plan**: `Threshold_CPU=90` 태그 변경 이벤트를 `_handle_tag_change`에 전달하고,
`sync_alarms_for_resource`가 호출되는지 mock으로 확인한다. 수정 전 코드에서 실행하여
호출이 발생하지 않음을 관찰한다.

**Test Cases**:
1. **CPU 임계치 태그 변경 테스트**: `Threshold_CPU=90` CreateTags 이벤트 + `Monitoring=on` 리소스
   → `sync_alarms_for_resource` 미호출 확인 (수정 전 코드에서 실패)
2. **Disk 임계치 태그 변경 테스트**: `Threshold_Disk_data=20` CreateTags 이벤트 + `Monitoring=on` EC2
   → `sync_alarms_for_resource` 미호출 확인 (수정 전 코드에서 실패)
3. **RDS 임계치 태그 변경 테스트**: `Threshold_Connections=100` AddTagsToResource 이벤트 + `Monitoring=on` RDS
   → `sync_alarms_for_resource` 미호출 확인 (수정 전 코드에서 실패)
4. **Monitoring=on 없는 리소스 테스트**: `Threshold_CPU=90` 변경 + `Monitoring=on` 없음
   → `sync_alarms_for_resource` 미호출 (수정 전/후 모두 정상 동작)

**Expected Counterexamples**:
- `sync_alarms_for_resource`가 호출되지 않음 (`monitoring_involved = False`로 즉시 `return`)
- 원인: `_handle_tag_change`에 `Threshold_*` 태그 처리 분기가 없음

### Fix Checking

**Goal**: 버그 조건이 성립하는 모든 입력에 대해 수정된 함수가 `sync_alarms_for_resource`를
올바르게 호출하는지 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := _handle_tag_change_fixed(input)
  ASSERT sync_alarms_for_resource WAS CALLED WITH (input.resource_id, input.resource_type, current_tags)
END FOR
```

### Preservation Checking

**Goal**: 버그 조건이 성립하지 않는 모든 입력에 대해 수정된 함수가 기존과 동일한 동작을
수행하는지 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT _handle_tag_change_original(input) = _handle_tag_change_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing을 활용하여 다양한 태그 키 조합(`Monitoring` 포함,
일반 태그만, `Threshold_` 없는 태그 등)에 대해 수정 전후 동작이 동일한지 검증한다.
특히 `Monitoring` 태그 처리 경로가 전혀 영향받지 않는 것을 보장한다.

**Test Plan**: 수정 전 코드에서 `Monitoring=on` 추가, `Monitoring` 삭제, 일반 태그 변경 동작을
관찰한 후, 수정 후에도 동일한 동작을 하는지 property-based test로 검증한다.

**Test Cases**:
1. **Monitoring=on 추가 보존**: `Monitoring=on` CreateTags 이벤트 → `create_alarms_for_resource` 호출이 유지되는지 검증
2. **Monitoring 삭제 보존**: `Monitoring` DeleteTags 이벤트 → 알람 삭제 + lifecycle SNS 알림이 유지되는지 검증
3. **일반 태그 무시 보존**: `Name=my-server` CreateTags 이벤트 → 무시 동작이 유지되는지 검증
4. **Threshold_* + Monitoring=on 없음 보존**: `Threshold_CPU=90` 변경 + `Monitoring=on` 없음 → 무시 동작 검증

### Unit Tests

- `Threshold_CPU=90` CreateTags + `Monitoring=on` 리소스 → `sync_alarms_for_resource` 호출 확인
- `Threshold_Disk_data=20` CreateTags + `Monitoring=on` EC2 → `sync_alarms_for_resource` 호출 확인
- `Threshold_CPU=90` CreateTags + `Monitoring=on` 없는 리소스 → `sync_alarms_for_resource` 미호출 확인
- `Monitoring=on` CreateTags → `create_alarms_for_resource` 호출 (기존 동작 보존) 확인
- `Monitoring` DeleteTags → 알람 삭제 + lifecycle SNS 알림 (기존 동작 보존) 확인
- `Name=my-server` CreateTags → 아무것도 호출되지 않음 (기존 동작 보존) 확인

### Property-Based Tests

- 임의의 `Threshold_*` 태그 키 조합 + `Monitoring=on` 리소스에 대해 `sync_alarms_for_resource`가
  항상 호출되는지 검증
- 임의의 비`Threshold_*` 태그 키 조합에 대해 수정 전후 동작이 동일한지 검증
- 임의의 `Monitoring` 태그 값 변경에 대해 기존 처리 경로가 그대로 동작하는지 검증

### Integration Tests

- EC2 인스턴스에 `Threshold_CPU=90` 태그 추가 → CloudWatch CPU 알람 임계치 90으로 갱신 확인
- RDS 인스턴스에 `Threshold_Connections=100` 태그 추가 → Connections 알람 임계치 100으로 갱신 확인
- `Monitoring=on` 없는 리소스에 `Threshold_CPU=90` 태그 추가 → 알람 변경 없음 확인
- `Monitoring=on` 추가 후 `Threshold_CPU=90` 추가 → 알람 생성 후 임계치 90으로 재동기화 확인
