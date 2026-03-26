# Bugfix Requirements Document

## Introduction

`sync_alarms_for_resource` 함수는 리소스 태그의 임계치 변경을 감지하면 `needs_recreate = True`로 설정하고 `create_alarms_for_resource`를 호출한다. 그런데 이 함수 내부에서 `_delete_all_alarms_for_resource`로 해당 리소스의 **모든** 알람을 삭제한 뒤 전체 재생성한다.

결과적으로 `Threshold_Disk_data` 태그 하나만 변경해도 CPU, Memory, Disk_root 등 변경되지 않은 알람까지 불필요하게 삭제·재생성된다. 이는 알람 상태 초기화, 불필요한 AWS API 호출, 그리고 재생성 중 알람 공백 구간을 유발한다.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN 리소스의 특정 알람 임계치 태그(예: `Threshold_Disk_data`)가 변경되어 `needs_recreate = True`가 되면, THEN 시스템은 변경되지 않은 알람(CPU, Memory, Disk_root 등)을 포함한 해당 리소스의 **모든** 알람을 삭제한다.

1.2 WHEN `_delete_all_alarms_for_resource`가 호출되면, THEN 시스템은 `result["updated"]` 리스트에 없는 알람(임계치가 변경되지 않은 알람)도 함께 삭제한다.

1.3 WHEN 전체 삭제 후 재생성이 수행되면, THEN 시스템은 삭제와 재생성 사이의 짧은 공백 구간 동안 변경되지 않은 알람도 존재하지 않는 상태가 된다.

### Expected Behavior (Correct)

2.1 WHEN 리소스의 특정 알람 임계치 태그가 변경되어 `needs_recreate = True`가 되면, THEN 시스템은 `result["updated"]` 리스트에 포함된 알람(임계치가 변경된 알람)만 개별적으로 삭제 후 재생성해야 한다.

2.2 WHEN `result["created"]` 리스트에 새로 추가되어야 할 알람이 있으면, THEN 시스템은 기존 알람을 삭제하지 않고 해당 알람만 신규 생성해야 한다.

2.3 WHEN 임계치가 변경된 알람을 재생성할 때, THEN 시스템은 `create_alarms_for_resource` 전체를 호출하는 대신 해당 알람만 `put_metric_alarm`으로 개별 재생성해야 한다.

### Unchanged Behavior (Regression Prevention)

3.1 WHEN 리소스에 알람이 하나도 존재하지 않는 최초 생성 시, THEN 시스템은 기존과 동일하게 `create_alarms_for_resource`를 호출하여 전체 알람을 생성해야 한다.

3.2 WHEN 모든 알람의 임계치가 현재 태그와 일치하는 경우(`result["ok"]`만 존재), THEN 시스템은 어떤 알람도 삭제하거나 재생성하지 않아야 한다.

3.3 WHEN 임계치가 변경되지 않은 알람(`result["ok"]` 목록)이 존재하면, THEN 시스템은 해당 알람을 삭제하거나 수정하지 않고 그대로 유지해야 한다.

3.4 WHEN `create_alarms_for_resource`가 최초 생성 목적으로 직접 호출되면, THEN 시스템은 기존과 동일하게 `_delete_all_alarms_for_resource`를 호출하여 레거시 알람을 포함한 전체 정리 후 재생성해야 한다.
