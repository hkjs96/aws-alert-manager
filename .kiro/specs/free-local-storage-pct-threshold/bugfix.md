# Bugfix Requirements Document

## Introduction

DocDB 및 Aurora RDS Provisioned 인스턴스의 FreeLocalStorageGB 알람 임계치가 인스턴스 실제 로컬 스토리지 용량을 반영하지 못하고 고정값(`HARDCODED_DEFAULTS["FreeLocalStorageGB"] = 10.0`)을 사용하는 버그를 수정한다.

FreeMemoryGB에는 이미 `_resolve_free_memory_threshold()` 함수가 구현되어 인스턴스 클래스별 메모리 용량 기반 퍼센트 임계치(기본 20%)를 자동 계산한다. 그러나 FreeLocalStorageGB에는 동일한 퍼센트 기반 해석 로직이 없어, 모든 인스턴스에 10GB 고정 임계치가 적용된다.

이로 인해:
- 소형 인스턴스(예: DocDB db.t3.medium, 로컬 스토리지 ~15-20GB)에 10GB 임계치가 걸려 50% 이상 사용 시 알람 발생 (너무 빡빡)
- 대형 인스턴스(예: db.r6g.4xlarge, 로컬 스토리지 수백 GB)에 10GB 임계치가 걸려 스토리지의 극소 비율에서야 감지되어 너무 늦게 알람 발생

영향 범위: DocDB(AWS/DocDB 네임스페이스)와 Aurora RDS Provisioned(AWS/RDS 네임스페이스). 일반 RDS는 FreeLocalStorage 메트릭이 없으므로 해당 없음. Aurora Serverless v2는 FreeLocalStorage 메트릭이 미발행되므로 해당 없음.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN DocDB 또는 Aurora RDS Provisioned 인스턴스에 대해 FreeLocalStorageGB 알람을 생성할 때 THEN the system은 인스턴스 실제 로컬 스토리지 용량을 무시하고 `HARDCODED_DEFAULTS["FreeLocalStorageGB"] = 10.0` 고정값을 임계치로 사용한다

1.2 WHEN 로컬 스토리지가 약 15~20GB인 소형 인스턴스(예: DocDB db.t3.medium)에 10GB 고정 임계치가 적용될 때 THEN the system은 스토리지의 50% 이상 사용 시 알람이 발생하여 임계치가 너무 빡빡하다

1.3 WHEN 로컬 스토리지가 수백 GB인 대형 인스턴스(예: db.r6g.4xlarge)에 10GB 고정 임계치가 적용될 때 THEN the system은 스토리지의 극소 비율(예: 3~5%)에서야 알람이 발생하여 스토리지 압박을 너무 늦게 감지한다

1.4 WHEN FreeLocalStorageGB 알람 임계치를 해석할 때 THEN the system은 `_resolve_free_memory_threshold()` 같은 퍼센트 기반 해석 함수가 없어 `get_threshold()` → `HARDCODED_DEFAULTS` 폴백 체인만 사용한다

### Expected Behavior (Correct)

2.1 WHEN DocDB 또는 Aurora RDS Provisioned 인스턴스에 대해 FreeLocalStorageGB 알람을 생성할 때 THEN the system SHALL 인스턴스 실제 로컬 스토리지 용량의 20%(기본값)를 임계치로 자동 계산해야 한다

2.2 WHEN 인스턴스에 `Threshold_FreeLocalStoragePct` 태그가 명시적으로 설정되어 있는 경우 THEN the system SHALL 태그 값을 퍼센트 기반 임계치로 최우선 사용해야 한다 (예: `Threshold_FreeLocalStoragePct=30` → 로컬 스토리지의 30%를 임계치로 계산)

2.3 WHEN `Threshold_FreeLocalStoragePct` 태그가 없고 인스턴스의 로컬 스토리지 총 용량(`_total_local_storage_bytes`)이 설정되어 있는 경우 THEN the system SHALL 기본 퍼센트 20%를 적용하여 `실제 로컬 스토리지 * 0.2`를 임계치로 자동 계산해야 한다

2.4 WHEN 인스턴스의 로컬 스토리지 총 용량을 조회할 수 없는 경우(API 실패 등) THEN the system SHALL warning 로그를 남기고 기존 GB 절대값 폴백(`Threshold_FreeLocalStorageGB` 태그 또는 `HARDCODED_DEFAULTS["FreeLocalStorageGB"] = 10.0`)을 사용해야 한다

2.5 WHEN `_resolve_free_local_storage_threshold()` 함수가 임계치를 해석할 때 THEN the system SHALL 3단계 폴백 체인을 따라야 한다: Threshold_FreeLocalStoragePct 태그 → 기본 퍼센트 20% → GB 절대값(Threshold_FreeLocalStorageGB 태그 또는 HARDCODED_DEFAULTS)

### Unchanged Behavior (Regression Prevention)

3.1 WHEN 인스턴스에 `Threshold_FreeLocalStorageGB` 태그가 명시적으로 설정되어 있는 경우 THEN the system SHALL CONTINUE TO 태그 값을 GB 절대값 임계치로 사용해야 한다 (3단계 폴백에서 GB 절대값으로 동작)

3.2 WHEN Aurora Serverless v2 인스턴스에 대해 알람을 생성할 때 THEN the system SHALL CONTINUE TO FreeLocalStorageGB 알람을 생성하지 않아야 한다 (Serverless v2는 FreeLocalStorage 메트릭 미발행)

3.3 WHEN FreeLocalStorageGB 이외의 다른 메트릭(CPU, FreeMemoryGB, Connections 등)에 대해 알람을 생성할 때 THEN the system SHALL CONTINUE TO 기존 임계치 해석 로직을 변경 없이 사용해야 한다

3.4 WHEN FreeMemoryGB 알람의 퍼센트 기반 임계치를 해석할 때 THEN the system SHALL CONTINUE TO 기존 `_resolve_free_memory_threshold()` 로직을 변경 없이 사용해야 한다

3.5 WHEN 일반 RDS(비Aurora) 인스턴스에 대해 알람을 생성할 때 THEN the system SHALL CONTINUE TO FreeLocalStorageGB 알람을 생성하지 않아야 한다 (일반 RDS는 FreeLocalStorage 메트릭 없음)

3.6 WHEN `Threshold_FreeLocalStorageGB` 태그 값이 "off"로 설정된 경우 THEN the system SHALL CONTINUE TO 해당 알람을 생성하지 않아야 한다 (기존 off 태그 동작 유지)
