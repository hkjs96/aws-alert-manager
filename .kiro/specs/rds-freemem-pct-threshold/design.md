# RDS FreeMemory 퍼센트 임계치 동적 메모리 조회 Bugfix Design

## Overview

`_INSTANCE_CLASS_MEMORY_MAP` 정적 매핑에 없는 RDS/Aurora 인스턴스 클래스에서 `_total_memory_bytes`가 설정되지 않아, `_resolve_free_memory_threshold()`가 3단계 폴백(고정 2GB)으로 진입하는 버그를 수정한다.

수정 전략: `_enrich_aurora_metadata()`와 `_enrich_rds_memory()`에서 정적 매핑 miss 시 `describe_db_instance_classes` API를 호출하여 해당 인스턴스 클래스의 실제 메모리 용량을 동적으로 조회하고, 조회 결과를 모듈 레벨 캐시에 저장하여 동일 클래스의 반복 API 호출을 방지한다.

## Glossary

- **Bug_Condition (C)**: 인스턴스 클래스가 `_INSTANCE_CLASS_MEMORY_MAP`에 없어서 `_total_memory_bytes`가 설정되지 않는 조건
- **Property (P)**: 매핑에 없는 인스턴스 클래스에 대해 `describe_db_instance_classes` API로 메모리를 동적 조회하여 `_total_memory_bytes`를 설정하고, 퍼센트 기반 임계치(기본 20%)가 적용되는 것
- **Preservation**: 기존 정적 매핑에 있는 인스턴스 클래스, Serverless v2, 태그 기반 임계치 오버라이드, FreeMemoryGB 이외 메트릭의 동작이 변경되지 않는 것
- **`_INSTANCE_CLASS_MEMORY_MAP`**: `common/collectors/rds.py`의 인스턴스 클래스 → 메모리 bytes 정적 매핑 딕셔너리
- **`_resolve_free_memory_threshold()`**: `common/alarm_manager.py`의 FreeMemoryGB 임계치 해석 함수 (3단계 폴백 체인)
- **`_enrich_aurora_metadata()`**: `common/collectors/rds.py`의 Aurora 인스턴스 메타데이터 enrichment 함수
- **`_enrich_rds_memory()`**: `common/collectors/rds.py`의 일반 RDS 인스턴스 메모리 태그 설정 함수

## Bug Details

### Bug Condition

`_INSTANCE_CLASS_MEMORY_MAP`에 등록되지 않은 인스턴스 클래스(예: db.r5.large, db.r6i.large, db.m6i.xlarge, db.t3.nano, db.r5.xlarge 등)를 사용하는 RDS/Aurora 프로비저닝 인스턴스에서 `_total_memory_bytes` 내부 태그가 설정되지 않는다. 이로 인해 `_resolve_free_memory_threshold()`가 2단계(퍼센트 기반)를 건너뛰고 3단계(GB 절대값 폴백, 기본 2GB)로 진입한다.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type { instance_class: string, is_serverless: boolean }
  OUTPUT: boolean

  RETURN input.is_serverless == false
         AND input.instance_class NOT IN _INSTANCE_CLASS_MEMORY_MAP
         AND input.instance_class starts with "db."
         AND input.instance_class != "db.serverless"
END FUNCTION
```

### Examples

- `db.r5.large` (16GB RAM): 매핑에 없음 → `_total_memory_bytes` 미설정 → 2GB 고정 임계치 → 메모리의 12.5%에서야 알람 발생 (기대: 3.2GB = 20%)
- `db.r6i.large` (16GB RAM): 매핑에 없음 → 2GB 고정 임계치 → 동일 문제
- `db.m6i.xlarge` (16GB RAM): 매핑에 없음 → 2GB 고정 임계치
- `db.t3.nano` (0.5GB RAM): 매핑에 없음 → 2GB 고정 임계치 → FreeableMemory가 절대 2GB를 초과할 수 없으므로 영구 ALARM
- `db.r6g.large` (16GB RAM): 매핑에 **있음** → `_total_memory_bytes` = 16GB → 3.2GB 임계치 (정상)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- `_INSTANCE_CLASS_MEMORY_MAP`에 이미 존재하는 인스턴스 클래스는 정적 매핑 값을 우선 사용하고 API 호출을 하지 않아야 한다
- `Threshold_FreeMemoryGB` 태그가 명시적으로 설정된 인스턴스는 태그 값을 GB 절대값 임계치로 우선 사용해야 한다
- `Threshold_FreeMemoryPct` 태그가 명시적으로 설정된 인스턴스는 태그 값을 퍼센트 기반 임계치로 최우선 사용해야 한다
- Aurora Serverless v2 인스턴스(`_is_serverless_v2` = "true")는 퍼센트 기반 임계치를 적용하지 않고 GB 절대값만 사용해야 한다
- `_resolve_free_memory_threshold()`의 3단계 폴백 체인 우선순위(Threshold_FreeMemoryPct 태그 → 기본 퍼센트 20% → GB 절대값)가 유지되어야 한다
- FreeMemoryGB 이외의 다른 메트릭(CPU, Connections, FreeStorageGB 등)의 알람 생성 로직이 변경되지 않아야 한다

**Scope:**
이 수정은 `common/collectors/rds.py`의 `_enrich_aurora_metadata()`와 `_enrich_rds_memory()` 함수에서 정적 매핑 miss 시 동적 조회를 추가하는 것에 한정된다. `_resolve_free_memory_threshold()` 함수 자체는 변경하지 않는다.

## Hypothesized Root Cause

`_INSTANCE_CLASS_MEMORY_MAP`이 수동으로 관리되는 정적 딕셔너리이며, AWS가 지속적으로 새 인스턴스 클래스를 출시하기 때문에 매핑이 불완전할 수밖에 없다.

1. **불완전한 정적 매핑**: 현재 매핑에는 T3/T4g, M5/M6g/M7g, R6g/R7g 계열만 포함되어 있다. R5, R6i, M5d, M6i, T2, X2g 등 다수의 인스턴스 패밀리가 누락되어 있다.

2. **폴백 경로의 설계 의도 불일치**: `_enrich_aurora_metadata()`와 `_enrich_rds_memory()`에서 매핑 miss 시 warning 로그만 남기고 `_total_memory_bytes`를 설정하지 않는다. 이는 `_resolve_free_memory_threshold()`의 2단계(퍼센트 기반)를 완전히 우회하게 만든다.

3. **동적 조회 메커니즘 부재**: AWS RDS API(`describe_db_instance_classes`)를 통해 인스턴스 클래스의 메모리 용량을 런타임에 조회할 수 있지만, 현재 코드에는 이 폴백 메커니즘이 구현되어 있지 않다.


## Correctness Properties

Property 1: Bug Condition - 매핑에 없는 인스턴스 클래스의 동적 메모리 조회

_For any_ RDS/Aurora 프로비저닝 인스턴스 where 인스턴스 클래스가 `_INSTANCE_CLASS_MEMORY_MAP`에 존재하지 않고 `describe_db_instance_classes` API가 정상 응답하는 경우, enrichment 함수 SHALL `_total_memory_bytes` 내부 태그를 API 응답의 메모리 값으로 설정하고, 이후 `_resolve_free_memory_threshold()`가 2단계(퍼센트 기반, 기본 20%)를 적용하여 `실제 메모리 * 0.2`를 임계치로 계산해야 한다.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

Property 2: Preservation - 정적 매핑 및 기존 임계치 로직 보존

_For any_ 입력 where 인스턴스 클래스가 `_INSTANCE_CLASS_MEMORY_MAP`에 이미 존재하거나, Serverless v2이거나, `Threshold_FreeMemoryGB`/`Threshold_FreeMemoryPct` 태그가 명시적으로 설정된 경우, 수정된 코드 SHALL 기존 코드와 동일한 `_total_memory_bytes` 값과 동일한 임계치를 생성해야 하며, `describe_db_instance_classes` API 호출이 발생하지 않아야 한다.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `common/collectors/rds.py`

**Function**: `_enrich_aurora_metadata()`, `_enrich_rds_memory()`

**Specific Changes**:

1. **동적 메모리 조회 헬퍼 함수 추가**: `_lookup_instance_class_memory(instance_class: str) -> int | None`
   - `_INSTANCE_CLASS_MEMORY_MAP`에서 먼저 조회
   - 없으면 `describe_db_instance_classes` API 호출하여 메모리 용량 조회
   - API 응답에서 `DBInstanceClassInfo.Memory` (MiB 단위) → bytes 변환
   - 결과를 모듈 레벨 캐시 딕셔너리(`_instance_class_memory_cache`)에 저장하여 동일 클래스 반복 호출 방지
   - API 실패 시 `None` 반환 + warning 로그

2. **`_enrich_aurora_metadata()` 수정**: Provisioned 분기에서 `_INSTANCE_CLASS_MEMORY_MAP.get()` 대신 `_lookup_instance_class_memory()` 호출

3. **`_enrich_rds_memory()` 수정**: `_INSTANCE_CLASS_MEMORY_MAP.get()` 대신 `_lookup_instance_class_memory()` 호출

4. **캐시 관리**: `_instance_class_memory_cache: dict[str, int | None]` 모듈 레벨 딕셔너리 추가. API 실패 결과도 캐시하여 동일 클래스에 대한 반복 실패 API 호출 방지. 테스트 시 `_instance_class_memory_cache.clear()`로 리셋 가능.

5. **API 호출 최적화**: `describe_db_instance_classes`는 `DBInstanceClass` 파라미터로 단일 클래스만 조회 가능. paginator 불필요. 응답의 `DBInstanceClasses[0].Memory` (MiB 단위)를 bytes로 변환 (`* 1024 * 1024`).

## Testing Strategy

### Validation Approach

테스트 전략은 두 단계로 진행한다: 먼저 수정 전 코드에서 버그를 재현하는 반례를 확인하고, 수정 후 코드에서 버그가 해결되었는지와 기존 동작이 보존되는지를 검증한다.

### Exploratory Bug Condition Checking

**Goal**: 수정 전 코드에서 매핑에 없는 인스턴스 클래스가 `_total_memory_bytes` 미설정으로 이어지는 것을 확인하고, 근본 원인 분석을 검증한다.

**Test Plan**: `_enrich_aurora_metadata()`와 `_enrich_rds_memory()`에 매핑에 없는 인스턴스 클래스를 전달하고, `_total_memory_bytes`가 태그에 설정되지 않는 것을 확인한다. 이후 `_resolve_free_memory_threshold()`에 해당 태그를 전달하여 3단계 폴백(2GB)이 발생하는 것을 확인한다.

**Test Cases**:
1. **매핑 누락 인스턴스 테스트**: `db.r5.large`로 `_enrich_rds_memory()` 호출 → `_total_memory_bytes` 미설정 확인 (수정 전 코드에서 실패)
2. **Aurora 매핑 누락 테스트**: `db.r6i.large`로 `_enrich_aurora_metadata()` 호출 → `_total_memory_bytes` 미설정 확인 (수정 전 코드에서 실패)
3. **소형 인스턴스 폴백 테스트**: `db.t3.nano`(0.5GB)에서 `_resolve_free_memory_threshold()` → 2GB 폴백 확인 (수정 전 코드에서 실패)
4. **대형 인스턴스 폴백 테스트**: `db.r5.xlarge`(32GB)에서 `_resolve_free_memory_threshold()` → 2GB 폴백 확인 (수정 전 코드에서 실패)

**Expected Counterexamples**:
- `_total_memory_bytes`가 태그에 없어서 `_resolve_free_memory_threshold()`가 3단계 폴백으로 진입
- 원인: `_INSTANCE_CLASS_MEMORY_MAP`에 해당 인스턴스 클래스가 없고, 동적 조회 메커니즘이 없음

### Fix Checking

**Goal**: 매핑에 없는 모든 인스턴스 클래스에 대해 `describe_db_instance_classes` API로 메모리를 동적 조회하고, 퍼센트 기반 임계치가 올바르게 적용되는지 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  tags := {}
  enrich_function(db_instance_with(input.instance_class), tags)
  ASSERT "_total_memory_bytes" IN tags
  ASSERT int(tags["_total_memory_bytes"]) == api_response_memory_bytes
  display_gb, cw_bytes := _resolve_free_memory_threshold(tags)
  ASSERT cw_bytes == 0.2 * int(tags["_total_memory_bytes"])
END FOR
```

### Preservation Checking

**Goal**: 정적 매핑에 있는 인스턴스 클래스, Serverless v2, 태그 오버라이드 등 기존 동작이 수정 후에도 동일하게 유지되는지 검증한다.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  tags_original := enrich_original(input)
  tags_fixed := enrich_fixed(input)
  ASSERT tags_original["_total_memory_bytes"] == tags_fixed["_total_memory_bytes"]
  ASSERT _resolve_free_memory_threshold(tags_original) == _resolve_free_memory_threshold(tags_fixed)
  ASSERT describe_db_instance_classes NOT called  // 정적 매핑 hit 시 API 호출 없음
END FOR
```

**Testing Approach**: Property-based testing은 preservation checking에 적합하다:
- 정적 매핑에 있는 인스턴스 클래스를 무작위로 선택하여 API 호출 없이 동일한 결과가 나오는지 검증
- 다양한 태그 조합(Threshold_FreeMemoryGB, Threshold_FreeMemoryPct, _is_serverless_v2)에서 기존 동작 보존 확인
- 엣지 케이스(빈 태그, 잘못된 태그 값 등)에서도 기존 폴백 동작이 유지되는지 확인

**Test Cases**:
1. **정적 매핑 보존**: `_INSTANCE_CLASS_MEMORY_MAP`에 있는 인스턴스 클래스에 대해 수정 전후 동일한 `_total_memory_bytes` 설정 확인
2. **Serverless v2 보존**: `_is_serverless_v2=true` 인스턴스에서 퍼센트 기반 스킵 동작 유지 확인
3. **태그 오버라이드 보존**: `Threshold_FreeMemoryGB`/`Threshold_FreeMemoryPct` 태그가 있을 때 기존 우선순위 유지 확인
4. **다른 메트릭 보존**: CPU, Connections 등 FreeMemoryGB 이외 메트릭의 `get_threshold()` 동작 불변 확인

### Unit Tests

- `_lookup_instance_class_memory()`: 정적 매핑 hit, API 동적 조회 성공, API 실패 시 None 반환, 캐시 동작
- `_enrich_aurora_metadata()`: 매핑에 없는 인스턴스 클래스에서 동적 조회 후 `_total_memory_bytes` 설정
- `_enrich_rds_memory()`: 매핑에 없는 인스턴스 클래스에서 동적 조회 후 `_total_memory_bytes` 설정
- API 실패 시 warning 로그 + `_total_memory_bytes` 미설정 (기존 폴백 유지)

### Property-Based Tests

- 임의의 인스턴스 클래스 문자열에 대해 `_lookup_instance_class_memory()`가 정적 매핑 또는 API 조회 중 하나를 통해 결과를 반환하거나, 둘 다 실패 시 None을 반환하는지 검증
- 정적 매핑에 있는 인스턴스 클래스를 무작위 선택하여 API 호출 없이 동일한 메모리 값이 반환되는지 검증
- 다양한 태그 조합에서 `_resolve_free_memory_threshold()`의 폴백 체인 우선순위가 유지되는지 검증

### Integration Tests

- moto mock 환경에서 `collect_monitored_resources()` → `sync_alarms_for_resource()` 전체 흐름 테스트
- 매핑에 없는 인스턴스 클래스의 RDS 인스턴스가 퍼센트 기반 FreeMemoryGB 알람을 생성하는지 확인
- 매핑에 있는 인스턴스 클래스와 없는 인스턴스 클래스가 혼재된 환경에서 각각 올바른 임계치가 적용되는지 확인
