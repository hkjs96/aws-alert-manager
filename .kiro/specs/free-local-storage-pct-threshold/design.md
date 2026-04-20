# FreeLocalStorageGB 퍼센트 기반 임계치 Bugfix Design

## Overview

DocDB 및 Aurora RDS Provisioned 인스턴스의 FreeLocalStorageGB 알람 임계치가 인스턴스 실제 로컬 스토리지 용량을 반영하지 못하고 고정값(`HARDCODED_DEFAULTS["FreeLocalStorageGB"] = 10.0`)을 사용하는 버그를 수정한다.

수정 전략: `_resolve_free_memory_threshold()` 패턴을 그대로 따라 `_resolve_free_local_storage_threshold()` 함수를 `common/alarm_manager.py`에 추가하고, Collector(DocDB/Aurora RDS)에서 `_total_local_storage_bytes` 내부 태그를 설정한다. 로컬 스토리지 용량은 `describe_db_instance_classes` API의 `MaxStorageSize` 또는 `StorageInfo` 필드에서 조회한다.

## Glossary

- **Bug_Condition (C)**: FreeLocalStorageGB 알람 생성 시 인스턴스 실제 로컬 스토리지 용량을 무시하고 고정 10GB 임계치를 사용하는 조건
- **Property (P)**: FreeLocalStorageGB 알람 임계치가 인스턴스 로컬 스토리지 용량의 퍼센트(기본 20%)로 자동 계산되는 것
- **Preservation**: 기존 FreeMemoryGB 퍼센트 임계치, FreeLocalStorageGB 이외 메트릭, Serverless v2 동작, 태그 기반 GB 절대값 오버라이드가 변경되지 않는 것
- **`_resolve_free_local_storage_threshold()`**: `common/alarm_manager.py`에 새로 추가할 FreeLocalStorageGB 임계치 해석 함수 (3단계 폴백 체인)
- **`_resolve_free_memory_threshold()`**: `common/alarm_manager.py`의 기존 FreeMemoryGB 임계치 해석 함수 (참조 패턴)
- **`_total_local_storage_bytes`**: Collector에서 설정하는 내부 태그. 인스턴스의 로컬 스토리지 총 용량(bytes)
- **`_lookup_instance_class_local_storage()`**: `describe_db_instance_classes` API로 로컬 스토리지 용량을 조회하는 헬퍼 함수

## Bug Details

### Bug Condition

FreeLocalStorageGB 알람 생성 시 `_create_standard_alarm()` 및 관련 함수들이 `get_threshold(resource_tags, "FreeLocalStorageGB")` → `HARDCODED_DEFAULTS["FreeLocalStorageGB"] = 10.0`으로 폴백하여 모든 인스턴스에 동일한 10GB 고정 임계치를 적용한다. `_resolve_free_memory_threshold()` 같은 퍼센트 기반 해석 함수가 FreeLocalStorageGB에는 존재하지 않는다.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type { resource_type: string, metric: string, is_serverless: boolean }
  OUTPUT: boolean

  RETURN input.metric == "FreeLocalStorageGB"
         AND input.resource_type IN ["AuroraRDS", "DocDB"]
         AND input.is_serverless == false
         AND NOT hasTag(input.tags, "Threshold_FreeLocalStorageGB")
END FUNCTION
```

### Examples

- DocDB `db.t3.medium` (로컬 스토리지 ~20GB): 10GB 고정 임계치 → 스토리지 50% 사용 시 알람 (기대: 4GB = 20%)
- Aurora `db.r6g.4xlarge` (로컬 스토리지 수백 GB): 10GB 고정 임계치 → 스토리지 3~5%에서야 알람 (기대: 수십 GB = 20%)
- Aurora `db.r6g.large` (로컬 스토리지 ~50GB): 10GB 고정 임계치 → 20%에서 알람 (우연히 적절하지만 사양 변경 시 부정확)
- DocDB `db.r6g.xlarge` + `Threshold_FreeLocalStorageGB=5` 태그: 태그 값 5GB 사용 → 정상 (버그 조건 아님)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- `Threshold_FreeLocalStorageGB` 태그가 명시적으로 설정된 인스턴스는 3단계 폴백에서 GB 절대값으로 동작해야 한다
- Aurora Serverless v2 인스턴스는 FreeLocalStorageGB 알람을 생성하지 않아야 한다 (기존 `_get_aurora_alarm_defs()` 로직 유지)
- FreeLocalStorageGB 이외의 다른 메트릭(CPU, FreeMemoryGB, Connections 등)의 알람 생성 로직이 변경되지 않아야 한다
- 기존 `_resolve_free_memory_threshold()` 로직이 변경되지 않아야 한다
- 일반 RDS(비Aurora) 인스턴스는 FreeLocalStorageGB 알람을 생성하지 않아야 한다
- `Threshold_FreeLocalStorageGB=off` 태그 설정 시 해당 알람을 생성하지 않아야 한다

**Scope:**
이 수정은 다음에 한정된다:
- `common/alarm_manager.py`에 `_resolve_free_local_storage_threshold()` 함수 추가
- `common/alarm_manager.py`의 4개 함수(`_create_standard_alarm`, `_sync_standard_alarms`, `_create_single_alarm`, `_recreate_standard_alarm`)에서 FreeLocalStorageGB 분기 추가
- `common/collectors/rds.py`의 `_enrich_aurora_metadata()`에서 `_total_local_storage_bytes` 태그 설정
- `common/collectors/docdb.py`의 `collect_monitored_resources()`에서 `_total_local_storage_bytes` 태그 설정
- `common/__init__.py`의 `HARDCODED_DEFAULTS`에 `FreeLocalStoragePct` 기본값 추가
- `_parse_threshold_tags()`에서 `Threshold_FreeLocalStoragePct` 제외 추가

## Hypothesized Root Cause

FreeMemoryGB에는 `_resolve_free_memory_threshold()` 함수가 구현되어 인스턴스 클래스별 메모리 용량 기반 퍼센트 임계치를 자동 계산하지만, FreeLocalStorageGB에는 동일한 패턴이 적용되지 않았다.

1. **퍼센트 해석 함수 부재**: `_create_standard_alarm()` 등에서 FreeMemoryGB만 특별 분기(`if metric == "FreeMemoryGB"`)가 있고, FreeLocalStorageGB는 일반 `get_threshold()` 경로를 탄다. 이로 인해 `HARDCODED_DEFAULTS["FreeLocalStorageGB"] = 10.0` 고정값으로 폴백된다.

2. **로컬 스토리지 용량 태그 미설정**: Collector(`rds.py`, `docdb.py`)에서 `_total_memory_bytes`는 설정하지만 `_total_local_storage_bytes`는 설정하지 않는다. `describe_db_instance_classes` API 응답에 로컬 스토리지 정보(`MaxStorageSize` 또는 `StorageInfo`)가 포함되어 있지만 현재 코드에서 이를 조회하지 않는다.

3. **HARDCODED_DEFAULTS에 FreeLocalStoragePct 미등록**: `FreeMemoryPct: 20.0`은 등록되어 있지만 `FreeLocalStoragePct`는 등록되어 있지 않다.

## Correctness Properties

Property 1: Bug Condition - FreeLocalStorageGB 퍼센트 기반 임계치 적용

_For any_ DocDB 또는 Aurora RDS Provisioned 인스턴스 where `_total_local_storage_bytes` 내부 태그가 설정되어 있고 `Threshold_FreeLocalStorageGB` 태그가 없는 경우, `_resolve_free_local_storage_threshold()` SHALL 로컬 스토리지 총 용량의 20%(기본값)를 임계치로 계산하여 `(display_gb, cw_bytes)` 튜플을 반환해야 하며, `cw_bytes == 0.2 * _total_local_storage_bytes`이어야 한다.

**Validates: Requirements 2.1, 2.2, 2.3, 2.5**

Property 2: Preservation - 기존 메트릭 및 FreeLocalStorageGB GB 절대값 동작 보존

_For any_ 입력 where 메트릭이 FreeLocalStorageGB가 아니거나, `Threshold_FreeLocalStorageGB` 태그가 명시적으로 설정되어 있거나, Serverless v2이거나, 일반 RDS인 경우, 수정된 코드 SHALL 기존 코드와 동일한 임계치를 생성해야 하며, `_resolve_free_memory_threshold()` 동작이 변경되지 않아야 한다.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File 1**: `common/__init__.py`

**변경**: `HARDCODED_DEFAULTS`에 `FreeLocalStoragePct` 추가

```python
"FreeLocalStoragePct": 20.0,
```

---

**File 2**: `common/alarm_manager.py`

**Function**: `_resolve_free_local_storage_threshold(resource_tags)` 신규 추가

`_resolve_free_memory_threshold()` 패턴을 그대로 따르는 3단계 폴백 체인:

1. **1단계**: `Threshold_FreeLocalStoragePct` 태그 (명시적 퍼센트)
   - 유효성 검증: `0 < pct < 100`, 숫자 파싱 가능
   - `_total_local_storage_bytes` 필요. 없으면 warning 로그 + 3단계 폴백
2. **2단계**: `_total_local_storage_bytes` 존재 시 `HARDCODED_DEFAULTS["FreeLocalStoragePct"]` (기본 20%) 자동 적용
3. **3단계**: `get_threshold(resource_tags, "FreeLocalStorageGB")` GB 절대값 폴백

반환: `(display_threshold_gb, cw_threshold_bytes)` 튜플

**Pseudocode:**
```
FUNCTION _resolve_free_local_storage_threshold(resource_tags)
  INPUT: resource_tags dict
  OUTPUT: (display_gb: float, cw_bytes: float)

  total_storage_raw := resource_tags.get("_total_local_storage_bytes")

  // 1단계: 명시적 Threshold_FreeLocalStoragePct 태그
  pct_raw := resource_tags.get("Threshold_FreeLocalStoragePct")
  IF pct_raw IS NOT None THEN
    pct := parse_float(pct_raw)
    IF valid(pct) AND 0 < pct < 100 AND total_storage_raw IS NOT None THEN
      cw_bytes := (pct / 100) * float(total_storage_raw)
      display_gb := round(cw_bytes / 1073741824, 2)
      RETURN (display_gb, cw_bytes)
    ELSE
      log warning + fall through

  // 2단계: _total_local_storage_bytes 있으면 기본 퍼센트 자동 적용
  IF total_storage_raw IS NOT None THEN
    default_pct := HARDCODED_DEFAULTS.get("FreeLocalStoragePct", 20.0)
    cw_bytes := (default_pct / 100) * float(total_storage_raw)
    display_gb := round(cw_bytes / 1073741824, 2)
    RETURN (display_gb, cw_bytes)

  // 3단계: GB 절대값 폴백
  gb := get_threshold(resource_tags, "FreeLocalStorageGB")
  RETURN (gb, gb * 1073741824)
END FUNCTION
```

---

**Function**: `_create_standard_alarm()`, `_sync_standard_alarms()`, `_create_single_alarm()`, `_recreate_standard_alarm()` 수정

4개 함수 모두 동일한 패턴으로 FreeLocalStorageGB 분기 추가:

```python
# 기존
if metric == "FreeMemoryGB":
    threshold, cw_threshold = _resolve_free_memory_threshold(resource_tags)
else:
    threshold = get_threshold(resource_tags, metric)
    ...

# 수정 후
if metric == "FreeMemoryGB":
    threshold, cw_threshold = _resolve_free_memory_threshold(resource_tags)
elif metric == "FreeLocalStorageGB":
    threshold, cw_threshold = _resolve_free_local_storage_threshold(resource_tags)
else:
    threshold = get_threshold(resource_tags, metric)
    ...
```

---

**Function**: `_parse_threshold_tags()` 수정

`Threshold_FreeLocalStoragePct` 태그를 동적 알람 파싱에서 제외:

```python
# 기존
if key == "Threshold_FreeMemoryPct":
    continue

# 수정 후
if key in ("Threshold_FreeMemoryPct", "Threshold_FreeLocalStoragePct"):
    continue
```

---

**File 3**: `common/collectors/rds.py`

**Function**: `_enrich_aurora_metadata()` 수정 (Provisioned 분기)

Provisioned Aurora 인스턴스에서 `_total_local_storage_bytes` 내부 태그 설정:

- `_lookup_instance_class_local_storage(instance_class)` 헬퍼 호출
- `describe_db_instance_classes` API 응답에서 `MaxStorageSize` (GiB 단위) 조회
  - `MaxStorageSize`가 없거나 0이면 `StorageInfo` 필드의 `StorageSizeRange.Maximum` 조회
- GiB → bytes 변환 후 `_total_local_storage_bytes` 태그에 설정
- API 실패 시 warning 로그 + 태그 미설정 (3단계 폴백으로 진입)

**Function**: `_lookup_instance_class_local_storage(instance_class)` 신규 추가

`_lookup_instance_class_memory()` 패턴을 따르는 로컬 스토리지 조회 함수:

- 모듈 레벨 캐시: `_instance_class_local_storage_cache: dict[str, int | None]`
- 캐시 hit → 즉시 반환 (API 실패 None도 캐시)
- 캐시 miss → `describe_db_instance_classes` API 호출
- API 응답에서 로컬 스토리지 용량 추출 (GiB → bytes 변환)
- API 실패 시 None 반환 + warning 로그

**참고**: `_lookup_instance_class_memory()`가 이미 동일 API를 호출하므로, 가능하면 한 번의 API 호출로 메모리와 로컬 스토리지를 동시에 캐시하는 것을 고려한다. 단, 이는 리팩터링 단계에서 처리하고 초기 구현은 별도 캐시로 시작한다.

---

**File 4**: `common/collectors/docdb.py`

**Function**: `collect_monitored_resources()` 수정

DocDB 인스턴스에서 `_total_local_storage_bytes` 내부 태그 설정:

- `_lookup_instance_class_local_storage()` 함수를 `rds.py`에서 import하여 사용
- DocDB는 RDS와 동일한 `describe_db_instance_classes` API를 사용하므로 동일 함수 재사용 가능
- 인스턴스 클래스 정보는 `db["DBInstanceClass"]`에서 추출
- 조회 성공 시 `tags["_total_local_storage_bytes"] = str(local_storage_bytes)` 설정
- 조회 실패 시 warning 로그 + 태그 미설정

---

**File 5**: `common/__init__.py` (HARDCODED_DEFAULTS 업데이트만)

`FreeLocalStoragePct` 기본값 추가 (위 File 1에서 설명).

## Testing Strategy

### Validation Approach

테스트 전략은 두 단계로 진행한다: 먼저 수정 전 코드에서 버그를 재현하는 반례를 확인하고, 수정 후 코드에서 버그가 해결되었는지와 기존 동작이 보존되는지를 검증한다.

### Exploratory Bug Condition Checking

**Goal**: 수정 전 코드에서 FreeLocalStorageGB 알람이 인스턴스 로컬 스토리지 용량과 무관하게 고정 10GB 임계치를 사용하는 것을 확인하고, 근본 원인 분석을 검증한다.

**Test Plan**: `_create_standard_alarm()`에 다양한 로컬 스토리지 용량의 인스턴스를 전달하고, 생성되는 알람의 임계치가 항상 10GB(= 10737418240 bytes)인 것을 확인한다.

**Test Cases**:
1. **소형 DocDB 인스턴스 테스트**: `db.t3.medium` (로컬 스토리지 ~20GB)에서 FreeLocalStorageGB 알람 → 10GB 고정 임계치 확인 (수정 전 코드에서 실패)
2. **대형 Aurora 인스턴스 테스트**: `db.r6g.4xlarge` (로컬 스토리지 수백 GB)에서 FreeLocalStorageGB 알람 → 10GB 고정 임계치 확인 (수정 전 코드에서 실패)
3. **_resolve_free_local_storage_threshold 부재 확인**: `_create_standard_alarm()`에서 FreeLocalStorageGB 메트릭이 일반 `get_threshold()` 경로를 타는 것 확인

**Expected Counterexamples**:
- 모든 인스턴스에서 FreeLocalStorageGB 임계치가 10GB(= `HARDCODED_DEFAULTS` 값)로 동일
- 원인: `_resolve_free_local_storage_threshold()` 함수가 없고, `_total_local_storage_bytes` 태그도 설정되지 않음

### Fix Checking

**Goal**: `_total_local_storage_bytes`가 설정된 모든 인스턴스에서 FreeLocalStorageGB 임계치가 로컬 스토리지 용량의 퍼센트(기본 20%)로 계산되는지 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  tags := { "_total_local_storage_bytes": str(local_storage_bytes) }
  display_gb, cw_bytes := _resolve_free_local_storage_threshold(tags)
  ASSERT cw_bytes == 0.2 * local_storage_bytes
  ASSERT display_gb == round(cw_bytes / 1073741824, 2)
END FOR
```

### Preservation Checking

**Goal**: FreeLocalStorageGB 이외 메트릭, 기존 FreeMemoryGB 퍼센트 로직, Serverless v2 동작, GB 절대값 태그 오버라이드 등 기존 동작이 수정 후에도 동일하게 유지되는지 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT create_alarm_original(input) == create_alarm_fixed(input)
  // FreeMemoryGB 퍼센트 로직 불변
  ASSERT _resolve_free_memory_threshold(tags) == _resolve_free_memory_threshold_original(tags)
  // Threshold_FreeLocalStorageGB 태그 오버라이드 동작 유지
  IF hasTag(input.tags, "Threshold_FreeLocalStorageGB") THEN
    ASSERT threshold == float(tag_value)
END FOR
```

**Testing Approach**: Property-based testing은 preservation checking에 적합하다:
- 다양한 태그 조합에서 `_resolve_free_memory_threshold()` 결과가 수정 전후 동일한지 검증
- FreeLocalStorageGB 이외 메트릭의 `get_threshold()` 동작이 불변인지 검증
- `Threshold_FreeLocalStorageGB` 태그가 있을 때 GB 절대값이 3단계 폴백으로 정상 적용되는지 검증

**Test Cases**:
1. **FreeMemoryGB 보존**: `_resolve_free_memory_threshold()` 결과가 수정 전후 동일한지 확인
2. **Serverless v2 보존**: Serverless v2 인스턴스에서 FreeLocalStorageGB 알람이 생성되지 않는 것 확인
3. **GB 태그 오버라이드 보존**: `Threshold_FreeLocalStorageGB=5` 태그가 있을 때 3단계 폴백에서 5GB 절대값 사용 확인
4. **다른 메트릭 보존**: CPU, Connections 등 FreeLocalStorageGB 이외 메트릭의 임계치 불변 확인
5. **off 태그 보존**: `Threshold_FreeLocalStorageGB=off` 시 알람 미생성 확인

### Unit Tests

- `_resolve_free_local_storage_threshold()`: 3단계 폴백 체인 각 단계 검증
  - 1단계: `Threshold_FreeLocalStoragePct` 태그 + `_total_local_storage_bytes` → 퍼센트 계산
  - 2단계: `_total_local_storage_bytes`만 있을 때 → 기본 20% 적용
  - 3단계: 둘 다 없을 때 → `get_threshold()` GB 절대값 폴백
  - 엣지: 무효 pct 값, pct 범위 초과, `_total_local_storage_bytes` 없이 pct 태그만 있는 경우
- `_lookup_instance_class_local_storage()`: API 조회 성공, API 실패 시 None, 캐시 동작
- `_enrich_aurora_metadata()`: Provisioned 인스턴스에서 `_total_local_storage_bytes` 설정 확인
- DocDB `collect_monitored_resources()`: `_total_local_storage_bytes` 설정 확인
- `_parse_threshold_tags()`: `Threshold_FreeLocalStoragePct` 태그가 동적 알람에서 제외되는지 확인

### Property-Based Tests

- 임의의 `_total_local_storage_bytes` 값과 퍼센트 값에 대해 `_resolve_free_local_storage_threshold()`가 올바른 `(display_gb, cw_bytes)` 튜플을 반환하는지 검증
- 기존 `_resolve_free_memory_threshold()` 결과가 수정 전후 동일한지 다양한 태그 조합으로 검증
- FreeLocalStorageGB 이외 메트릭의 임계치가 수정 전후 동일한지 검증

### Integration Tests

- moto mock 환경에서 DocDB 인스턴스 수집 → `sync_alarms_for_resource()` 전체 흐름 테스트
- Aurora Provisioned 인스턴스에서 FreeLocalStorageGB 알람이 퍼센트 기반 임계치로 생성되는지 확인
- `Threshold_FreeLocalStoragePct=30` 태그가 있는 인스턴스에서 30% 임계치가 적용되는지 확인
