# Bugfix Requirements Document

## Introduction

`remediation_handler/lambda_handler.py`의 `_handle_tag_change` 함수가 `Threshold_*` 태그 변경 이벤트를 무시하는 버그.

현재 구현은 TAG_CHANGE 이벤트 수신 시 `"Monitoring"` 키가 변경된 태그에 포함된 경우에만 처리를 진행하고,
`Threshold_CPU`, `Threshold_Disk_data` 등 임계치 태그만 변경된 경우에는 즉시 `return`하여 알람이 재동기화되지 않는다.

그 결과, 운영자가 임계치 태그를 수정해도 CloudWatch Alarm의 임계치가 갱신되지 않아
모니터링 설정이 실제 의도와 불일치하는 상태가 지속된다.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `Threshold_*` 태그만 변경(추가/수정)되고 `Monitoring` 태그가 변경 태그 목록에 없을 때
    THEN 시스템은 `monitoring_involved = False`로 판단하여 즉시 `return`하고 알람을 재동기화하지 않는다

1.2 WHEN `Threshold_Disk_data=20`과 같은 임계치 태그가 EC2 인스턴스에 추가될 때
    THEN 시스템은 해당 이벤트를 무시하고 `sync_alarms_for_resource`를 호출하지 않는다

1.3 WHEN `Monitoring=on` 상태인 리소스에 `Threshold_CPU=90`이 설정될 때
    THEN 시스템은 기존 CPU 알람의 임계치를 갱신하지 않고 이전 값을 유지한다

### Expected Behavior (Correct)

2.1 WHEN `Threshold_*` 패턴의 태그가 변경되고 해당 리소스에 `Monitoring=on` 태그가 존재할 때
    THEN 시스템은 `sync_alarms_for_resource`를 호출하여 해당 리소스의 알람을 즉시 재동기화해야 한다

2.2 WHEN `Threshold_Disk_data=20`과 같은 임계치 태그가 EC2 인스턴스에 추가될 때
    THEN 시스템은 현재 리소스 태그를 조회한 후 `sync_alarms_for_resource`를 호출하여 알람을 갱신해야 한다

2.3 WHEN `Threshold_*` 태그가 변경되었으나 해당 리소스에 `Monitoring=on` 태그가 없을 때
    THEN 시스템은 알람 재동기화를 수행하지 않고 조용히 종료해야 한다

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `Monitoring=on` 태그가 추가될 때
    THEN 시스템은 기존과 동일하게 `create_alarms_for_resource`를 호출하여 알람을 생성해야 한다

3.2 WHEN `Monitoring` 태그가 `on`이 아닌 값으로 변경되거나 삭제될 때
    THEN 시스템은 기존과 동일하게 알람을 삭제하고 lifecycle SNS 알림을 발송해야 한다

3.3 WHEN `Monitoring`과 무관한 일반 태그(예: `Name`, `Env`)만 변경될 때
    THEN 시스템은 기존과 동일하게 해당 이벤트를 무시해야 한다

3.4 WHEN MODIFY 이벤트가 수신될 때
    THEN 시스템은 기존과 동일하게 `Monitoring=on` 리소스에 대해 Auto-Remediation을 수행해야 한다

3.5 WHEN DELETE 이벤트가 수신될 때
    THEN 시스템은 기존과 동일하게 알람 삭제 및 lifecycle SNS 알림을 발송해야 한다
