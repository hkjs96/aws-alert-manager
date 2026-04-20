# Bugfix Requirements Document

## Introduction

`sync_alarms_for_resource` 함수에서 디스크 알람의 임계치를 비교할 때 경로별 태그 키(`Disk_root`, `Disk_data` 등)를 사용하지 않고 일괄적으로 `get_threshold(resource_tags, "Disk")`를 호출한다. 이로 인해 사용자가 `Threshold_Disk_root=55` 같은 경로별 태그를 설정해도 sync 시 항상 기본값(80)과 비교하게 되어, 실제 알람 임계치와 태그 임계치가 다름에도 불구하고 알람이 업데이트되지 않는다.

`create_alarms_for_resource`에서는 이미 알람의 Dimensions에서 path를 추출하여 `get_threshold(resource_tags, "Disk_root")` 형태로 올바르게 조회하고 있으나, `sync_alarms_for_resource`의 디스크 알람 동기화 블록에서는 이 로직이 누락되어 있다.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `sync_alarms_for_resource`가 디스크 알람의 임계치를 비교할 때 THEN the system은 모든 디스크 경로에 대해 `get_threshold(resource_tags, "Disk")`를 호출하여 항상 기본값(80)만 반환한다

1.2 WHEN 사용자가 `Threshold_Disk_root=55` 태그를 설정하고 sync가 실행될 때 THEN the system은 기존 알람 임계치(55)와 기본값(80)을 비교하여 불일치로 판단하고 불필요한 재생성을 트리거한다

1.3 WHEN 사용자가 `Threshold_Disk_root=55` 태그를 설정하고 이미 알람이 올바른 임계치(55)로 생성되어 있을 때 THEN the system은 sync에서 `get_threshold(resource_tags, "Disk")` → 80을 반환하고, 기존 알람(55)과 80을 비교하여 불일치로 판단해 매번 불필요한 재생성을 반복한다

1.4 WHEN 사용자가 `Threshold_Disk_data=90` 태그를 설정하고 `/data` 경로의 디스크 알람이 존재할 때 THEN the system은 해당 알람에 대해서도 `get_threshold(resource_tags, "Disk")` → 80을 사용하여 경로별 임계치(90)를 무시한다

### Expected Behavior (Correct)

2.1 WHEN `sync_alarms_for_resource`가 디스크 알람의 임계치를 비교할 때 THEN the system SHALL 각 알람의 Dimensions 또는 알람 이름에서 디스크 경로(path)를 추출하고, `get_threshold(resource_tags, "Disk_{path_suffix}")`를 호출하여 경로별 임계치를 조회해야 한다

2.2 WHEN 사용자가 `Threshold_Disk_root=55` 태그를 설정하고 sync가 실행될 때 THEN the system SHALL 루트(`/`) 디스크 알람에 대해 `get_threshold(resource_tags, "Disk_root")` → 55를 반환하고, 기존 알람 임계치와 올바르게 비교해야 한다

2.3 WHEN 사용자가 `Threshold_Disk_root=55` 태그를 설정하고 이미 알람이 올바른 임계치(55)로 생성되어 있을 때 THEN the system SHALL sync에서 태그 임계치(55)와 기존 알람 임계치(55)가 일치함을 인식하고 재생성을 건너뛰어야 한다

2.4 WHEN 사용자가 `Threshold_Disk_data=90` 태그를 설정하고 `/data` 경로의 디스크 알람이 존재할 때 THEN the system SHALL 해당 알람에 대해 `get_threshold(resource_tags, "Disk_data")` → 90을 사용하여 경로별 임계치를 올바르게 비교해야 한다

### Unchanged Behavior (Regression Prevention)

3.1 WHEN 디스크 경로별 태그가 없고 기본 `Disk` 임계치(80)만 적용되는 리소스에 대해 sync가 실행될 때 THEN the system SHALL CONTINUE TO `get_threshold(resource_tags, "Disk_root")` → 80 (기본값 폴백)을 반환하고 기존과 동일하게 동작해야 한다

3.2 WHEN CPU, Memory 등 디스크가 아닌 메트릭의 알람에 대해 sync가 실행될 때 THEN the system SHALL CONTINUE TO 기존과 동일하게 `get_threshold(resource_tags, metric)`으로 임계치를 조회하고 비교해야 한다

3.3 WHEN `create_alarms_for_resource`가 디스크 알람을 생성할 때 THEN the system SHALL CONTINUE TO 기존과 동일하게 경로별 `get_threshold(resource_tags, "Disk_{path_suffix}")`로 임계치를 조회하여 알람을 생성해야 한다

3.4 WHEN 디스크 알람이 하나도 존재하지 않는 리소스에 대해 sync가 실행될 때 THEN the system SHALL CONTINUE TO `needs_recreate = True`를 설정하고 `create_alarms_for_resource`를 통해 전체 알람을 재생성해야 한다
