# Alarm Naming Format Update Bugfix Design

## Overview

알람 이름 포맷에 두 가지 가독성/식별성 문제가 있다:
1. direction과 threshold 사이에 공백이 없어 가독성이 떨어진다 (`>=80%` → `>= 80%`)
2. suffix의 resource_id에 `TagName:` 접두사가 없어 리소스 식별이 불명확하다 (`(i-1234)` → `(TagName: i-1234)`)

이 변경은 알람 이름을 생성하는 `_pretty_alarm_name()`, `_create_dynamic_alarm()`과 알람을 검색/파싱하는 `_find_alarms_for_resource()`, `_classify_alarm()`에 영향을 미친다. 기존 알람은 모두 삭제된 상태이므로 마이그레이션은 불필요하다.

## Glossary

- **Bug_Condition (C)**: 알람 이름이 생성/검색/파싱될 때 포맷이 올바르지 않은 조건 — direction-threshold 공백 누락 및 TagName: 접두사 누락
- **Property (P)**: 알람 이름이 `{direction} {threshold}{unit}` (공백 포함) 및 `(TagName: {short_id})` 포맷을 따르는 것
- **Preservation**: 255자 truncate 로직, Short_ID 추출, 레거시 알람 검색, AlarmDescription 메타데이터 등 기존 동작이 변경되지 않는 것
- **`_pretty_alarm_name()`**: `common/alarm_naming.py`의 표준/Disk 알람 이름 생성 함수
- **`_create_dynamic_alarm()`**: `common/alarm_builder.py`의 동적 태그 메트릭 알람 생성 함수
- **`_find_alarms_for_resource()`**: `common/alarm_search.py`의 리소스별 알람 검색 함수
- **`_classify_alarm()`**: `daily_monitor/lambda_handler.py`의 알람 이름 분류 함수
- **`_NEW_FORMAT_RE`**: `daily_monitor/lambda_handler.py`의 새 포맷 알람 이름 파싱 정규식
- **Short_ID**: ALB/NLB/TG ARN에서 추출한 `{name}/{hash}` 형태의 짧은 식별자

## Bug Details

### Bug Condition

알람 이름이 생성될 때 두 가지 포맷 문제가 발생한다:
1. `threshold_part`에서 direction과 threshold 사이에 공백이 없다 (`>=80` 대신 `>= 80`이어야 함)
2. suffix에서 resource_id에 `TagName:` 접두사가 없다 (`(i-1234)` 대신 `(TagName: i-1234)`이어야 함)

이로 인해 검색(`_find_alarms_for_resource`)과 파싱(`_classify_alarm`)도 연쇄적으로 영향을 받는다.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type AlarmNameOperation (create, search, or parse)
  OUTPUT: boolean

  IF input.operation == "create" THEN
    RETURN alarmName contains "{direction}{threshold}" (no space)
           OR alarmName suffix matches "({short_id})" (no TagName: prefix)
  ELSE IF input.operation == "search" THEN
    RETURN suffixPattern == "({short_id})" (missing TagName: prefix)
  ELSE IF input.operation == "parse" THEN
    RETURN regex captures "TagName: {resource_id}" instead of "{resource_id}"
  END IF
END FUNCTION
```

### Examples

- `_pretty_alarm_name("EC2", "i-abc123", "my-server", "CPU", 80.0)`:
  - 현재: `[EC2] my-server CPUUtilization >=80% (i-abc123)`
  - 기대: `[EC2] my-server CPUUtilization >= 80% (TagName: i-abc123)`

- `_pretty_alarm_name("ALB", "arn:...app/my-alb/abc123", "my-alb", "RequestCount", 10000.0)`:
  - 현재: `[ALB] my-alb RequestCount >=10000Count (my-alb/abc123)`
  - 기대: `[ALB] my-alb RequestCount >= 10000Count (TagName: my-alb/abc123)`

- `_create_dynamic_alarm(...)` with resource_id `i-abc123`:
  - 현재 suffix: `(i-abc123)`
  - 기대 suffix: `(TagName: i-abc123)`

- `_find_alarms_for_resource("i-abc123", "EC2")`:
  - 현재 suffix 매칭: `(i-abc123)` — 새 포맷 `(TagName: i-abc123)` 알람을 찾지 못함
  - 기대 suffix 매칭: `(TagName: i-abc123)`

- `_classify_alarm("[EC2] my-server CPUUtilization >= 80% (TagName: i-abc123)")`:
  - 현재 정규식 캡처: `TagName: i-abc123` (TagName: 접두사 포함)
  - 기대 캡처: `i-abc123` (순수 resource_id)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- 255자 초과 시 label → display_metric 순으로 truncate하는 로직이 유지되어야 한다
- ALB/NLB/TG suffix의 resource_id는 기존과 동일하게 Short_ID(`{name}/{hash}`)를 사용해야 한다 (TagName: 접두사만 추가)
- `_find_alarms_for_resource()`의 레거시 prefix 기반 검색(`resource_id` prefix)이 계속 동작해야 한다
- `_classify_alarm()`의 resource_type 추출 (`[EC2]`, `[RDS]` 등)은 기존과 동일하게 동작해야 한다
- `AlarmDescription`의 `resource_id` 필드에는 기존과 동일하게 전체 ARN/ID를 저장해야 한다

**Scope:**
알람 이름의 direction-threshold 공백과 suffix TagName: 접두사만 변경된다. 그 외 모든 동작(메타데이터 저장, 디멘션 빌드, 임계치 해석, 태그 파싱 등)은 완전히 영향 없다.

## Hypothesized Root Cause

이 버그는 초기 설계 시 포맷 요구사항이 불완전했기 때문에 발생했다:

1. **Direction-Threshold 공백 누락**: `_pretty_alarm_name()`의 `threshold_part` 변수가 `f" {direction}{thr_str}{unit} "`로 구성되어 direction과 threshold 사이에 공백이 없다. `_create_dynamic_alarm()`의 `threshold_part`도 동일한 패턴이다.

2. **TagName: 접두사 누락**: `_pretty_alarm_name()`의 `suffix` 변수가 `f"({short_id})"`로 구성되어 TagName: 접두사가 없다. `_create_dynamic_alarm()`도 동일하다.

3. **검색 suffix 불일치**: `_find_alarms_for_resource()`의 `suffixes` 집합이 `f"({short_id})"`를 사용하여 새 포맷 `(TagName: {short_id})` 알람을 매칭하지 못한다.

4. **정규식 캡처 그룹 불일치**: `_NEW_FORMAT_RE`가 `\((.+)\)$`로 괄호 안 전체를 캡처하므로, `(TagName: i-abc123)`에서 `TagName: i-abc123`이 캡처된다. `TagName: ` 접두사를 제거하는 로직이 필요하다.

## Correctness Properties

Property 1: Bug Condition - Direction-Threshold 공백 및 TagName: 접두사

_For any_ 유효한 resource_type, resource_id, resource_name, metric, threshold 조합에 대해, 수정된 `_pretty_alarm_name()` 함수는 direction과 threshold 사이에 공백을 포함하고 (`>= 80`, `< 2` 등), suffix가 `(TagName: {short_id})` 포맷을 따르는 알람 이름을 생성해야 한다 (SHALL).

**Validates: Requirements 2.1, 2.2**

Property 2: Preservation - 255자 Truncate 및 Short_ID 보존

_For any_ 유효한 입력 조합에 대해, 수정된 `_pretty_alarm_name()` 함수는 255자 제한을 준수하고, ALB/NLB/TG 리소스의 Short_ID 추출이 기존과 동일하며, truncate 순서(label → display_metric)가 보존되어야 한다 (SHALL).

**Validates: Requirements 3.1, 3.2**

Property 3: Bug Condition - 동적 알람 TagName: 접두사

_For any_ 유효한 동적 알람 생성 입력에 대해, 수정된 `_create_dynamic_alarm()` 함수는 suffix가 `(TagName: {short_id})` 포맷을 따르고 direction-threshold 사이에 공백을 포함하는 알람 이름을 생성해야 한다 (SHALL).

**Validates: Requirements 2.3**

Property 4: Bug Condition - 알람 검색 suffix 매칭

_For any_ resource_id와 resource_type 조합에 대해, 수정된 `_find_alarms_for_resource()` 함수는 `(TagName: {short_id})` suffix를 가진 알람을 올바르게 검색해야 한다 (SHALL).

**Validates: Requirements 2.4**

Property 5: Bug Condition - 알람 파싱 resource_id 추출

_For any_ 새 포맷 알람 이름 `[{type}] ... (TagName: {resource_id})`에 대해, 수정된 `_classify_alarm()` 함수는 `TagName: ` 접두사를 제외한 순수 resource_id를 추출해야 한다 (SHALL).

**Validates: Requirements 2.5**

Property 6: Preservation - 레거시 검색 및 resource_type 파싱 보존

_For any_ 레거시 포맷 알람 이름에 대해, 수정된 코드는 레거시 prefix 검색과 resource_type 추출이 기존과 동일하게 동작해야 한다 (SHALL). AlarmDescription의 resource_id 필드도 변경되지 않아야 한다.

**Validates: Requirements 3.3, 3.4, 3.5**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `common/alarm_naming.py`

**Function**: `_pretty_alarm_name()`

**Specific Changes**:
1. **threshold_part 공백 추가**: `f" {direction}{thr_str}{unit} "` → `f" {direction} {thr_str}{unit} "` (direction 뒤에 공백 추가)
2. **suffix TagName: 접두사 추가**: `f"({short_id})"` → `f"(TagName: {short_id})"`

---

**File**: `common/alarm_builder.py`

**Function**: `_create_dynamic_alarm()`

**Specific Changes**:
1. **threshold_part 공백 추가**: `f" {direction}{thr_str} "` → `f" {direction} {thr_str} "` (direction 뒤에 공백 추가)
2. **suffix TagName: 접두사 추가**: `f"({short_id})"` → `f"(TagName: {short_id})"`

---

**File**: `common/alarm_search.py`

**Function**: `_find_alarms_for_resource()`

**Specific Changes**:
1. **suffix 매칭 업데이트**: `f"({short_id})"` → `f"(TagName: {short_id})"` (suffixes 집합의 새 포맷 항목)
2. 레거시 Full_ARN 호환 suffix도 동일하게 업데이트: `f"({resource_id})"` → `f"(TagName: {resource_id})"`

---

**File**: `daily_monitor/lambda_handler.py`

**Function**: `_classify_alarm()` / `_NEW_FORMAT_RE`

**Specific Changes**:
1. **정규식 업데이트**: `r"^\[(\w+)\]\s.*\((.+)\)$"` → `r"^\[(\w+)\]\s.*\(TagName:\s(.+)\)$"` (TagName: 접두사를 매칭하되 캡처 그룹에서 제외)

---

**File**: `.kiro/steering/alarm-rules.md`

**Specific Changes**:
1. **포맷 가이드 업데이트**: `{direction}{threshold}{unit}` → `{direction} {threshold}{unit}` 및 `({resource_id})` → `(TagName: {resource_id})`

## Testing Strategy

### Validation Approach

테스트 전략은 두 단계로 진행한다: 먼저 수정 전 코드에서 버그를 재현하는 counterexample을 확인하고, 수정 후 fix checking과 preservation checking을 수행한다.

### Exploratory Bug Condition Checking

**Goal**: 수정 전 코드에서 버그를 재현하여 root cause를 확인/반박한다.

**Test Plan**: `_pretty_alarm_name()`과 `_create_dynamic_alarm()`의 출력을 검사하여 direction-threshold 공백 누락과 TagName: 접두사 누락을 확인한다.

**Test Cases**:
1. **Pretty Name 공백 테스트**: `_pretty_alarm_name("EC2", "i-abc", "srv", "CPU", 80.0)` 호출 후 `>=80` 패턴 존재 확인 (수정 전 코드에서 실패)
2. **Pretty Name TagName 테스트**: 동일 호출 후 suffix가 `(i-abc)`인지 확인 (수정 전 코드에서 실패)
3. **Dynamic Alarm TagName 테스트**: `_create_dynamic_alarm()` 호출 후 AlarmName suffix 확인 (수정 전 코드에서 실패)
4. **Search Suffix 테스트**: 새 포맷 알람을 등록하고 `_find_alarms_for_resource()` 검색 결과 확인 (수정 전 코드에서 실패)

**Expected Counterexamples**:
- `_pretty_alarm_name()` 출력에 `>=80%` (공백 없음) 및 `(i-abc)` (TagName: 없음) 패턴 발견
- `_find_alarms_for_resource()`가 `(TagName: ...)` suffix 알람을 찾지 못함

### Fix Checking

**Goal**: 버그 조건에 해당하는 모든 입력에 대해 수정된 함수가 올바른 동작을 하는지 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := _pretty_alarm_name_fixed(input) OR _create_dynamic_alarm_fixed(input)
  ASSERT result contains "{direction} {threshold}" (with space)
  ASSERT result ends with "(TagName: {short_id})"
END FOR
```

### Preservation Checking

**Goal**: 버그 조건에 해당하지 않는 모든 입력에 대해 수정된 함수가 기존과 동일한 결과를 생성하는지 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT len(_pretty_alarm_name_fixed(input)) <= 255
  ASSERT truncate_order_preserved(input)  -- label → display_metric 순서
  ASSERT short_id_extraction_unchanged(input)
  ASSERT legacy_search_works(input)
  ASSERT alarm_description_unchanged(input)
END FOR
```

**Testing Approach**: Property-based testing은 preservation checking에 적합하다:
- 다양한 길이의 label/display_metric 조합으로 truncate 동작 검증
- 다양한 resource_type/resource_id 조합으로 Short_ID 추출 검증
- 랜덤 알람 이름으로 _classify_alarm() 파싱 검증

**Test Cases**:
1. **Truncate 보존**: 긴 label/display_metric 조합에서 255자 제한 준수 및 truncate 순서 확인
2. **Short_ID 보존**: ALB/NLB/TG ARN에서 Short_ID 추출이 변경되지 않는지 확인
3. **레거시 검색 보존**: 레거시 포맷 알람이 여전히 검색되는지 확인
4. **AlarmDescription 보존**: 메타데이터 JSON의 resource_id 필드가 전체 ARN/ID인지 확인

### Unit Tests

- `_pretty_alarm_name()` direction-threshold 공백 포함 확인 (각 direction: `>=`, `<`)
- `_pretty_alarm_name()` suffix `(TagName: {short_id})` 포맷 확인 (EC2, RDS, ALB, NLB, TG)
- `_create_dynamic_alarm()` suffix 및 공백 확인
- `_find_alarms_for_resource()` 새 포맷 suffix 매칭 확인
- `_classify_alarm()` TagName: 접두사 제거 후 resource_id 추출 확인
- 255자 truncate 경계 케이스 (label만 truncate, label+metric 모두 truncate)

### Property-Based Tests

- 랜덤 resource_type/resource_id/resource_name/metric/threshold 조합으로 `_pretty_alarm_name()` 출력이 항상 `{direction} {threshold}` 공백과 `(TagName: {short_id})` suffix를 포함하는지 검증
- 랜덤 입력으로 `_pretty_alarm_name()` 출력이 항상 255자 이하인지 검증 (preservation)
- 랜덤 새 포맷 알람 이름으로 `_classify_alarm()` 파싱이 올바른 resource_type과 resource_id를 추출하는지 검증

### Integration Tests

- 전체 알람 생성 → 검색 → 파싱 플로우에서 새 포맷이 일관되게 적용되는지 확인
- 동적 알람 생성 후 `_find_alarms_for_resource()`로 검색 가능한지 확인
- daily_monitor의 `_classify_alarm()`이 새 포맷 알람을 올바르게 분류하는지 확인
