# Bugfix Requirements Document

## Introduction

NLB Target Group에 ALB 전용 메트릭(`RequestCountPerTarget`, `TargetResponseTime`)에 대한 알람이 생성되어 해당 알람이 영구적으로 `INSUFFICIENT_DATA` 상태에 빠지는 버그를 수정한다. `_TG_ALARMS`가 단일 리스트로 정의되어 있고 `_get_alarm_defs("TG")`가 LB 타입(ALB/NLB)을 구분하지 않아 발생한다.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN NLB Target Group(`_lb_type == "network"`)에 대해 `create_alarms_for_resource()`를 호출하면 THEN `_get_alarm_defs("TG")`가 `RequestCountPerTarget` 알람 정의를 포함한 4개 알람 정의를 반환하여 `AWS/NetworkELB` 네임스페이스에 `RequestCountPerTarget` 알람이 생성되고 `INSUFFICIENT_DATA` 상태가 된다

1.2 WHEN NLB Target Group(`_lb_type == "network"`)에 대해 `create_alarms_for_resource()`를 호출하면 THEN `_get_alarm_defs("TG")`가 `TGResponseTime`(TargetResponseTime) 알람 정의를 포함한 4개 알람 정의를 반환하여 `AWS/NetworkELB` 네임스페이스에 `TargetResponseTime` 알람이 생성되고 `INSUFFICIENT_DATA` 상태가 된다

1.3 WHEN NLB Target Group에 대해 `sync_alarms_for_resource()`를 호출하면 THEN `_get_alarm_defs("TG")`가 동일하게 4개 알람 정의를 반환하여 `RequestCountPerTarget`과 `TGResponseTime`에 대한 동기화/재생성이 시도된다

1.4 WHEN `_HARDCODED_METRIC_KEYS["TG"]`를 조회하면 THEN `RequestCountPerTarget`과 `TGResponseTime`이 LB 타입 구분 없이 항상 포함되어 NLB TG에서도 해당 메트릭이 하드코딩 메트릭으로 인식된다

### Expected Behavior (Correct)

2.1 WHEN NLB Target Group(`_lb_type == "network"`)에 대해 `create_alarms_for_resource()`를 호출하면 THEN `HealthyHostCount`와 `UnHealthyHostCount` 2개 알람만 생성되고 `RequestCountPerTarget`과 `TGResponseTime` 알람은 생성되지 않아야 한다

2.2 WHEN ALB Target Group(`_lb_type == "application"`)에 대해 `create_alarms_for_resource()`를 호출하면 THEN `HealthyHostCount`, `UnHealthyHostCount`, `RequestCountPerTarget`, `TGResponseTime` 4개 알람이 모두 생성되어야 한다

2.3 WHEN NLB Target Group에 대해 `sync_alarms_for_resource()`를 호출하면 THEN `HealthyHostCount`와 `UnHealthyHostCount`만 동기화 대상이 되고 `RequestCountPerTarget`과 `TGResponseTime`은 동기화 대상에서 제외되어야 한다

2.4 WHEN NLB Target Group에 대해 `_get_alarm_defs("TG")`를 호출하면 THEN NLB TG에 유효한 메트릭(`HealthyHostCount`, `UnHealthyHostCount`)만 포함된 알람 정의 리스트를 반환하거나, 호출 측에서 LB 타입 기반 필터링이 적용되어야 한다

### Unchanged Behavior (Regression Prevention)

3.1 WHEN ALB Target Group(`_lb_type == "application"`)에 대해 `create_alarms_for_resource()`를 호출하면 THEN 기존과 동일하게 4개 알람(`HealthyHostCount`, `UnHealthyHostCount`, `RequestCountPerTarget`, `TGResponseTime`)이 생성되어야 한다

3.2 WHEN ALB Target Group에 대해 `sync_alarms_for_resource()`를 호출하면 THEN 기존과 동일하게 4개 메트릭에 대한 동기화가 수행되어야 한다

3.3 WHEN EC2, RDS, ALB, NLB 리소스에 대해 `create_alarms_for_resource()`를 호출하면 THEN 각 리소스 유형별 알람 정의가 변경 없이 동일하게 적용되어야 한다

3.4 WHEN TG 리소스에 대해 `_build_dimensions()`를 호출하면 THEN `TargetGroup` + `LoadBalancer` 복합 디멘션이 기존과 동일하게 생성되어야 한다

3.5 WHEN TG 리소스에 대해 `_resolve_tg_namespace()`를 호출하면 THEN `_lb_type == "network"` → `AWS/NetworkELB`, 그 외 → `AWS/ApplicationELB` 동작이 기존과 동일해야 한다

3.6 WHEN TG 리소스에 대해 `_find_alarms_for_resource()`를 호출하면 THEN 기존과 동일하게 `[TG]` prefix + `[ELB]` 레거시 prefix 검색이 수행되어야 한다
