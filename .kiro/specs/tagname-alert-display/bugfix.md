# Bugfix Requirements Document

## Introduction

SNS 알림 메시지에서 리소스의 AWS Name 태그 값이 `(TagName: <Name 태그 값>)` 형식으로 표시되어야 하지만, 현재는 리소스 ID만 표시되고 있다. `sns_notifier.py`의 모든 알림 함수(`send_alert`, `send_remediation_alert`, `send_lifecycle_alert`)가 `resource_id`만 받고 Name 태그 정보를 전달받지 않아, 메시지 본문에 TagName이 누락된다.

영향 범위: 임계치 초과 알림, 자동 복구 알림, 생명주기 알림 등 모든 SNS 알림 메시지.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN 임계치 초과 알림(`send_alert`)이 발송될 때 THEN 메시지가 `[{resource_type}] {resource_id} - {metric_name} exceeded threshold: {current_value} > {threshold}` 형식으로 표시되며, 리소스의 Name 태그 값이 포함되지 않는다.

1.2 WHEN 자동 복구 알림(`send_remediation_alert`)이 발송될 때 THEN 메시지가 `[{resource_type}] {resource_id} - unauthorized change detected. Change: {change_summary}. Action: {action_taken}` 형식으로 표시되며, 리소스의 Name 태그 값이 포함되지 않는다.

1.3 WHEN 생명주기 알림(`send_lifecycle_alert`)이 발송될 때 THEN 메시지 본문에 리소스의 Name 태그 값이 포함되지 않는다.

1.4 WHEN Name 태그가 없는 리소스에 대해 알림이 발송될 때 THEN Name 태그 부재를 나타내는 표시 없이 리소스 ID만 표시된다.

### Expected Behavior (Correct)

2.1 WHEN 임계치 초과 알림(`send_alert`)이 발송될 때 THEN 메시지에 `(TagName: <Name 태그 값>)` 형식으로 리소스의 Name 태그 값이 포함되어야 한다.

2.2 WHEN 자동 복구 알림(`send_remediation_alert`)이 발송될 때 THEN 메시지에 `(TagName: <Name 태그 값>)` 형식으로 리소스의 Name 태그 값이 포함되어야 한다.

2.3 WHEN 생명주기 알림(`send_lifecycle_alert`)이 발송될 때 THEN 메시지에 `(TagName: <Name 태그 값>)` 형식으로 리소스의 Name 태그 값이 포함되어야 한다.

2.4 WHEN Name 태그가 없는 리소스에 대해 알림이 발송될 때 THEN 메시지에 `(TagName: N/A)` 형식으로 표시되어야 한다.

### Unchanged Behavior (Regression Prevention)

3.1 WHEN 알림이 발송될 때 THEN SNS 메시지의 JSON 구조(`alert_type`, `resource_id`, `resource_type`, `timestamp` 등 기존 필드)는 변경 없이 유지되어야 한다.

3.2 WHEN SNS 발송이 실패할 때 THEN 기존과 동일하게 CloudWatch Logs에 오류를 기록하고 예외를 삼키는 동작이 유지되어야 한다.

3.3 WHEN 리소스 수집기(EC2, RDS, ELB collector)가 리소스를 수집할 때 THEN 기존 수집 로직과 반환 데이터(`ResourceInfo`)는 변경 없이 유지되어야 한다.

3.4 WHEN 오류 알림(`send_error_alert`)이 발송될 때 THEN 기존 메시지 형식이 변경 없이 유지되어야 한다 (오류 알림은 특정 리소스가 아닌 운영 컨텍스트 기반이므로 TagName 불필요).

3.5 WHEN 알림 유형별 SNS 토픽 ARN 라우팅이 수행될 때 THEN 기존 `_get_topic_arn` 로직이 변경 없이 유지되어야 한다.
