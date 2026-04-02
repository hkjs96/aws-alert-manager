# Bugfix Requirements Document

## Introduction

Target Group(TG)이 삭제될 때 Remediation Handler가 `DeleteTargetGroup` CloudTrail 이벤트를 감지하지 못해서, TG 관련 CloudWatch 알람이 정리되지 않고 고아 알람으로 남아있는 버그.

영향 범위:
- `Monitoring=on` 태그가 있는 TG가 삭제되면 해당 TG의 CloudWatch 알람(HealthyHostCount, UnHealthyHostCount, RequestCountPerTarget, TGResponseTime)이 삭제되지 않음
- Lifecycle SNS 알림도 발송되지 않아 운영자가 TG 삭제 사실을 인지하지 못함
- 고아 알람이 `INSUFFICIENT_DATA` 상태로 무한히 남아 비용과 노이즈 유발

근본 원인: `DeleteTargetGroup` 이벤트가 시스템의 3개 레이어(EventBridge 룰, 모니터링 이벤트 상수, Lambda 이벤트 파싱)에서 모두 누락됨.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `DeleteTargetGroup` CloudTrail 이벤트가 발생하면 THEN EventBridge 룰(`CloudTrailModifyRule`)이 해당 이벤트를 캡처하지 않아 Remediation Handler Lambda가 호출되지 않는다

1.2 WHEN `DeleteTargetGroup` 이벤트가 Remediation Handler에 도달하더라도 THEN `MONITORED_API_EVENTS["DELETE"]`에 `DeleteTargetGroup`이 없어 이벤트 카테고리를 판별할 수 없다

1.3 WHEN `DeleteTargetGroup` 이벤트가 Remediation Handler에 도달하더라도 THEN `_API_MAP`에 `DeleteTargetGroup` 매핑이 없어 `parse_cloudtrail_event()`가 `ValueError("Unsupported eventName")`를 발생시킨다

1.4 WHEN TG가 삭제된 후 THEN 해당 TG의 CloudWatch 알람(HealthyHostCount, UnHealthyHostCount 등)이 삭제되지 않고 `INSUFFICIENT_DATA` 상태로 남아있다

1.5 WHEN `Monitoring=on` 태그가 있는 TG가 삭제된 후 THEN `RESOURCE_DELETED` lifecycle SNS 알림이 발송되지 않는다

### Expected Behavior (Correct)

2.1 WHEN `DeleteTargetGroup` CloudTrail 이벤트가 발생하면 THEN EventBridge 룰이 해당 이벤트를 캡처하여 Remediation Handler Lambda를 호출해야 한다 (SHALL)

2.2 WHEN `DeleteTargetGroup` 이벤트가 Remediation Handler에 도달하면 THEN `MONITORED_API_EVENTS["DELETE"]`에서 `DELETE` 카테고리로 분류되어야 한다 (SHALL)

2.3 WHEN `DeleteTargetGroup` 이벤트가 Remediation Handler에 도달하면 THEN `parse_cloudtrail_event()`가 `requestParameters.targetGroupArn`에서 TG ARN을 추출하고 `resource_type="TG"`로 파싱해야 한다 (SHALL)

2.4 WHEN TG가 삭제되면 THEN `_handle_delete()`가 해당 TG의 모든 CloudWatch 알람을 `delete_alarms_for_resource()`로 삭제해야 한다 (SHALL)

2.5 WHEN `Monitoring=on` 태그가 있는 TG가 삭제되면 THEN `RESOURCE_DELETED` 타입의 lifecycle SNS 알림이 발송되어야 한다 (SHALL)

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `DeleteLoadBalancer` CloudTrail 이벤트가 발생하면 THEN 기존과 동일하게 ALB/NLB 알람 삭제 및 lifecycle 알림이 정상 동작해야 한다 (SHALL CONTINUE TO)

3.2 WHEN `TerminateInstances` CloudTrail 이벤트가 발생하면 THEN 기존과 동일하게 EC2 알람 삭제 및 lifecycle 알림이 정상 동작해야 한다 (SHALL CONTINUE TO)

3.3 WHEN `DeleteDBInstance` CloudTrail 이벤트가 발생하면 THEN 기존과 동일하게 RDS 알람 삭제 및 lifecycle 알림이 정상 동작해야 한다 (SHALL CONTINUE TO)

3.4 WHEN `ModifyLoadBalancerAttributes` 등 MODIFY 이벤트가 발생하면 THEN 기존 Auto-Remediation 로직이 변경 없이 동작해야 한다 (SHALL CONTINUE TO)

3.5 WHEN `AddTags`/`RemoveTags` 등 TAG_CHANGE 이벤트가 발생하면 THEN 기존 태그 변경 처리 로직이 변경 없이 동작해야 한다 (SHALL CONTINUE TO)

3.6 WHEN `Monitoring` 태그가 없는 TG가 삭제되면 THEN lifecycle SNS 알림이 발송되지 않아야 한다 (SHALL CONTINUE TO — 기존 DELETE 핸들러의 비모니터링 리소스 처리 로직과 동일)
