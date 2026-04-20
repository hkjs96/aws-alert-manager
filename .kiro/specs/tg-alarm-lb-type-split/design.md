# TG Alarm LB Type Split Bugfix Design

## Overview

NLB Target Group에 ALB 전용 메트릭(`RequestCountPerTarget`, `TGResponseTime`)에 대한 알람이 생성되어 영구적으로 `INSUFFICIENT_DATA` 상태에 빠지는 버그를 수정한다. `_TG_ALARMS`가 단일 리스트로 4개 알람을 정의하고 `_get_alarm_defs("TG")`가 LB 타입을 구분하지 않아 발생한다. 수정 접근: `_get_alarm_defs()`에 `resource_tags`를 전달하여 `_lb_type` 기반으로 TG 알람 정의를 필터링하고, 관련 동기화 헬퍼와 `_HARDCODED_METRIC_KEYS`도 동일하게 LB 타입을 반영한다.

## Glossary

- **Bug_Condition (C)**: TG 리소스에 대해 `_lb_type == "network"`일 때 `_get_alarm_defs("TG")`가 ALB 전용 메트릭(`RequestCountPerTarget`, `TGResponseTime`)을 포함한 알람 정의를 반환하는 조건
- **Property (P)**: NLB TG에는 `HealthyHostCount`, `UnHealthyHostCount`만, ALB TG에는 4개 전체 메트릭에 대한 알람이 생성되는 것
- **Preservation**: ALB TG의 기존 4개 알람 생성, EC2/RDS/ALB/NLB 리소스의 알람 생성, `_build_dimensions()`, `_resolve_tg_namespace()`, `_find_alarms_for_resource()` 동작이 변경 없이 유지되는 것
- **`_TG_ALARMS`**: `common/alarm_manager.py`의 TG 알람 정의 리스트 (현재 4개: HealthyHostCount, UnHealthyHostCount, RequestCountPerTarget, TGResponseTime)
- **`_get_alarm_defs()`**: resource_type을 받아 해당 타입의 알람 정의 리스트를 반환하는 함수
- **`_lb_type`**: ELB Collector가 `resource_tags`에 주입하는 LB 타입 값 (`"application"` 또는 `"network"`)
- **`_HARDCODED_METRIC_KEYS`**: resource_type별 하드코딩 메트릭 키 집합 (동적 태그 파싱 시 하드코딩 메트릭 제외용)

## Bug Details

### Bug Condition

`_get_alarm_defs("TG")`가 `_lb_type`을 고려하지 않고 항상 동일한 `_TG_ALARMS` 리스트(4개)를 반환한다. NLB TG에서는 `RequestCountPerTarget`과 `TGResponseTime`이 `AWS/NetworkELB` 네임스페이스에 존재하지 않으므로 해당 알람이 `INSUFFICIENT_DATA` 상태에 빠진다.

**Formal Specification:**
```
FUNCTION isBugCondition(resource_type, resource_tags)
  INPUT: resource_type of type str, resource_tags of type dict
  OUTPUT: boolean

  RETURN resource_type == "TG"
         AND resource_tags.get("_lb_type") == "network"
         AND _get_alarm_defs("TG") contains alarm_def
             WHERE alarm_def["metric"] IN ["RequestCountPerTarget", "TGResponseTime"]
END FUNCTION
```

### Examples

- NLB TG (`_lb_type="network"`)에 `create_alarms_for_resource()` 호출 → `RequestCountPerTarget` 알람이 `AWS/NetworkELB` 네임스페이스로 생성됨 → `INSUFFICIENT_DATA` (기대: 알람 미생성)
- NLB TG (`_lb_type="network"`)에 `create_alarms_for_resource()` 호출 → `TGResponseTime` 알람이 `AWS/NetworkELB` 네임스페이스로 생성됨 → `INSUFFICIENT_DATA` (기대: 알람 미생성)
- ALB TG (`_lb_type="application"`)에 `create_alarms_for_resource()` 호출 → 4개 알람 모두 정상 생성 (이 경우는 버그 아님)
- NLB TG에 `sync_alarms_for_resource()` 호출 → `RequestCountPerTarget`과 `TGResponseTime`에 대한 동기화 시도 (기대: 동기화 대상에서 제외)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- ALB TG(`_lb_type="application"`)에 대해 `create_alarms_for_resource()` 호출 시 기존과 동일하게 4개 알람 생성
- ALB TG에 대해 `sync_alarms_for_resource()` 호출 시 기존과 동일하게 4개 메트릭 동기화
- EC2, RDS, ALB, NLB 리소스에 대한 `_get_alarm_defs()` 반환값 변경 없음
- `_build_dimensions()`의 TG 복합 디멘션(TargetGroup + LoadBalancer) 생성 로직 변경 없음
- `_resolve_tg_namespace()`의 네임스페이스 결정 로직 변경 없음
- `_find_alarms_for_resource()`의 알람 검색 로직 변경 없음
- 동적 태그 알람(`_parse_threshold_tags`) 처리 로직 변경 없음

**Scope:**
`_lb_type != "network"`인 모든 TG 리소스와 TG가 아닌 모든 리소스 유형(EC2, RDS, ALB, NLB)은 이 수정에 의해 영향받지 않아야 한다.

## Hypothesized Root Cause

Based on the bug description, the most likely issues are:

1. **`_get_alarm_defs()` 시그니처 제한**: `_get_alarm_defs(resource_type)`가 `resource_type`만 받고 `resource_tags`를 받지 않아 `_lb_type` 기반 필터링이 불가능하다. TG 타입에 대해 항상 동일한 `_TG_ALARMS` 4개를 반환한다.

2. **`_TG_ALARMS` 단일 리스트**: ALB TG와 NLB TG의 유효 메트릭이 다름에도 불구하고 단일 리스트로 정의되어 있다. NLB TG에서는 `RequestCountPerTarget`과 `TGResponseTime`이 `AWS/NetworkELB` 네임스페이스에 존재하지 않는다.

3. **`_HARDCODED_METRIC_KEYS["TG"]` 미분리**: `_HARDCODED_METRIC_KEYS["TG"]`가 `{"HealthyHostCount", "UnHealthyHostCount", "RequestCountPerTarget", "TGResponseTime"}`으로 고정되어 있어, NLB TG에서도 `RequestCountPerTarget`과 `TGResponseTime`이 하드코딩 메트릭으로 인식된다.

4. **동기화 헬퍼 미분리**: `sync_alarms_for_resource()`와 `_create_single_alarm()`이 `_get_alarm_defs(resource_type)`를 호출하므로 동일한 문제가 전파된다.

## Correctness Properties

Property 1: Bug Condition - NLB TG에 ALB 전용 알람 미생성

_For any_ TG 리소스 where `_lb_type == "network"`, the fixed `create_alarms_for_resource()` function SHALL create only `HealthyHostCount` and `UnHealthyHostCount` alarms, and SHALL NOT create `RequestCountPerTarget` or `TGResponseTime` alarms.

**Validates: Requirements 2.1, 2.4**

Property 2: Preservation - ALB TG 및 비-TG 리소스 알람 동작 유지

_For any_ TG 리소스 where `_lb_type == "application"` OR any non-TG 리소스(EC2, RDS, ALB, NLB), the fixed `create_alarms_for_resource()` function SHALL produce the same set of alarms as the original function, preserving all existing alarm creation behavior.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `common/alarm_manager.py`

**Function**: `_get_alarm_defs()`

**Specific Changes**:

1. **`_get_alarm_defs()` 시그니처 확장**: `resource_tags: dict | None = None` 파라미터를 추가한다. 기존 호출부에서 `resource_tags`를 전달하지 않는 경우 기본값 `None`으로 기존 동작을 유지한다.

2. **NLB TG 필터링 로직 추가**: `resource_type == "TG"`이고 `resource_tags.get("_lb_type") == "network"`인 경우, `_TG_ALARMS`에서 `RequestCountPerTarget`과 `TGResponseTime`을 제외한 리스트를 반환한다. NLB TG 유효 메트릭: `{"HealthyHostCount", "UnHealthyHostCount"}`.

3. **호출부 업데이트 - `create_alarms_for_resource()`**: `_get_alarm_defs(resource_type)` → `_get_alarm_defs(resource_type, resource_tags)` 변경.

4. **호출부 업데이트 - `sync_alarms_for_resource()`**: `_get_alarm_defs(resource_type)` → `_get_alarm_defs(resource_type, resource_tags)` 변경.

5. **호출부 업데이트 - `_create_single_alarm()`**: `_get_alarm_defs(resource_type)` → `_get_alarm_defs(resource_type, resource_tags)` 변경.

6. **호출부 업데이트 - `_recreate_alarm_by_name()`**: `_get_alarm_defs(resource_type)` → `_get_alarm_defs(resource_type, resource_tags)` 변경.

7. **`_HARDCODED_METRIC_KEYS` 동적화**: NLB TG에서 `_parse_threshold_tags()`가 `RequestCountPerTarget`과 `TGResponseTime`을 동적 메트릭으로 오인하지 않도록, `_HARDCODED_METRIC_KEYS` 조회도 `_lb_type`을 반영하거나, `_get_alarm_defs()` 결과에서 메트릭 키 집합을 동적으로 추출하는 헬퍼를 추가한다.

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: NLB TG에 대해 `create_alarms_for_resource()`를 호출하고 생성된 알람 목록에 `RequestCountPerTarget` 또는 `TGResponseTime`이 포함되는지 확인한다. Run these tests on the UNFIXED code to observe failures and understand the root cause.

**Test Cases**:
1. **NLB TG Create Alarms**: `_lb_type="network"` TG에 `create_alarms_for_resource()` 호출 → 4개 알람 생성됨 확인 (will fail on unfixed code: 4개 대신 2개만 기대)
2. **NLB TG Sync Alarms**: `_lb_type="network"` TG에 `sync_alarms_for_resource()` 호출 → `RequestCountPerTarget`과 `TGResponseTime` 동기화 시도 확인 (will fail on unfixed code)
3. **NLB TG get_alarm_defs**: `_get_alarm_defs("TG")` 호출 → 항상 4개 반환 확인 (will fail on unfixed code: NLB TG에서 2개만 기대)

**Expected Counterexamples**:
- `create_alarms_for_resource(nlb_tg_arn, "TG", {"_lb_type": "network", ...})` returns 4 alarm names including `RequestCountPerTarget` and `TGResponseTime`
- Possible causes: `_get_alarm_defs("TG")` ignores `_lb_type`, `_TG_ALARMS` is a single undifferentiated list

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL (resource_id, resource_tags) WHERE isBugCondition("TG", resource_tags) DO
  result := create_alarms_for_resource_fixed(resource_id, "TG", resource_tags)
  alarm_metrics := extract_metric_keys(result)
  ASSERT "RequestCountPerTarget" NOT IN alarm_metrics
  ASSERT "TGResponseTime" NOT IN alarm_metrics
  ASSERT "HealthyHostCount" IN alarm_metrics
  ASSERT "UnHealthyHostCount" IN alarm_metrics
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL (resource_id, resource_type, resource_tags) WHERE NOT isBugCondition(resource_type, resource_tags) DO
  ASSERT create_alarms_original(resource_id, resource_type, resource_tags)
       = create_alarms_fixed(resource_id, resource_type, resource_tags)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain (ALB TG, EC2, RDS, ALB, NLB)
- It catches edge cases that manual unit tests might miss (e.g., missing `_lb_type` tag)
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for ALB TG and non-TG resources, then write property-based tests capturing that behavior.

**Test Cases**:
1. **ALB TG Preservation**: ALB TG(`_lb_type="application"`)에 `create_alarms_for_resource()` 호출 시 기존과 동일하게 4개 알람 생성 확인
2. **EC2/RDS Preservation**: EC2, RDS에 `create_alarms_for_resource()` 호출 시 기존과 동일한 알람 생성 확인
3. **ALB/NLB LB Preservation**: ALB, NLB LB 레벨에 `create_alarms_for_resource()` 호출 시 기존과 동일한 알람 생성 확인
4. **Sync Preservation**: ALB TG에 `sync_alarms_for_resource()` 호출 시 기존과 동일한 동기화 결과 확인

### Unit Tests

- `_get_alarm_defs("TG", {"_lb_type": "network"})` → 2개 알람 정의 반환 (HealthyHostCount, UnHealthyHostCount)
- `_get_alarm_defs("TG", {"_lb_type": "application"})` → 4개 알람 정의 반환
- `_get_alarm_defs("TG", {})` → 4개 알람 정의 반환 (기본값: ALB 동작)
- `_get_alarm_defs("TG", None)` → 4개 알람 정의 반환 (하위 호환)
- `_get_alarm_defs("EC2")` → 기존과 동일 (resource_tags 미전달)
- NLB TG `create_alarms_for_resource()` → 2개 알람만 생성
- ALB TG `create_alarms_for_resource()` → 4개 알람 생성
- NLB TG `sync_alarms_for_resource()` → 2개 메트릭만 동기화

### Property-Based Tests

- Generate random TG resources with `_lb_type` in `{"application", "network"}` and verify alarm count matches expected (2 for NLB, 4 for ALB)
- Generate random non-TG resources (EC2, RDS, ALB, NLB) and verify `_get_alarm_defs()` returns identical results with and without `resource_tags`
- Generate random resource configurations and verify preservation of alarm creation for non-buggy inputs

### Integration Tests

- NLB + TG 전체 플로우: ELB Collector가 `_lb_type="network"` 주입 → `create_alarms_for_resource()` → 2개 알람만 생성 확인
- ALB + TG 전체 플로우: ELB Collector가 `_lb_type="application"` 주입 → `create_alarms_for_resource()` → 4개 알람 생성 확인
- Daily Monitor 동기화 플로우: NLB TG에 대해 `sync_alarms_for_resource()` → `RequestCountPerTarget`/`TGResponseTime` 동기화 미시도 확인
