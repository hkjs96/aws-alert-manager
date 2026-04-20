# Bugfix Requirements Document

## Introduction

RDS/Aurora의 FreeMemoryGB 알람 임계치가 인스턴스 실제 메모리 용량을 반영하지 못하고 고정값(2GB)으로 폴백되는 버그를 수정한다.

`_resolve_free_memory_threshold()` 함수는 `_total_memory_bytes` 내부 태그가 존재할 때 퍼센트 기반(기본 20%) 임계치를 자동 계산하도록 이미 구현되어 있다. 그러나 `_INSTANCE_CLASS_MEMORY_MAP`이 불완전하여 많은 인스턴스 클래스에서 `_total_memory_bytes`가 설정되지 않고, 결과적으로 `HARDCODED_DEFAULTS["FreeMemoryGB"] = 2.0` 고정값으로 폴백된다.

이로 인해:
- 소형 인스턴스(예: db.t3.micro, 1GB RAM)에 2GB 임계치가 걸려 항상 알람이 울림
- 대형 인스턴스(예: db.r6g.xlarge, 32GB RAM)에 2GB 임계치가 걸려 메모리의 6%에서야 감지되어 너무 늦게 알람 발생

RDS와 AuroraRDS 모두 동일한 `_INSTANCE_CLASS_MEMORY_MAP`과 `_resolve_free_memory_threshold()`를 공유하므로 양쪽 모두 영향을 받는다.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN RDS 또는 AuroraRDS 인스턴스의 클래스가 `_INSTANCE_CLASS_MEMORY_MAP`에 존재하지 않는 경우(예: db.r5.large, db.r6i.large, db.m6i.xlarge, db.t3.nano 등) THEN the system은 `_total_memory_bytes` 내부 태그를 설정하지 않고 warning 로그만 남긴다

1.2 WHEN `_total_memory_bytes`가 설정되지 않은 인스턴스에 대해 FreeMemoryGB 알람을 생성할 때 THEN the system은 `_resolve_free_memory_threshold()` 3단계(GB 절대값 폴백)로 진입하여 `HARDCODED_DEFAULTS["FreeMemoryGB"] = 2.0` 고정값을 임계치로 사용한다

1.3 WHEN 총 메모리가 2GB 미만인 소형 인스턴스(예: db.t3.micro 1GB, db.t4g.micro 1GB)에 2GB 고정 임계치가 적용될 때 THEN the system은 FreeableMemory가 절대로 2GB를 초과할 수 없으므로 알람이 영구적으로 ALARM 상태에 머문다

1.4 WHEN 총 메모리가 32GB 이상인 대형 인스턴스(예: db.r6g.xlarge 32GB)에 2GB 고정 임계치가 적용될 때 THEN the system은 메모리의 93.75%가 사용된 후에야 알람이 발생하여 메모리 압박을 너무 늦게 감지한다

1.5 WHEN `_INSTANCE_CLASS_MEMORY_MAP`에 존재하는 인스턴스 클래스 중 일부(db.t3.micro 등)의 메모리 값이 AWS 실제 사양과 다를 수 있는 경우 THEN the system은 잘못된 메모리 용량 기반으로 퍼센트 임계치를 계산하여 부정확한 알람 임계치를 생성한다

### Expected Behavior (Correct)

2.1 WHEN RDS 또는 AuroraRDS 인스턴스의 클래스가 `_INSTANCE_CLASS_MEMORY_MAP`에 존재하지 않는 경우 THEN the system SHALL `describe_db_instance_classes` API(또는 `describe_orderable_db_instance_options` API)를 통해 해당 인스턴스 클래스의 실제 메모리 용량을 동적으로 조회하고 `_total_memory_bytes`를 설정해야 한다

2.2 WHEN `_total_memory_bytes`가 정상적으로 설정된 인스턴스에 대해 FreeMemoryGB 알람을 생성할 때 THEN the system SHALL `_resolve_free_memory_threshold()` 2단계(기본 퍼센트 20%)를 적용하여 `실제 메모리 * 0.2`를 임계치로 자동 계산해야 한다

2.3 WHEN 소형 인스턴스(예: db.t3.micro, 1GB RAM)에 퍼센트 기반 임계치가 적용될 때 THEN the system SHALL 임계치를 0.2GB(= 1GB * 20%)로 설정하여 적절한 수준에서 알람이 발생해야 한다

2.4 WHEN 대형 인스턴스(예: db.r6g.xlarge, 32GB RAM)에 퍼센트 기반 임계치가 적용될 때 THEN the system SHALL 임계치를 6.4GB(= 32GB * 20%)로 설정하여 적절한 수준에서 알람이 발생해야 한다

2.5 WHEN `describe_db_instance_classes` API 호출이 실패하고 `_INSTANCE_CLASS_MEMORY_MAP`에도 해당 클래스가 없는 경우 THEN the system SHALL warning 로그를 남기고 기존 GB 절대값 폴백(`HARDCODED_DEFAULTS["FreeMemoryGB"]`)을 사용해야 한다

2.6 WHEN `_INSTANCE_CLASS_MEMORY_MAP`의 기존 엔트리 메모리 값이 AWS 실제 사양과 일치하도록 THEN the system SHALL 정적 매핑 테이블의 메모리 값을 AWS 공식 사양 기준으로 검증 및 수정해야 한다

### Unchanged Behavior (Regression Prevention)

3.1 WHEN 인스턴스에 `Threshold_FreeMemoryGB` 태그가 명시적으로 설정되어 있는 경우 THEN the system SHALL CONTINUE TO 태그 값을 GB 절대값 임계치로 우선 사용해야 한다 (기존 태그 우선순위 유지)

3.2 WHEN 인스턴스에 `Threshold_FreeMemoryPct` 태그가 명시적으로 설정되어 있는 경우 THEN the system SHALL CONTINUE TO 태그 값을 퍼센트 기반 임계치로 최우선 사용해야 한다

3.3 WHEN Aurora Serverless v2 인스턴스(`_is_serverless_v2` = "true")에 대해 FreeMemoryGB 알람을 생성할 때 THEN the system SHALL CONTINUE TO 퍼센트 기반 임계치를 적용하지 않고 GB 절대값만 사용해야 한다 (ACU 동적 변동 특성)

3.4 WHEN `_resolve_free_memory_threshold()`의 기존 3단계 폴백 체인(Threshold_FreeMemoryPct 태그 → 기본 퍼센트 20% → GB 절대값)이 동작할 때 THEN the system SHALL CONTINUE TO 동일한 우선순위 순서를 유지해야 한다

3.5 WHEN FreeMemoryGB 이외의 다른 메트릭(CPU, Connections, FreeStorageGB 등)에 대해 알람을 생성할 때 THEN the system SHALL CONTINUE TO 기존 `get_threshold()` 로직(태그 → 환경변수 → HARDCODED_DEFAULTS)을 변경 없이 사용해야 한다

3.6 WHEN `_INSTANCE_CLASS_MEMORY_MAP`에 이미 존재하는 인스턴스 클래스에 대해 메모리를 조회할 때 THEN the system SHALL CONTINUE TO 정적 매핑 테이블의 값을 우선 사용하고 불필요한 API 호출을 하지 않아야 한다
