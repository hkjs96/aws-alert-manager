# Disk Threshold Sync Bugfix Design

## Overview

`sync_alarms_for_resource` 함수의 디스크 알람 동기화 블록에서 모든 디스크 경로에 대해 `get_threshold(resource_tags, "Disk")`를 일괄 호출하여 경로별 태그(`Threshold_Disk_root=55`, `Threshold_Disk_data=90` 등)를 무시하고 항상 기본값(80)만 사용하는 버그를 수정한다.

수정 전략: `sync_alarms_for_resource`의 디스크 알람 임계치 비교 루프에서 각 알람의 Dimensions에서 `path` 값을 추출하고, `disk_path_to_tag_suffix`로 변환하여 `get_threshold(resource_tags, "Disk_{path_suffix}")`를 호출하도록 변경한다. 이는 `create_alarms_for_resource`에서 이미 사용 중인 패턴과 동일하다.

## Glossary

- **Bug_Condition (C)**: `sync_alarms_for_resource`가 디스크 알람의 임계치를 비교할 때 경로별 태그 키 대신 일반 `"Disk"` 키로 조회하는 조건
- **Property (P)**: 디스크 알람 동기화 시 각 경로별 태그 임계치(`Disk_root`, `Disk_data` 등)를 올바르게 조회하여 비교하는 것
- **Preservation**: 비디스크 메트릭 알람 동기화, `create_alarms_for_resource` 동작, 디스크 알람 미존재 시 재생성 트리거 등 기존 동작이 변경 없이 유지되는 것
- **`sync_alarms_for_resource`**: `common/alarm_manager.py`의 알람 동기화 함수 (버그 위치)
- **`create_alarms_for_resource`**: `common/alarm_manager.py`의 알람 생성 함수 (올바른 참조 구현)
- **`get_threshold`**: `common/tag_resolver.py`의 임계치 조회 함수 (태그 → 환경변수 → 하드코딩 기본값 순)
- **`disk_path_to_tag_suffix`**: `common/tag_resolver.py`의 경로→태그 suffix 변환 함수 (`/` → `root`, `/data` → `data`)
- **`_METRIC_DISPLAY`**: `common/alarm_manager.py`의 메트릭별 표시이름 매핑 딕셔너리

## Bug Details

### Fault Condition

`sync_alarms_for_resource`의 디스크 알람 동기화 블록(line ~510)에서 `describe_alarms`로 조회한 각 디스크 알람에 대해 `get_threshold(resource_tags, "Disk")`를 호출한다. 이 호출은 `Threshold_Disk` 태그 키를 찾지만, 실제 태그는 `Threshold_Disk_root`, `Threshold_Disk_data` 등 경로별 키로 설정되어 있어 항상 기본값(80)으로 폴백된다.

반면 `create_alarms_for_resource`에서는 각 디스크 파티션의 `path` dimension에서 suffix를 추출하여 `get_threshold(resource_tags, "Disk_root")` 형태로 올바르게 조회하고 있다.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type SyncAlarmCall { resource_id, resource_type, resource_tags, existing_disk_alarms }
  OUTPUT: boolean

  RETURN input.resource_type == "EC2"
         AND input.existing_disk_alarms is not empty
         AND ANY alarm IN input.existing_disk_alarms HAS
             alarm.Dimensions CONTAINS {Name: "path", Value: some_path}
             AND input.resource_tags CONTAINS key "Threshold_Disk_{disk_path_to_tag_suffix(some_path)}"
             AND get_threshold(input.resource_tags, "Disk") != get_threshold(input.resource_tags, "Disk_{disk_path_to_tag_suffix(some_path)}")
END FUNCTION
```

### Examples

- `Threshold_Disk_root=55` 태그 + 기존 알람 임계치 55 → sync에서 `get_threshold(tags, "Disk")` → 80 반환 → 55 ≠ 80 → 불필요한 재생성 트리거 (기대: 55 = 55 → 재생성 안 함)
- `Threshold_Disk_data=90` 태그 + 기존 `/data` 알람 임계치 90 → sync에서 `get_threshold(tags, "Disk")` → 80 반환 → 90 ≠ 80 → 불필요한 재생성 트리거 (기대: 90 = 90 → 재생성 안 함)
- `Threshold_Disk_root=55`, `Threshold_Disk_data=90` 태그 + 기존 알람 각각 55, 90 → sync에서 둘 다 80으로 비교 → 둘 다 불일치 → 재생성 (기대: 둘 다 일치 → 재생성 안 함)
- 경로별 태그 없음 + 기존 알람 임계치 80 → sync에서 `get_threshold(tags, "Disk")` → 80 → 80 = 80 → OK (이 경우는 현재도 정상 동작)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- CPU, Memory, Connections, FreeMemoryGB, FreeStorageGB, RequestCount, HealthyHostCount 등 비디스크 메트릭 알람의 sync 임계치 비교 로직은 변경 없이 유지
- `create_alarms_for_resource`의 디스크 알람 생성 로직은 변경 없이 유지 (이미 올바르게 동작)
- 디스크 알람이 하나도 존재하지 않는 리소스에 대해 `needs_recreate = True` 설정 후 전체 재생성 트리거 동작 유지
- `_find_alarms_for_resource`, `_delete_all_alarms_for_resource` 등 보조 함수 동작 변경 없음
- 경로별 태그가 없는 리소스에서 기본값(80) 폴백 동작 유지 (`get_threshold(tags, "Disk_root")` → 80)

**Scope:**
`sync_alarms_for_resource` 함수의 디스크 알람 동기화 블록(`dynamic_dimensions` 분기) 내부의 임계치 조회 호출만 변경한다. 비디스크 메트릭 처리, 알람 생성, 알람 삭제 등 다른 코드 경로는 영향받지 않는다.

## Hypothesized Root Cause

`sync_alarms_for_resource`의 디스크 알람 동기화 블록에서 `get_threshold(resource_tags, "Disk")`를 하드코딩하여 호출하는 것이 근본 원인이다:

1. **경로 추출 로직 누락**: `create_alarms_for_resource`에서는 각 `dim_set`의 `path` dimension에서 경로를 추출하여 `Disk_{suffix}` 형태의 metric key를 구성하지만, `sync_alarms_for_resource`에서는 `describe_alarms` 응답의 `Dimensions`에서 `path`를 추출하는 로직이 없음

2. **일괄 키 사용**: `sync_alarms_for_resource`의 line ~516에서 `disk_threshold = get_threshold(resource_tags, "Disk")`로 모든 디스크 알람에 동일한 키를 사용. `get_threshold`는 `Threshold_Disk` 태그를 찾지만, 사용자는 `Threshold_Disk_root`, `Threshold_Disk_data` 등 경로별 키를 설정하므로 태그 매칭 실패 → 기본값(80) 폴백

3. **create와 sync 간 로직 불일치**: `create_alarms_for_resource`는 CWAgent 메트릭의 dimension에서 path를 추출하여 경로별 임계치를 조회하지만, `sync_alarms_for_resource`는 이 패턴을 따르지 않음. 두 함수가 동일한 임계치 조회 전략을 사용해야 하는데 sync 쪽이 누락됨

## Correctness Properties

Property 1: Fault Condition - 디스크 알람 경로별 임계치 조회

_For any_ `sync_alarms_for_resource` 호출에서 기존 디스크 알람이 존재하고 해당 알람의 Dimensions에 `path` 값이 포함되어 있을 때, 수정된 함수 SHALL 해당 path에서 `disk_path_to_tag_suffix`로 suffix를 추출하고 `get_threshold(resource_tags, "Disk_{suffix}")`를 호출하여 경로별 임계치를 조회해야 한다.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

Property 2: Preservation - 비디스크 메트릭 및 기본값 폴백 동작 유지

_For any_ `sync_alarms_for_resource` 호출에서 비디스크 메트릭 알람(CPU, Memory 등)에 대해서는 기존과 동일하게 `get_threshold(resource_tags, metric)`으로 임계치를 조회하고, 경로별 태그가 없는 디스크 알람에 대해서는 `get_threshold(resource_tags, "Disk_{suffix}")` → 기본값(80) 폴백이 정상 동작하여 기존과 동일한 결과를 생성해야 한다.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `common/alarm_manager.py`

**Function**: `sync_alarms_for_resource`

**Specific Changes**:

1. **import 추가**: `disk_path_to_tag_suffix`를 import (파일 상단 또는 함수 내 지역 import)

2. **Dimensions에서 path 추출**: `describe_alarms` 응답의 각 알람에서 `Dimensions` 리스트를 순회하여 `Name == "path"`인 dimension의 `Value`를 추출

3. **경로별 metric key 구성**: 추출한 path를 `disk_path_to_tag_suffix`로 변환하여 `"Disk_{suffix}"` 형태의 metric key 생성 (예: `/` → `"Disk_root"`, `/data` → `"Disk_data"`)

4. **get_threshold 호출 변경**: `get_threshold(resource_tags, "Disk")`를 `get_threshold(resource_tags, f"Disk_{suffix}")`로 변경

5. **path 추출 실패 시 폴백**: Dimensions에 path가 없는 경우 기본값 `"/"` 사용 (기존 `create_alarms_for_resource`와 동일한 패턴)

**변경 전 코드** (line ~510-518):
```python
for alarm in resp.get("MetricAlarms", []):
    name = alarm["AlarmName"]
    existing_threshold = alarm.get("Threshold", 0)
    disk_threshold = get_threshold(resource_tags, "Disk")
    if abs(existing_threshold - disk_threshold) > 0.001:
        needs_recreate = True
        result["updated"].append(name)
    else:
        result["ok"].append(name)
```

**변경 후 코드**:
```python
for alarm in resp.get("MetricAlarms", []):
    name = alarm["AlarmName"]
    existing_threshold = alarm.get("Threshold", 0)
    # 알람 Dimensions에서 path 추출 (create_alarms_for_resource와 동일 패턴)
    path = next(
        (d["Value"] for d in alarm.get("Dimensions", []) if d["Name"] == "path"),
        "/",
    )
    suffix = disk_path_to_tag_suffix(path)
    disk_threshold = get_threshold(resource_tags, f"Disk_{suffix}")
    if abs(existing_threshold - disk_threshold) > 0.001:
        needs_recreate = True
        result["updated"].append(name)
    else:
        result["ok"].append(name)
```

## Testing Strategy

### Validation Approach

테스트 전략은 두 단계로 진행한다: 먼저 수정 전 코드에서 경로별 태그가 무시되는 버그를 재현하는 반례를 확인하고, 수정 후 경로별 임계치가 올바르게 조회되며 기존 동작이 보존되는지 검증한다.

### Exploratory Fault Condition Checking

**Goal**: 수정 전 코드에서 `sync_alarms_for_resource`가 경로별 디스크 태그를 무시하고 기본값(80)을 사용하는 것을 확인하여 근본 원인 분석을 검증한다. 근본 원인이 반증되면 재분석이 필요하다.

**Test Plan**: `sync_alarms_for_resource`를 경로별 디스크 태그가 설정된 리소스에 대해 호출하고, `get_threshold`가 `"Disk"` 키로 호출되는지 (버그) 또는 `"Disk_root"` 키로 호출되는지 (정상) 확인한다. 수정 전 코드에서 실행하여 `"Disk"` 키 호출을 관찰한다.

**Test Cases**:
1. **Root 경로 태그 무시 테스트**: `Threshold_Disk_root=55` 태그 + 기존 알람 임계치 55 → sync가 80으로 비교하여 불필요한 재생성 트리거 (수정 전 코드에서 실패)
2. **Data 경로 태그 무시 테스트**: `Threshold_Disk_data=90` 태그 + 기존 `/data` 알람 임계치 90 → sync가 80으로 비교하여 불필요한 재생성 트리거 (수정 전 코드에서 실패)
3. **다중 경로 태그 무시 테스트**: `Threshold_Disk_root=55`, `Threshold_Disk_data=90` 태그 + 각각 올바른 임계치 알람 → 둘 다 80으로 비교 (수정 전 코드에서 실패)
4. **get_threshold 호출 키 확인**: mock을 사용하여 `get_threshold`가 `"Disk"` 키로 호출되는지 확인 (수정 전 코드에서 실패)

**Expected Counterexamples**:
- `get_threshold`가 `"Disk_root"`, `"Disk_data"` 대신 `"Disk"`로 호출됨
- 경로별 태그 임계치와 기존 알람 임계치가 일치함에도 `needs_recreate = True` 설정됨
- 원인: `sync_alarms_for_resource`에서 알람 Dimensions의 path를 추출하지 않고 일괄 `"Disk"` 키 사용

### Fix Checking

**Goal**: 버그 조건이 성립하는 모든 입력에 대해 수정된 함수가 경로별 임계치를 올바르게 조회하는지 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := sync_alarms_for_resource_fixed(input.resource_id, input.resource_type, input.resource_tags)
  FOR EACH disk_alarm IN input.existing_disk_alarms DO
    path := extract_path_from_dimensions(disk_alarm.Dimensions)
    suffix := disk_path_to_tag_suffix(path)
    expected_threshold := get_threshold(input.resource_tags, "Disk_" + suffix)
    IF disk_alarm.Threshold == expected_threshold THEN
      ASSERT disk_alarm.AlarmName IN result["ok"]
    ELSE
      ASSERT disk_alarm.AlarmName IN result["updated"]
    END IF
  END FOR
END FOR
```

### Preservation Checking

**Goal**: 버그 조건이 성립하지 않는 모든 입력에 대해 수정된 함수가 기존과 동일한 결과를 생성하는지 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT sync_alarms_for_resource_original(input) = sync_alarms_for_resource_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing을 활용하여 다양한 리소스 태그 조합(경로별 태그 없음, 기본값만 사용, 비디스크 메트릭 등)에 대해 수정 전후 동작이 동일한지 검증한다. 특히 비디스크 메트릭 알람의 sync 동작이 전혀 영향받지 않는 것을 보장한다.

**Test Plan**: 수정 전 코드에서 경로별 태그가 없는 리소스, 비디스크 메트릭 알람의 sync 동작을 관찰한 후, 수정 후에도 동일한 동작을 하는지 property-based test로 검증한다.

**Test Cases**:
1. **비디스크 메트릭 보존**: CPU, Memory 등 비디스크 알람의 sync 결과가 수정 전후 동일한지 검증
2. **기본값 폴백 보존**: 경로별 태그가 없는 디스크 알람에 대해 `get_threshold(tags, "Disk_root")` → 80 폴백이 정상 동작하는지 검증
3. **알람 미존재 시 재생성 보존**: 디스크 알람이 없을 때 `needs_recreate = True` 설정 후 `create_alarms_for_resource` 호출이 유지되는지 검증
4. **create_alarms_for_resource 동작 보존**: 디스크 알람 생성 로직이 변경되지 않았는지 검증

### Unit Tests

- `sync_alarms_for_resource`에서 `Threshold_Disk_root=55` 태그 + 기존 알람 임계치 55 → 재생성 안 함 확인
- `sync_alarms_for_resource`에서 `Threshold_Disk_data=90` 태그 + 기존 `/data` 알람 임계치 90 → 재생성 안 함 확인
- `sync_alarms_for_resource`에서 `Threshold_Disk_root=55` 태그 + 기존 알람 임계치 80 → 재생성 트리거 확인
- `sync_alarms_for_resource`에서 경로별 태그 없음 + 기존 알람 임계치 80 → 재생성 안 함 확인 (기본값 폴백)
- `sync_alarms_for_resource`에서 Dimensions에 path가 없는 알람 → 기본값 `/` 사용 확인
- 비디스크 메트릭(CPU, Memory) 알람의 sync 동작이 변경되지 않음 확인

### Property-Based Tests

- 임의의 디스크 경로와 경로별 태그 조합에 대해 sync가 올바른 metric key로 `get_threshold`를 호출하는지 검증
- 임의의 비디스크 메트릭과 태그 조합에 대해 sync 결과가 수정 전후 동일한지 검증
- 임의의 `disk_path_to_tag_suffix` 입력에 대해 path → suffix → metric key 변환이 `create_alarms_for_resource`와 동일한 패턴을 따르는지 검증

### Integration Tests

- EC2 리소스에 `Threshold_Disk_root=55`, `Threshold_Disk_data=90` 태그 설정 후 전체 sync 흐름에서 올바른 임계치 비교 확인
- 알람 생성(`create`) → 태그 변경 → 알람 동기화(`sync`) 전체 흐름에서 경로별 임계치가 일관되게 적용되는지 확인
- 다중 디스크 파티션(/, /data, /var/log)이 있는 EC2 인스턴스에서 sync가 각 경로별로 올바른 임계치를 사용하는지 확인
