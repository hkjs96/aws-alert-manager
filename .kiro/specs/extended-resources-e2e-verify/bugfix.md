# Bugfix Requirements Document

## Introduction

`dev-e2e-extended` CloudFormation 스택이 배포된 상태에서, Daily Monitor가 11개 확장 리소스(SQS, ECS, MSK, DynamoDB, CloudFront, WAF, Route53, EFS, S3, SageMaker, SNS)에 대해 CloudWatch 알람을 정상적으로 생성했는지 검증이 필요하다.

현재 문제:
- 스택 배포 후 Daily Monitor를 실행하지 않았거나, 실행했더라도 알람이 생성되었는지 확인되지 않음
- 메트릭 데이터가 없는 리소스는 알람이 `INSUFFICIENT_DATA` 상태로 남아 있을 수 있음
- 트래픽 생성 없이는 SQS, DynamoDB, CloudFront, WAF, S3, SNS 등의 메트릭이 발행되지 않아 알람 상태 검증이 불가능

이 스펙은 알람 생성 여부 확인 → 누락 시 강제 생성 → 트래픽 생성 → 알람 상태 재검증의 흐름을 Python 스크립트로 자동화한다.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `dev-e2e-extended` 스택이 배포된 상태에서 Daily Monitor를 실행하면 THEN 시스템은 알람 생성 성공 여부를 반환하지 않아 실제로 ~35개 알람이 생성되었는지 확인할 수 없다

1.2 WHEN Daily Monitor 실행 후 알람 수를 확인하면 THEN 시스템은 `INSUFFICIENT_DATA` 상태의 알람을 정상으로 간주하여 메트릭 데이터 부재 여부를 구분하지 못한다

1.3 WHEN 트래픽 없이 알람 상태를 조회하면 THEN 시스템은 SQS, DynamoDB, CloudFront, WAF, S3, SNS 알람이 `INSUFFICIENT_DATA` 상태로 표시되어 알람 정의 자체의 정합성을 검증할 수 없다

1.4 WHEN 알람이 누락된 리소스가 발견되면 THEN 시스템은 누락 원인(Daily Monitor 미실행, 태그 미감지, collector 오류 등)을 구분하지 못하고 수동 개입이 필요하다

### Expected Behavior (Correct)

2.1 WHEN `dev-e2e-extended` 스택의 CloudFormation Outputs에서 리소스 식별자를 조회하면 THEN 시스템은 11개 리소스 타입별 예상 알람 목록(~35개)을 생성하고 실제 존재하는 알람과 비교하여 누락 목록을 출력해야 한다

2.2 WHEN 알람이 누락된 리소스가 발견되면 THEN 시스템은 `alarm_manager.create_alarms_for_resource()`를 직접 호출하여 누락 알람을 강제 생성해야 한다

2.3 WHEN 트래픽 생성 스크립트(`traffic-test.sh`)를 실행하면 THEN 시스템은 SQS, DynamoDB, CloudFront, WAF, S3, SNS에 대한 메트릭 데이터를 발생시켜 알람이 `INSUFFICIENT_DATA`에서 `OK` 또는 `ALARM` 상태로 전환될 수 있는 조건을 만들어야 한다

2.4 WHEN 트래픽 생성 후 CloudWatch 메트릭 반영 대기(최소 1분) 후 알람 상태를 재조회하면 THEN 시스템은 각 알람의 상태(`OK`, `ALARM`, `INSUFFICIENT_DATA`)를 리소스 타입별로 집계하여 출력해야 한다

2.5 WHEN 알람 상태 검증 결과 `INSUFFICIENT_DATA` 비율이 50% 초과이면 THEN 시스템은 경고를 출력하고 트래픽 재생성 또는 대기 시간 연장을 안내해야 한다

### Unchanged Behavior (Regression Prevention)

3.1 WHEN 기존 Daily Monitor가 다른 리소스(EC2, RDS, ALB 등)에 대해 알람을 관리하는 동안 THEN 시스템은 해당 리소스들의 알람을 변경하지 않고 CONTINUE TO 기존 알람 상태를 유지해야 한다

3.2 WHEN `alarm_manager.create_alarms_for_resource()`를 `dev-e2e-extended` 리소스에 대해 호출하는 동안 THEN 시스템은 동일 리소스에 대한 기존 알람을 삭제 후 재생성하는 기존 동작을 CONTINUE TO 유지해야 한다

3.3 WHEN `traffic-test.sh`가 SQS, DynamoDB, S3, SNS에 트래픽을 전송하는 동안 THEN 시스템은 해당 리소스의 실제 데이터(메시지, 아이템, 객체)를 CONTINUE TO 정상 처리해야 한다

3.4 WHEN CloudFront 및 Route53 알람이 `us-east-1` 리전에 생성되는 동안 THEN 시스템은 해당 알람을 `us-east-1` CloudWatch에서 CONTINUE TO 관리해야 한다
