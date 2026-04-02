# Bugfix Requirements Document

## Introduction

프로덕션(us-east-1) Daily Monitor Lambda 실행 후 확인된 두 가지 버그를 수정한다.

**버그 1 (주요)**: TG(Target Group) 알람 생성 시 `TargetGroup` 디멘션만 설정되고 `LoadBalancer` 복합 디멘션이 누락되어, CloudWatch가 메트릭 데이터를 찾지 못해 모든 TG 알람이 `INSUFFICIENT_DATA` 상태가 된다. 프로덕션에서 4개 TG 알람 전부 `INSUFFICIENT_DATA`로 확인됨.

**버그 2 (부차)**: ELB 리소스 타입 분리(ALB/NLB/TG) 이후, 기존 `[ELB]` 접두사 레거시 알람이 정리되지 않고 새 `[ALB]`/`[NLB]` 알람과 공존한다. 프로덕션에서 2개 레거시 `[ELB]` 알람이 잔존 확인됨.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN TG 리소스에 대해 `_create_standard_alarm()`이 호출될 때 THEN 시스템은 `TargetGroup` 단일 디멘션만으로 CloudWatch 알람을 생성하여, CloudWatch가 메트릭 데이터를 찾지 못하고 알람이 `INSUFFICIENT_DATA` 상태가 된다

1.2 WHEN TG 리소스에 대해 `_create_single_alarm()`이 호출될 때 THEN 시스템은 `TargetGroup` 단일 디멘션만으로 CloudWatch 알람을 생성하여, 동일하게 `INSUFFICIENT_DATA` 상태가 된다

1.3 WHEN TG 리소스에 대해 `_recreate_standard_alarm()`이 호출될 때 THEN 시스템은 `TargetGroup` 단일 디멘션만으로 CloudWatch 알람을 재생성하여, 동일하게 `INSUFFICIENT_DATA` 상태가 된다

1.4 WHEN ALB/NLB 리소스에 대해 `create_alarms_for_resource()`가 호출되어 새 `[ALB]`/`[NLB]` 알람이 생성될 때 THEN 시스템은 기존 `[ELB]` 접두사 레거시 알람을 삭제하지 못하고 레거시 알람이 잔존한다

### Expected Behavior (Correct)

2.1 WHEN TG 리소스에 대해 `_create_standard_alarm()`이 호출될 때 THEN 시스템은 `TargetGroup` + `LoadBalancer` 복합 디멘션으로 CloudWatch 알람을 생성하여 SHALL 정상적으로 메트릭 데이터와 매칭되어야 한다. `LoadBalancer` 값은 `resource_tags["_lb_arn"]`에서 추출한 LB ARN suffix를 사용한다

2.2 WHEN TG 리소스에 대해 `_create_single_alarm()`이 호출될 때 THEN 시스템은 `TargetGroup` + `LoadBalancer` 복합 디멘션으로 CloudWatch 알람을 생성 SHALL 한다

2.3 WHEN TG 리소스에 대해 `_recreate_standard_alarm()`이 호출될 때 THEN 시스템은 `TargetGroup` + `LoadBalancer` 복합 디멘션으로 CloudWatch 알람을 재생성 SHALL 한다

2.4 WHEN ALB/NLB 리소스에 대해 `create_alarms_for_resource()`가 호출될 때 THEN 시스템은 `[ELB]` 접두사 레거시 알람을 포함하여 기존 알람을 모두 삭제한 후 새 알람을 생성 SHALL 한다

### Unchanged Behavior (Regression Prevention)

3.1 WHEN ALB 리소스에 대해 알람이 생성될 때 THEN 시스템은 기존과 동일하게 `LoadBalancer` 단일 디멘션으로 알람을 생성 SHALL CONTINUE TO 한다

3.2 WHEN NLB 리소스에 대해 알람이 생성될 때 THEN 시스템은 기존과 동일하게 `LoadBalancer` 단일 디멘션으로 알람을 생성 SHALL CONTINUE TO 한다

3.3 WHEN EC2/RDS 리소스에 대해 알람이 생성될 때 THEN 시스템은 기존과 동일하게 `InstanceId`/`DBInstanceIdentifier` 단일 디멘션으로 알람을 생성 SHALL CONTINUE TO 한다

3.4 WHEN TG가 아닌 리소스에 대해 `_create_standard_alarm()`이 호출될 때 THEN 시스템은 기존 디멘션 로직을 변경 없이 유지 SHALL CONTINUE TO 한다

3.5 WHEN `_find_alarms_for_resource()`가 ALB/NLB 리소스에 대해 호출될 때 THEN 시스템은 `[ELB]` 접두사 레거시 알람도 검색 결과에 포함 SHALL CONTINUE TO 한다

3.6 WHEN `_TG_ALARMS` 정의의 `namespace` 필드가 사용될 때 THEN 시스템은 ALB TG의 경우 `AWS/ApplicationELB`, NLB TG의 경우 `AWS/NetworkELB`를 올바르게 적용 SHALL CONTINUE TO 한다 (현재 `_TG_ALARMS`는 `AWS/ApplicationELB`만 하드코딩되어 있으므로, NLB TG의 namespace 결정은 `_lb_type` 태그 기반으로 동적 처리가 필요할 수 있음)
