# Selective Alarm Update Bugfix Design

## Overview

`sync_alarms_for_resource` 함수에서 `needs_recreate = True`가 되면 `create_alarms_for_resource` 전체를 호출하고, 이 함수 내부에서 `_delete_all_alarms_for_resource`로 해당 리소스의 **모든** 알람을 삭제한 뒤 전체 재생성한다.

결과적으로 `Threshold_Disk_data` 태그 하나만 변경되어도 CPU, Memory, Disk_root 등 변경되지 않은 알람까지 불필요하게 삭제·재생성된다. 이는 알람 상태 초기화, 불필요한 AWS API 호출, 재생성 중 알람 공백 구간을 유발한다.

수정 전략: `sync_alarms_for_resource` 마지막 부분에서 `create_alarms_for_resource` 전체 호출 대신, `result["updated"]` 리스트의 알람만 개별 삭제 후 재생성하고, `result["created"]` 리스트의 메트릭은 기존 알람 삭제 없이 신규 생성하는 `_recreate_alarm_by_name` 헬퍼 함수를 추가한다.

## Glossary

- **Bug_Condition (C)**: `sync_alarms_for_resource`에서 `needs_recreate = True`가 되어 `create_alarms_for_resource` 전체를 호출함으로써 변경되지 않은 알람까지 삭제되는 조건
- **Property (P)**: `needs_recreate = True` 시 `result["updated"]` 알람만 개별 삭제·재생성하고, `result["created"]` 메트릭만 신규 생성하는 것
- **Preservation**: 최초 생성 시 `create_alarms_for_resource` 전체 호출, 모든 알람 일치 시 아무 동작 없음, 변경되지 않은 알람 유지 등 기존 동작이 변경 없이 유지되는 것
- **`sync_alarms_for_resource`**: `common/alarm_manager.py`의 알람 동기화 함수 (버그 위치)
- **`create_alarms_for_resource`**: `common/alarm_manager.py`의 알람 전체 생성 함수 (최초 생성 시 사용, 변경하지 않음)
- **`_recreate_alarm_by_name`**: 신규 추가할 헬퍼 함수 - 알람 이름에서 메트릭 타입을 파악하여 해당 알람만 삭제 후 `put_metric_alarm`으로 재생성
- **`result["updated"]`**: 임계치가 변경된 기존 알람 이름 목록 (개별 삭제·재생성 대상)
- **`result["created"]`**: 기존에 없어서 새로 생성해야 할 메트릭 이름 목록 (신규 생성 대상)
- **`result["ok"]`**: 임계치가 현재 태그와 일치하는 알람 이름 목록 (변경 없이 유지)
- **`_METRIC_DISPLAY`**: `common/alarm_manager.py`의 메트릭별 표시이름 매핑 딕셔너리

## Bug Details

### Fault Condition

`sync_alarms_for_resource` 함수 마지막 부분에서 `needs_recreate = True`이면 `create_alarms_for_resource(resource_id, resource_type, resource_tags)`를 호출한다. 이 함수는 내부에서 `_delete_all_alarms_for_resource(resource_id)`를 먼저 호출하여 해당 리소스의 모든 알람을 삭제한 뒤 전체 재생성한다. 따라서 `result["updated"]`에 포함된 알람 하나만 변경되어도 `result["ok"]`에 있는 변경되지 않은 알람까지 모두 삭제·재생성된다.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type SyncAlarmCall { resource_id, resource_type, resource_tags, existing_alarms }
  OUTPUT: boolean

  result := compute_sync_result(input)

  RETURN result["updated"] is not empty OR result["created"] is not empty
         AND result["ok"] is not empty
         AND create_alarms_for_resource IS CALLED (which deletes ALL alarms including result["ok"])
END FUNCTION
```

### Examples

- `Threshold_Disk_data=90` 태그 변경 → `result["updated"] = ["[EC2] my-server disk_used_percent(/data) >90% (i-xxx)"]`, `result["ok"] = [CPU 알람, Memory 알람, Disk_root 알람]` → 현재: 4개 알람 모두 삭제·재생성, 기대: Disk_data 알람 1개만 삭제·재생성
- `Threshold_CPU=90` 태그 변경 → `result["updated"] = [CPU 알람]`, `result["ok"] = [Memory 알람, Disk 알람들]` → 현재: 전체 삭제·재생성, 기대: CPU 알람 1개만 삭제·재생성
- 신규 EC2에 Memory 알람이 없는 경우 → `result["created"] = ["Memory"]`, `result["ok"] = [CPU 알람]` → 현재: CPU 알람 삭제 후 전체 재생성, 기대: CPU 알람 유지하고 Memory 알람만 신규 생성
- `result["ok"]`만 존재 (모든 임계치 일치) → `needs_recreate = False` → 현재/기대 모두 아무 동작 없음 (정상)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- 리소스에 알람이 하나도 없는 최초 생성 시 `create_alarms_for_resource` 전체 호출 동작 유지
- 모든 알람 임계치가 현재 태그와 일치하는 경우(`result["ok"]`만 존재) 아무 동작도 하지 않는 동작 유지
- `result["ok"]` 목록의 알람은 삭제하거나 수정하지 않고 그대로 유지
- `create_alarms_for_resource` 함수 자체는 변경하지 않음 (최초 생성 시 전체 삭제 로직 유지)
- `_delete_all_alarms_for_resource`, `_find_alarms_for_resource` 등 보조 함수 동작 변경 없음

**Scope:**
`sync_alarms_for_resource` 함수의 마지막 `if needs_recreate:` 블록만 변경한다. 임계치 비교 루프, 알람 조회 로직, 최초 생성 분기 등 다른 코드 경로는 영향받지 않는다.

## Hypothesized Root Cause

`sync_alarms_for_resource`의 마지막 부분에서 `needs_recreate = True`일 때 `create_alarms_for_resource` 전체를 호출하는 것이 근본 원인이다:

1. **전체 재생성 함수 재사용**: `create_alarms_for_resource`는 최초 생성 목적으로 설계되어 내부에서 `_delete_all_alarms_for_resource`를 먼저 호출한다. 이 함수를 sync 시 부분 업데이트에 재사용하면서 의도치 않게 전체 삭제가 발생함

2. **개별 알람 재생성 로직 부재**: `sync_alarms_for_resource`가 `result["updated"]`와 `result["created"]`를 구분하여 수집하지만, 이 정보를 활용하여 개별 알람만 처리하는 로직이 없음

3. **알람 이름 → 메트릭 타입 역매핑 부재**: 알람 이름(예: `[EC2] my-server CPUUtilization >80% (i-xxx)`)에서 메트릭 타입(CPU)을 역으로 파악하여 해당 알람만 재생성하는 헬퍼 함수가 없음

4. **sync와 create의 책임 분리 미흡**: sync는 변경된 것만 업데이트해야 하지만, create를 그대로 호출함으로써 "전체 삭제 후 전체 재생성"이라는 create의 책임이 sync에 전이됨

## Correctness Properties

Property 1: Fault Condition - 변경된 알람만 개별 삭제·재생성

_For any_ `sync_alarms_for_resource` 호출에서 `result["updated"]`가 비어있지 않고 `result["ok"]`도 비어있지 않을 때, 수정된 함수 SHALL `result["ok"]` 목록의 알람은 삭제하지 않고, `result["updated"]` 목록의 알람만 개별 삭제 후 `put_metric_alarm`으로 재생성해야 한다.

**Validates: Requirements 2.1, 2.3**

Property 2: Preservation - 변경되지 않은 알람 및 최초 생성 동작 유지

_For any_ `sync_alarms_for_resource` 호출에서 버그 조건이 성립하지 않는 경우(알람이 없어 최초 생성하는 경우, 또는 `result["ok"]`만 존재하는 경우), 수정된 함수 SHALL 기존 함수와 동일한 동작을 수행하여 최초 생성 시 `create_alarms_for_resource` 호출 및 모든 일치 시 아무 동작 없음을 그대로 보존해야 한다.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `common/alarm_manager.py`

**Specific Changes**:

1. **`_recreate_alarm_by_name` 헬퍼 함수 추가**: 알람 이름에서 메트릭 타입을 파악하여 해당 알람만 삭제 후 `put_metric_alarm`으로 재생성하는 함수

   - 알람 이름에서 메트릭 식별: `CPUUtilization` → CPU, `mem_used_percent` → Memory, `disk_used_percent` → Disk
   - `cw.delete_alarms(AlarmNames=[alarm_name])`으로 해당 알람만 삭제
   - 알람 정의(`_get_alarm_defs`)에서 해당 메트릭의 설정을 찾아 `put_metric_alarm` 호출
   - Disk 알람의 경우 기존 알람의 Dimensions를 `describe_alarms`로 조회하여 재사용

2. **`sync_alarms_for_resource` 마지막 블록 수정**:

   - 기존: `if needs_recreate: create_alarms_for_resource(resource_id, resource_type, resource_tags)`
   - 변경: `result["updated"]` 각 알람에 대해 `_recreate_alarm_by_name` 호출, `result["created"]` 각 메트릭에 대해 신규 알람만 생성

**변경 전 코드**:
```python
if needs_recreate:
    create_alarms_for_resource(resource_id, resource_type, resource_tags)
```

**변경 후 코드**:
```python
if needs_recreate:
    # 변경된 알람만 개별 삭제·재생성
    for alarm_name in result["updated"]:
        _recreate_alarm_by_name(alarm_name, resource_id, resource_type, resource_tags)
    # 신규 알람만 생성 (전체 삭제 없이)
    for metric in result["created"]:
        _create_single_alarm(metric, resource_id, resource_type, resource_tags)
```

**`_recreate_alarm_by_name` 구현 방향**:
```python
def _recreate_alarm_by_name(
    alarm_name: str,
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
) -> None:
    """알람 이름에서 메트릭 타입을 파악하여 해당 알람만 삭제 후 재생성."""
    cw = _get_cw_client()
    # 1. 기존 알람 설정 조회 (Dimensions 재사용 목적)
    try:
        resp = cw.describe_alarms(AlarmNames=[alarm_name])
        existing = resp.get("MetricAlarms", [])
    except ClientError as e:
        logger.error("Failed to describe alarm %s: %s", alarm_name, e)
        return

    # 2. 알람 이름에서 메트릭 타입 식별
    metric_name_in_alarm = existing[0]["MetricName"] if existing else ""
    # CPUUtilization → CPU, mem_used_percent → Memory, disk_used_percent → Disk
    metric_key = _metric_name_to_key(metric_name_in_alarm)

    # 3. 해당 알람만 삭제
    try:
        cw.delete_alarms(AlarmNames=[alarm_name])
    except ClientError as e:
        logger.error("Failed to delete alarm %s: %s", alarm_name, e)
        return

    # 4. put_metric_alarm으로 재생성 (기존 Dimensions 재사용)
    _put_alarm_for_metric(metric_key, resource_id, resource_type, resource_tags,
                          existing_dims=existing[0].get("Dimensions", []) if existing else None)
```

## Testing Strategy

### Validation Approach

테스트 전략은 두 단계로 진행한다: 먼저 수정 전 코드에서 변경되지 않은 알람까지 삭제되는 버그를 재현하는 반례를 확인하고, 수정 후 변경된 알람만 개별 처리되며 기존 동작이 보존되는지 검증한다.

### Exploratory Fault Condition Checking

**Goal**: 수정 전 코드에서 `sync_alarms_for_resource`가 `result["ok"]` 알람까지 삭제하는 것을 확인하여 근본 원인 분석을 검증한다. 근본 원인이 반증되면 재분석이 필요하다.

**Test Plan**: `Threshold_Disk_data=90` 태그 변경 시나리오에서 `sync_alarms_for_resource`를 호출하고, `_delete_all_alarms_for_resource`가 호출되는지 mock으로 확인한다. 수정 전 코드에서 실행하여 변경되지 않은 CPU/Memory 알람까지 삭제됨을 관찰한다.

**Test Cases**:
1. **단일 알람 변경 테스트**: Disk_data 임계치 변경 → CPU/Memory/Disk_root 알람이 삭제되는지 확인 (수정 전 코드에서 실패)
2. **신규 알람 추가 테스트**: Memory 알람 누락 → CPU 알람이 삭제되는지 확인 (수정 전 코드에서 실패)
3. **`_delete_all_alarms_for_resource` 호출 확인**: `needs_recreate=True` 시 전체 삭제 함수가 호출되는지 mock으로 확인 (수정 전 코드에서 실패)
4. **result["ok"] 알람 보존 확인**: 변경되지 않은 알람이 sync 후에도 존재하는지 확인 (수정 전 코드에서 실패)

**Expected Counterexamples**:
- `result["ok"]` 목록의 알람이 삭제됨 (`_delete_all_alarms_for_resource` 호출로 인해)
- 원인: `create_alarms_for_resource` 내부에서 `_delete_all_alarms_for_resource`를 먼저 호출하는 구조

### Fix Checking

**Goal**: 버그 조건이 성립하는 모든 입력에 대해 수정된 함수가 `result["updated"]` 알람만 개별 삭제·재생성하는지 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := sync_alarms_for_resource_fixed(input.resource_id, input.resource_type, input.resource_tags)
  FOR EACH alarm_name IN result["updated"] DO
    ASSERT alarm_name WAS DELETED individually (not via _delete_all_alarms_for_resource)
    ASSERT alarm_name WAS RECREATED via put_metric_alarm
  END FOR
  FOR EACH alarm_name IN result["ok"] DO
    ASSERT alarm_name WAS NOT DELETED
  END FOR
END FOR
```

### Preservation Checking

**Goal**: 버그 조건이 성립하지 않는 모든 입력에 대해 수정된 함수가 기존과 동일한 동작을 수행하는지 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT sync_alarms_for_resource_original(input) = sync_alarms_for_resource_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing을 활용하여 다양한 시나리오(알람 없음, 모든 알람 일치, 일부 알람 변경 등)에 대해 수정 전후 동작이 동일한지 검증한다. 특히 최초 생성 경로와 모든 알람 일치 경로가 전혀 영향받지 않는 것을 보장한다.

**Test Plan**: 수정 전 코드에서 알람 없음(최초 생성), 모든 알람 일치 시나리오의 동작을 관찰한 후, 수정 후에도 동일한 동작을 하는지 property-based test로 검증한다.

**Test Cases**:
1. **최초 생성 보존**: 알람이 없을 때 `create_alarms_for_resource` 호출이 유지되는지 검증
2. **모든 알람 일치 보존**: `result["ok"]`만 존재할 때 아무 삭제/재생성도 발생하지 않는지 검증
3. **변경되지 않은 알람 보존**: `result["ok"]` 알람이 sync 후에도 그대로 존재하는지 검증
4. **`create_alarms_for_resource` 불변 보존**: 함수 자체가 변경되지 않아 직접 호출 시 기존 동작이 유지되는지 검증

### Unit Tests

- `Threshold_Disk_data=90` 변경 → Disk_data 알람만 삭제·재생성, CPU/Memory/Disk_root 알람 유지 확인
- `Threshold_CPU=90` 변경 → CPU 알람만 삭제·재생성, 나머지 알람 유지 확인
- Memory 알람 누락 → Memory 알람만 신규 생성, 기존 CPU 알람 삭제 없음 확인
- 알람 없음 → `create_alarms_for_resource` 전체 호출 (기존 동작 보존) 확인
- 모든 알람 일치 → 아무 삭제/재생성도 발생하지 않음 확인
- `_recreate_alarm_by_name` 단위 테스트: 알람 이름에서 메트릭 타입 식별 정확성 확인

### Property-Based Tests

- 임의의 `result["updated"]` 알람 목록에 대해 해당 알람만 개별 삭제되고 `result["ok"]` 알람은 삭제되지 않는지 검증
- 임의의 알람 없음/모든 일치 시나리오에 대해 수정 전후 동작이 동일한지 검증
- 임의의 메트릭 타입 조합에 대해 `_recreate_alarm_by_name`이 올바른 메트릭 키를 식별하는지 검증

### Integration Tests

- EC2 리소스에서 `Threshold_Disk_data=90` 태그 변경 → Disk_data 알람만 재생성, 나머지 알람 상태 유지 확인
- 알람 생성(`create`) → 태그 변경 → 알람 동기화(`sync`) 전체 흐름에서 변경된 알람만 업데이트되는지 확인
- 다중 알람 변경(CPU + Memory 동시 변경) 시 해당 알람들만 재생성되는지 확인
