# Implementation Plan: Extended Resource Monitoring

## Overview

AWS Monitoring Engine에 미구현 12개 리소스 타입(SQS, ECS, MSK, DynamoDB, CloudFront, WAF, Route53, DX, EFS, S3, SageMaker, SNS)을 추가한다. TDD 레드-그린-리팩터링 사이클(거버넌스 §8)을 따르며, 설계 문서의 Correctness Properties 10개에 대한 PBT 테스트를 포함한다.

변경 파일: `common/alarm_registry.py`, `common/__init__.py`, `common/collectors/sqs.py` (NEW), `common/collectors/ecs.py` (NEW), `common/collectors/msk.py` (NEW), `common/collectors/dynamodb.py` (NEW), `common/collectors/cloudfront.py` (NEW), `common/collectors/waf.py` (NEW), `common/collectors/route53.py` (NEW), `common/collectors/dx.py` (NEW), `common/collectors/efs.py` (NEW), `common/collectors/s3.py` (NEW), `common/collectors/sagemaker.py` (NEW), `common/collectors/sns.py` (NEW), `common/alarm_builder.py`, `common/alarm_search.py`, `common/dimension_builder.py`, `common/tag_resolver.py`, `daily_monitor/lambda_handler.py`, `remediation_handler/lambda_handler.py`, `template.yaml`, `tests/test_collectors.py`, `tests/test_alarm_manager.py`, `tests/test_daily_monitor.py`, `tests/test_remediation_handler.py`, `tests/test_pbt_extended_resource_alarm_defs.py` (NEW)

## Tasks

- [x] 1. Alarm Registry 데이터 등록 — 12개 리소스 타입 알람 정의 일괄 추가
  - [x] 1.1 Red: `tests/test_alarm_registry.py`에 12개 신규 리소스 타입 알람 정의 실패 테스트 작성
    - `_get_alarm_defs("SQS")` → 3개 알람 (SQSMessagesVisible, SQSOldestMessage, SQSMessagesSent), namespace `AWS/SQS`, dimension_key `QueueName`
    - `_get_alarm_defs("ECS")` → 3개 알람 (EcsCPU, EcsMemory, RunningTaskCount), namespace `AWS/ECS`, dimension_key `ServiceName`, RunningTaskCount comparison `LessThanThreshold`
    - `_get_alarm_defs("ECS", {"_ecs_launch_type": "FARGATE"})` 와 `_get_alarm_defs("ECS", {"_ecs_launch_type": "EC2"})` 동일 결과 검증
    - `_get_alarm_defs("MSK")` → 4개 알람 (OffsetLag, BytesInPerSec, UnderReplicatedPartitions, ActiveControllerCount), namespace `AWS/Kafka`, dimension_key `"Cluster Name"` (공백 포함), ActiveControllerCount `treat_missing_data="breaching"` + `LessThanThreshold`
    - `_get_alarm_defs("DynamoDB")` → 4개 알람 (DDBReadCapacity, DDBWriteCapacity, ThrottledRequests, DDBSystemErrors), namespace `AWS/DynamoDB`, dimension_key `TableName`
    - `_get_alarm_defs("CloudFront")` → 4개 알람 (CF5xxErrorRate, CF4xxErrorRate, CFRequests, CFBytesDownloaded), namespace `AWS/CloudFront`, dimension_key `DistributionId`, 모든 정의에 `region="us-east-1"`
    - `_get_alarm_defs("WAF")` → 3개 알람 (WAFBlockedRequests, WAFAllowedRequests, WAFCountedRequests), namespace `AWS/WAFV2`, dimension_key `WebACL`
    - `_get_alarm_defs("Route53")` → 1개 알람 (HealthCheckStatus), namespace `AWS/Route53`, dimension_key `HealthCheckId`, `treat_missing_data="breaching"`, `region="us-east-1"`, `LessThanThreshold`
    - `_get_alarm_defs("DX")` → 1개 알람 (ConnectionState), namespace `AWS/DX`, dimension_key `ConnectionId`, `treat_missing_data="breaching"`, `LessThanThreshold`
    - `_get_alarm_defs("EFS")` → 3개 알람 (BurstCreditBalance, PercentIOLimit, EFSClientConnections), namespace `AWS/EFS`, dimension_key `FileSystemId`, BurstCreditBalance `LessThanThreshold`
    - `_get_alarm_defs("S3")` → 4개 알람 (S34xxErrors, S35xxErrors, S3BucketSizeBytes, S3NumberOfObjects), namespace `AWS/S3`, dimension_key `BucketName`, S3BucketSizeBytes/S3NumberOfObjects `needs_storage_type=True` + `period=86400`
    - `_get_alarm_defs("SageMaker")` → 4개 알람 (SMInvocations, SMInvocationErrors, SMModelLatency, SMCPU), namespace `AWS/SageMaker`, dimension_key `EndpointName`
    - `_get_alarm_defs("SNS")` → 2개 알람 (SNSNotificationsFailed, SNSMessagesPublished), namespace `AWS/SNS`, dimension_key `TopicName`
    - `_HARDCODED_METRIC_KEYS` 12개 타입 키 집합 검증
    - `_NAMESPACE_MAP` 12개 타입 네임스페이스 검증
    - `_DIMENSION_KEY_MAP` 12개 타입 디멘션 키 검증
    - `_METRIC_DISPLAY` 모든 신규 메트릭 매핑 존재 검증
    - `_metric_name_to_key()` 신규 매핑 round-trip 검증
    - 실행 → 실패 확인
    - _Requirements: 1.1, 1.2, 2-B.5, 2-B.6, 2-B.7, 3.1, 3.2, 3.3, 4.1, 4.2, 5.1, 5.2, 5.3, 6.1, 6.2, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 9.1, 9.2, 9.3, 10-A.1, 10-A.2, 10-A.3, 11-A.1, 11-A.2, 12.1, 12.2, 13.1–13.8, 18.1–18.4, 19.1–19.12_

  - [x] 1.2 Green: `common/alarm_registry.py`에 12개 알람 정의 리스트 및 매핑 테이블 추가
    - `_SQS_ALARMS` (3개: SQSMessagesVisible, SQSOldestMessage, SQSMessagesSent)
    - `_ECS_ALARMS` (3개: EcsCPU, EcsMemory, RunningTaskCount — `_ecs_launch_type` 무관 동일)
    - `_MSK_ALARMS` (4개: OffsetLag, BytesInPerSec, UnderReplicatedPartitions, ActiveControllerCount — ActiveControllerCount `treat_missing_data="breaching"`)
    - `_DYNAMODB_ALARMS` (4개: DDBReadCapacity, DDBWriteCapacity, ThrottledRequests, DDBSystemErrors)
    - `_CLOUDFRONT_ALARMS` (4개: CF5xxErrorRate, CF4xxErrorRate, CFRequests, CFBytesDownloaded — 모두 `region="us-east-1"`)
    - `_WAF_ALARMS` (3개: WAFBlockedRequests, WAFAllowedRequests, WAFCountedRequests)
    - `_ROUTE53_ALARMS` (1개: HealthCheckStatus — `treat_missing_data="breaching"`, `region="us-east-1"`)
    - `_DX_ALARMS` (1개: ConnectionState — `treat_missing_data="breaching"`)
    - `_EFS_ALARMS` (3개: BurstCreditBalance, PercentIOLimit, EFSClientConnections)
    - `_S3_ALARMS` (4개: S34xxErrors, S35xxErrors, S3BucketSizeBytes, S3NumberOfObjects — `needs_storage_type=True`)
    - `_SAGEMAKER_ALARMS` (4개: SMInvocations, SMInvocationErrors, SMModelLatency, SMCPU)
    - `_SNS_ALARMS` (2개: SNSNotificationsFailed, SNSMessagesPublished)
    - `_get_alarm_defs()` 분기에 12개 타입 추가 (ECS는 `_ecs_launch_type` 무관 동일 반환)
    - `_HARDCODED_METRIC_KEYS`, `_NAMESPACE_MAP`, `_DIMENSION_KEY_MAP` 확장
    - `_METRIC_DISPLAY` 확장 (모든 신규 메트릭)
    - `_metric_name_to_key()` 매핑 확장 (ECS/SageMaker CPUUtilization은 collector 직접 반환으로 충돌 회피)
    - 실행 → 통과 확인
    - _Requirements: 13.1–13.8_

  - [x] 1.3 Refactor: 알람 정의 정리 및 전체 테스트 재실행
    - Route53/DX `treat_missing_data="breaching"` 필드 확인, MSK ActiveControllerCount만 breaching 확인
    - CloudFront/Route53 `region="us-east-1"` 필드 확인
    - S3 `needs_storage_type` 플래그 확인, ECS launch_type 무관 동일 반환 확인
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 13.3, 18.1–18.4_

- [x] 2. Common Constants 확장 — `common/__init__.py`
  - [x] 2.1 Red: `tests/test_common_constants.py`에 상수 검증 실패 테스트 작성
    - `SUPPORTED_RESOURCE_TYPES`에 12개 신규 타입 포함 검증
    - `HARDCODED_DEFAULTS`에 모든 신규 메트릭 키 존재 + 값 검증 (SQSMessagesVisible=1000, EcsCPU=80, OffsetLag=1000, DDBReadCapacity=80, CF5xxErrorRate=1, WAFBlockedRequests=100, HealthCheckStatus=1, ConnectionState=1, BurstCreditBalance=1000000000, S34xxErrors=100, SMInvocations=100000, SNSNotificationsFailed=0 등)
    - `MONITORED_API_EVENTS` CREATE/DELETE/TAG_CHANGE에 신규 이벤트 포함 검증 (CreateQueue, DeleteQueue, TagQueue, UntagQueue, CreateService, DeleteService, CreateCluster, DeleteCluster, CreateTable, DeleteTable, CreateDistribution, DeleteDistribution, CreateWebACL, DeleteWebACL, CreateHealthCheck, DeleteHealthCheck, CreateConnection, DeleteConnection, CreateFileSystem, DeleteFileSystem, CreateBucket, DeleteBucket, CreateEndpoint, DeleteEndpoint, CreateTopic, DeleteTopic)
    - 실행 → 실패 확인
    - _Requirements: 1.6, 1.7, 2-A.1, 2-D.13, 3.7, 3.8, 4.6, 4.7, 5.7, 5.8, 6.7, 6.8, 7.8, 7.9, 8.7, 8.8, 9.7, 9.8, 10-D.10, 10-D.11, 11-C.9, 11-C.10, 12.6, 12.7, 14.1_

  - [x] 2.2 Green: `common/__init__.py` 상수 확장
    - `SUPPORTED_RESOURCE_TYPES`에 `"SQS", "ECS", "MSK", "DynamoDB", "CloudFront", "WAF", "Route53", "DX", "EFS", "S3", "SageMaker", "SNS"` 추가
    - `HARDCODED_DEFAULTS`에 모든 신규 메트릭 기본 임계치 추가 (36개 메트릭 키)
    - `MONITORED_API_EVENTS` CREATE/DELETE/TAG_CHANGE에 신규 이벤트 추가
    - 실행 → 통과 확인
    - _Requirements: 1.6, 1.7, 2-A.1, 2-D.13, 3.7, 3.8, 4.6, 4.7, 5.7, 5.8, 6.7, 6.8, 7.8, 7.9, 8.7, 8.8, 9.7, 9.8, 10-D.10, 10-D.11, 11-C.9, 11-C.10, 12.6, 12.7, 14.1_

- [x] 3. Checkpoint — Alarm Registry + Constants 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Collectors 구현 — 12개 모듈 (common/collectors/)
  - [x] 4.1 Red: `tests/test_collectors.py`에 Simple Collector 실패 테스트 작성 — SQS, DynamoDB, EFS, SNS, Route53, DX
    - **SQS**: `moto`로 SQS mock, `Monitoring=on` 태그 큐 + 태그 없는 큐 생성 → `collect_monitored_resources()` → `Monitoring=on` 큐만 수집, `type == "SQS"`, `id == queue_name` (URL에서 추출) 검증 → `get_metrics(queue_name)` → `SQSMessagesVisible`, `SQSOldestMessage`, `SQSMessagesSent` 키 반환 검증
    - **DynamoDB**: `moto`로 DynamoDB mock, `Monitoring=on` 태그 테이블 + 태그 없는 테이블 생성 → `collect_monitored_resources()` → `Monitoring=on` 테이블만 수집, `type == "DynamoDB"` 검증 → `get_metrics(table_name)` → `DDBReadCapacity`, `DDBWriteCapacity`, `ThrottledRequests`, `DDBSystemErrors` 키 반환 검증
    - **EFS**: `moto`로 EFS mock, `Monitoring=on` 태그 파일시스템 + 태그 없는 파일시스템 생성 → `collect_monitored_resources()` → `Monitoring=on` 파일시스템만 수집, `type == "EFS"` 검증 → `get_metrics(file_system_id)` → `BurstCreditBalance`, `PercentIOLimit`, `EFSClientConnections` 키 반환 검증
    - **SNS**: `moto`로 SNS mock, `Monitoring=on` 태그 토픽 + 태그 없는 토픽 생성 → `collect_monitored_resources()` → `Monitoring=on` 토픽만 수집, `type == "SNS"`, `id == topic_name` (ARN에서 추출) 검증 → `get_metrics(topic_name)` → `SNSNotificationsFailed`, `SNSMessagesPublished` 키 반환 검증
    - **Route53**: `moto`로 Route53 mock, `Monitoring=on` 태그 Health Check + 태그 없는 Health Check 생성 → `collect_monitored_resources()` → `Monitoring=on` Health Check만 수집, `type == "Route53"` 검증 → `get_metrics(health_check_id)` → `HealthCheckStatus` 키 반환 검증
    - **DX**: `moto`로 DirectConnect mock, `Monitoring=on` 태그 연결 + 태그 없는 연결 생성, `connectionState != "available"` 연결 skip 검증 → `collect_monitored_resources()` → `Monitoring=on` + available 연결만 수집, `type == "DX"` 검증 → `get_metrics(connection_id)` → `ConnectionState` 키 반환 검증
    - 모든 메트릭 데이터 없을 때 `None` 반환 검증
    - 실행 → `ImportError`로 실패 확인
    - _Requirements: 1.3, 1.4, 4.3, 4.4, 7.5, 7.6, 8.4, 8.5, 9.4, 9.5, 12.3, 12.4_

  - [x] 4.2 Green: Simple Collector 6개 모듈 생성 — `sqs.py`, `dynamodb.py`, `efs.py`, `sns.py`, `route53.py`, `dx.py`
    - **`common/collectors/sqs.py`**: `_get_sqs_client()` 싱글턴, `collect_monitored_resources()` (list_queues paginator → list_queue_tags → Monitoring=on 필터 → ResourceInfo(type="SQS", id=queue_name)), `get_metrics()` (AWS/SQS, QueueName, ApproximateNumberOfMessagesVisible/ApproximateAgeOfOldestMessage/NumberOfMessagesSent)
    - **`common/collectors/dynamodb.py`**: `_get_dynamodb_client()` 싱글턴, `collect_monitored_resources()` (list_tables paginator → list_tags_of_resource → Monitoring=on 필터 → ResourceInfo(type="DynamoDB", id=table_name)), `get_metrics()` (AWS/DynamoDB, TableName, ConsumedReadCapacityUnits/ConsumedWriteCapacityUnits/ThrottledRequests/SystemErrors)
    - **`common/collectors/efs.py`**: `_get_efs_client()` 싱글턴, `collect_monitored_resources()` (describe_file_systems paginator → Tags 필드에서 Monitoring=on 필터 → ResourceInfo(type="EFS", id=file_system_id)), `get_metrics()` (AWS/EFS, FileSystemId, BurstCreditBalance/PercentIOLimit/ClientConnections)
    - **`common/collectors/sns.py`**: `_get_sns_client()` 싱글턴, `collect_monitored_resources()` (list_topics paginator → list_tags_for_resource → Monitoring=on 필터 → ResourceInfo(type="SNS", id=topic_name — ARN에서 추출)), `get_metrics()` (AWS/SNS, TopicName, NumberOfNotificationsFailed/NumberOfMessagesPublished)
    - **`common/collectors/route53.py`**: `_get_route53_client()` 싱글턴, `collect_monitored_resources()` (list_health_checks paginator → list_tags_for_resource(ResourceType="healthcheck") → Monitoring=on 필터 → ResourceInfo(type="Route53", id=health_check_id)), `get_metrics()` (AWS/Route53, HealthCheckId, HealthCheckStatus — us-east-1 고정)
    - **`common/collectors/dx.py`**: `_get_dx_client()` 싱글턴, `collect_monitored_resources()` (describe_connections → describe_tags → connectionState=="available" + Monitoring=on 필터 → ResourceInfo(type="DX", id=connection_id)), `get_metrics()` (AWS/DX, ConnectionId, ConnectionState)
    - 실행 → 통과 확인
    - _Requirements: 1.3, 1.4, 4.3, 4.4, 7.5, 7.6, 8.4, 8.5, 9.4, 9.5, 12.3, 12.4_

  - [x] 4.3 Red: `tests/test_collectors.py`에 Compound Dimension Collector 실패 테스트 작성 — ECS, WAF, S3, SageMaker
    - **ECS**: `moto`로 ECS mock, FARGATE/EC2 서비스 혼합 생성, `Monitoring=on` 태그 서비스 + 태그 없는 서비스 → `collect_monitored_resources()` → `Monitoring=on` 서비스만 수집, `type == "ECS"` 검증 → `_ecs_launch_type` Internal_Tag (FARGATE/EC2) 설정 검증 → `_cluster_name` Internal_Tag 설정 검증 → `get_metrics(service_name, resource_tags)` → `EcsCPU`, `EcsMemory`, `RunningTaskCount` 키 반환 검증 → ClusterName + ServiceName Compound_Dimension 사용 검증
    - **WAF**: `moto`로 WAFv2 mock, `Monitoring=on` 태그 WebACL + 태그 없는 WebACL 생성 → `collect_monitored_resources()` → `Monitoring=on` WebACL만 수집, `type == "WAF"` 검증 → `_waf_rule` Internal_Tag 기본값 `"ALL"` 검증 → `get_metrics(web_acl_name, resource_tags)` → `WAFBlockedRequests`, `WAFAllowedRequests`, `WAFCountedRequests` 키 반환 검증 → WebACL + Rule Compound_Dimension 사용 검증
    - **S3**: `moto`로 S3 mock, `Monitoring=on` 태그 버킷 + 태그 없는 버킷 생성 → `collect_monitored_resources()` → `Monitoring=on` 버킷만 수집, `type == "S3"` 검증 → `_storage_type` Internal_Tag 기본값 `"StandardStorage"` 검증 → `get_metrics(bucket_name, resource_tags)` → `S34xxErrors`, `S35xxErrors`, `S3BucketSizeBytes`, `S3NumberOfObjects` 키 반환 검증 → 4xxErrors/5xxErrors 데이터 미반환 시 warning 로그 검증
    - **SageMaker**: `moto`로 SageMaker mock, InService 엔드포인트 + 비-InService 엔드포인트 생성, `Monitoring=on` 태그 → `collect_monitored_resources()` → InService + Monitoring=on 엔드포인트만 수집, `type == "SageMaker"` 검증 → 학습 작업 제외 검증 → `_variant_name` Internal_Tag 설정 검증 → `get_metrics(endpoint_name, resource_tags)` → `SMInvocations`, `SMInvocationErrors`, `SMModelLatency`, `SMCPU` 키 반환 검증 → EndpointName + VariantName Compound_Dimension 사용 검증
    - 실행 → `ImportError`로 실패 확인
    - _Requirements: 2-C.8, 2-C.9, 2-C.10, 2-C.11, 2-C.12, 6.3, 6.4, 6.5, 10-B.4, 10-B.5, 10-B.6, 10-B.7, 10-C.8, 11-B.3, 11-B.4, 11-B.5, 11-B.6, 11-B.7_

  - [x] 4.4 Green: Compound Dimension Collector 4개 모듈 생성 — `ecs.py`, `waf.py`, `s3.py`, `sagemaker.py`
    - **`common/collectors/ecs.py`**: `_get_ecs_client()` 싱글턴, `collect_monitored_resources()` (list_clusters → list_services paginator → describe_services 배치 → list_tags_for_resource → Monitoring=on 필터 → `_ecs_launch_type` + `_cluster_name` Internal_Tag 설정 → ResourceInfo(type="ECS", id=service_name)), `get_metrics()` (AWS/ECS, ClusterName+ServiceName Compound_Dimension, CPUUtilization→EcsCPU/MemoryUtilization→EcsMemory/RunningTaskCount)
    - **`common/collectors/waf.py`**: `_get_wafv2_client()` 싱글턴, `collect_monitored_resources()` (list_web_acls(Scope="REGIONAL") → list_tags_for_resource → Monitoring=on 필터 → `_waf_rule="ALL"` Internal_Tag 설정 → ResourceInfo(type="WAF", id=web_acl_name)), `get_metrics()` (AWS/WAFV2, WebACL+Rule Compound_Dimension, BlockedRequests/AllowedRequests/CountedRequests)
    - **`common/collectors/s3.py`**: `_get_s3_client()` 싱글턴, `collect_monitored_resources()` (list_buckets → get_bucket_tagging → Monitoring=on 필터 → `_storage_type="StandardStorage"` Internal_Tag 설정 → ResourceInfo(type="S3", id=bucket_name)), `get_metrics()` (AWS/S3, BucketName+StorageType Compound_Dimension, 4xxErrors/5xxErrors — 데이터 미반환 시 warning 로그, BucketSizeBytes/NumberOfObjects)
    - **`common/collectors/sagemaker.py`**: `_get_sagemaker_client()` 싱글턴, `collect_monitored_resources()` (list_endpoints(StatusEquals="InService") paginator → list_tags → Monitoring=on 필터 → describe_endpoint → `_variant_name` Internal_Tag 설정 → ResourceInfo(type="SageMaker", id=endpoint_name) — 학습 작업 제외), `get_metrics()` (AWS/SageMaker, EndpointName+VariantName Compound_Dimension, Invocations/InvocationErrors/ModelLatency/CPUUtilization→SMCPU)
    - 실행 → 통과 확인
    - _Requirements: 2-C.8, 2-C.9, 2-C.10, 2-C.11, 2-C.12, 6.3, 6.4, 6.5, 10-B.4, 10-B.5, 10-B.6, 10-B.7, 10-C.8, 11-B.3, 11-B.4, 11-B.5, 11-B.6, 11-B.7_

  - [x] 4.5 Red: `tests/test_collectors.py`에 Special Collector 실패 테스트 작성 — MSK, CloudFront
    - **MSK**: `moto`로 Kafka mock, `Monitoring=on` 태그 클러스터 + 태그 없는 클러스터 생성 → `collect_monitored_resources()` → `Monitoring=on` 클러스터만 수집, `type == "MSK"` 검증 → `get_metrics(cluster_name)` → `OffsetLag`, `BytesInPerSec`, `UnderReplicatedPartitions`, `ActiveControllerCount` 키 반환 검증 → 디멘션 키 `"Cluster Name"` (공백 포함) 사용 검증
    - **CloudFront**: `moto`로 CloudFront mock, `Monitoring=on` 태그 배포 + 태그 없는 배포 생성 → `collect_monitored_resources()` → `Monitoring=on` 배포만 수집, `type == "CloudFront"` 검증 → `get_metrics(distribution_id)` → `CF5xxErrorRate`, `CF4xxErrorRate`, `CFRequests`, `CFBytesDownloaded` 키 반환 검증 → us-east-1 리전 고정 검증
    - 실행 → `ImportError`로 실패 확인
    - _Requirements: 3.4, 3.5, 5.4, 5.5_

  - [x] 4.6 Green: Special Collector 2개 모듈 생성 — `msk.py`, `cloudfront.py`
    - **`common/collectors/msk.py`**: `_get_kafka_client()` 싱글턴, `collect_monitored_resources()` (list_clusters_v2 paginator → Tags 필드에서 Monitoring=on 필터 → ResourceInfo(type="MSK", id=cluster_name)), `get_metrics()` (AWS/Kafka, `"Cluster Name"` 디멘션 — 공백 포함, SumOffsetLag/BytesInPerSec/UnderReplicatedPartitions/ActiveControllerCount)
    - **`common/collectors/cloudfront.py`**: `_get_cloudfront_client()` 싱글턴, `collect_monitored_resources()` (list_distributions paginator → list_tags_for_resource → Monitoring=on 필터 → ResourceInfo(type="CloudFront", id=distribution_id)), `get_metrics()` (AWS/CloudFront, DistributionId 디멘션, us-east-1 고정, 5xxErrorRate/4xxErrorRate/Requests/BytesDownloaded)
    - 실행 → 통과 확인
    - _Requirements: 3.4, 3.5, 5.4, 5.5_

  - [x] 4.7 Refactor: 12개 Collector 코드 정리 및 전체 테스트 재실행
    - 공통 패턴 (`query_metric` 헬퍼) 중복 확인 및 정리
    - 로깅 메시지에 resource_id 컨텍스트 포함 확인
    - ECS/SageMaker CPUUtilization → EcsCPU/SMCPU 키 직접 반환 확인 (기존 CPU 매핑 충돌 회피)
    - S3 Request_Metrics warning 로그 확인
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 1.3, 1.4, 2-C.8–12, 3.4, 3.5, 4.3, 4.4, 5.4, 5.5, 6.3–6.5, 7.5, 7.6, 8.4, 8.5, 9.4, 9.5, 10-B.4–7, 10-C.8, 11-B.3–7, 12.3, 12.4_

- [x] 5. Checkpoint — 12개 Collector 구현 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. CloudTrail 이벤트 + Remediation Handler — `remediation_handler/lambda_handler.py`
  - [x] 6.1 Red: `tests/test_remediation_handler.py`에 12개 신규 리소스 이벤트 실패 테스트 작성
    - `_API_MAP`에 신규 이벤트 매핑 존재 검증: CreateQueue, DeleteQueue, TagQueue, UntagQueue, CreateService, DeleteService, CreateCluster(MSK), DeleteCluster(MSK), CreateTable, DeleteTable, CreateDistribution, DeleteDistribution, CreateWebACL, DeleteWebACL, CreateHealthCheck, DeleteHealthCheck, CreateConnection, DeleteConnection, CreateFileSystem, DeleteFileSystem, CreateBucket, DeleteBucket, CreateEndpoint(SageMaker), DeleteEndpoint(SageMaker), CreateTopic, DeleteTopic
    - 각 이벤트별 `(resource_type, id_extractor)` 매핑 검증
    - TagResource/UntagResource ARN 기반 서비스 판별 로직에 12개 신규 타입 추가 검증 (ECS ARN → "ECS", MSK ARN → "MSK", DynamoDB ARN → "DynamoDB" 등)
    - ID 추출 실패 시 에러 로깅 + 이벤트 skip 검증
    - 실행 → 실패 확인
    - _Requirements: 14.1, 14.2, 14.4_

  - [x] 6.2 Green: Remediation Handler에 12개 신규 리소스 이벤트 매핑 추가
    - `_API_MAP`에 SQS/ECS/MSK/DynamoDB/CloudFront/WAF/Route53/DX/EFS/S3/SageMaker/SNS 이벤트 매핑 추가
    - 각 리소스별 `_extract_*_ids()` ID 추출 함수 구현
    - `TagResource`/`UntagResource`: 기존 `"MULTI"` 핸들러의 ARN 기반 서비스 판별에 12개 신규 타입 추가
    - SQS TagQueue/UntagQueue 전용 핸들러 추가
    - 실행 → 통과 확인
    - _Requirements: 14.1, 14.2, 14.4_

  - [x] 6.3 Refactor: Remediation Handler 정리 및 전체 테스트 재실행
    - ID 추출 함수 네이밍 일관성 확인
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 14.2_

- [x] 7. Tag Resolver 확장 — `common/tag_resolver.py`
  - [x] 7.1 Red: `tests/test_collectors.py`에 12개 신규 리소스 태그 조회 실패 테스트 작성
    - `get_resource_tags(resource_id, "SQS")` → SQS 태그 반환 검증
    - `get_resource_tags(resource_id, "ECS")` → ECS 태그 반환 검증
    - `get_resource_tags(resource_id, "MSK")` → MSK 태그 반환 검증
    - `get_resource_tags(resource_id, "DynamoDB")` → DynamoDB 태그 반환 검증
    - `get_resource_tags(resource_id, "CloudFront")` → CloudFront 태그 반환 검증
    - `get_resource_tags(resource_id, "WAF")` → WAF 태그 반환 검증
    - `get_resource_tags(resource_id, "Route53")` → Route53 태그 반환 검증
    - `get_resource_tags(resource_id, "DX")` → DX 태그 반환 검증
    - `get_resource_tags(resource_id, "EFS")` → EFS 태그 반환 검증
    - `get_resource_tags(resource_id, "S3")` → S3 태그 반환 검증
    - `get_resource_tags(resource_id, "SageMaker")` → SageMaker 태그 반환 검증
    - `get_resource_tags(resource_id, "SNS")` → SNS 태그 반환 검증
    - 실행 → 미지원 타입으로 빈 dict 반환 확인
    - _Requirements: 1.3, 2-C.8, 3.4, 4.3, 5.4, 6.3, 7.5, 8.4, 9.4, 10-B.4, 11-B.3, 12.3_

  - [x] 7.2 Green: `common/tag_resolver.py`의 `get_resource_tags()`에 12개 신규 타입 분기 추가
    - SQS: `sqs` 클라이언트 `list_queue_tags(QueueUrl)`
    - ECS: `ecs` 클라이언트 `list_tags_for_resource(resourceArn)`
    - MSK: `kafka` 클라이언트 `list_tags_for_resource(ResourceArn)`
    - DynamoDB: `dynamodb` 클라이언트 `list_tags_of_resource(ResourceArn)`
    - CloudFront: `cloudfront` 클라이언트 `list_tags_for_resource(Resource)`
    - WAF: `wafv2` 클라이언트 `list_tags_for_resource(ResourceARN)`
    - Route53: `route53` 클라이언트 `list_tags_for_resource(ResourceType, ResourceId)`
    - DX: `directconnect` 클라이언트 `describe_tags(resourceArns)`
    - EFS: `efs` 클라이언트 `describe_file_systems()` → Tags 필드
    - S3: `s3` 클라이언트 `get_bucket_tagging(Bucket)`
    - SageMaker: `sagemaker` 클라이언트 `list_tags(ResourceArn)`
    - SNS: `sns` 클라이언트 `list_tags_for_resource(ResourceArn)`
    - 실행 → 통과 확인
    - _Requirements: 1.3, 2-C.8, 3.4, 4.3, 5.4, 6.3, 7.5, 8.4, 9.4, 10-B.4, 11-B.3, 12.3_

- [x] 8. Checkpoint — CloudTrail + Tag Resolver 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [-] 9. Daily Monitor 통합 — `daily_monitor/lambda_handler.py`
  - [x] 9.1 Red: `tests/test_daily_monitor.py`에 12개 신규 Collector 통합 실패 테스트 작성
    - `_COLLECTOR_MODULES`에 12개 신규 모듈 포함 검증
    - `alive_checkers`에 12개 신규 타입 키 존재 + callable 검증
    - "낮을수록 위험" 메트릭 세트에 `RunningTaskCount`, `ActiveControllerCount`, `HealthCheckStatus`, `ConnectionState`, `BurstCreditBalance` 추가 검증
    - 실행 → 실패 확인
    - _Requirements: 1.5, 2-A.4, 3.6, 4.5, 5.6, 6.6, 7.7, 8.6, 9.6, 10-D.9, 11-C.8, 12.5, 16.1, 16.3_

  - [x] 9.2 Green: Daily Monitor에 12개 신규 Collector 등록
    - 12개 import 추가: `sqs`, `ecs`, `msk`, `dynamodb`, `cloudfront`, `waf`, `route53`, `dx`, `efs`, `s3`, `sagemaker`, `sns`
    - `_COLLECTOR_MODULES`에 12개 모듈 추가
    - `alive_checkers`에 12개 타입별 `_find_alive_*` 함수 등록
    - 12개 `_find_alive_*` 함수 구현 (각 리소스 타입별 존재 확인 API 호출)
    - `_process_resource()` "낮을수록 위험" 메트릭 세트에 `RunningTaskCount`, `ActiveControllerCount`, `HealthCheckStatus`, `ConnectionState`, `BurstCreditBalance` 추가
    - 실행 → 통과 확인
    - _Requirements: 1.5, 2-A.4, 3.6, 4.5, 5.6, 6.6, 7.7, 8.6, 9.6, 10-D.9, 11-C.8, 12.5, 16.1, 16.3_

  - [x] 9.3 Refactor: Daily Monitor 정리 및 전체 테스트 재실행
    - `_find_alive_*` 함수 패턴 일관성 확인
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 16.2_

- [x] 10. Checkpoint — Daily Monitor 통합 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. template.yaml IAM + EventBridge 확장
  - [x] 11.1 Red: `template.yaml` 변경 사항 검증 테스트 작성 (수동 검증 또는 CFN lint)
    - Daily Monitor Role에 12개 신규 리소스 Describe/List/Tags API 권한 추가 필요 확인 (sqs:ListQueues, sqs:ListQueueTags, ecs:ListClusters, ecs:ListServices, ecs:DescribeServices, ecs:ListTagsForResource, kafka:ListClustersV2, kafka:ListTagsForResource, dynamodb:ListTables, dynamodb:ListTagsOfResource, dynamodb:DescribeTable, cloudfront:ListDistributions, cloudfront:ListTagsForResource, wafv2:ListWebACLs, wafv2:ListTagsForResource, route53:ListHealthChecks, route53:ListTagsForResource, directconnect:DescribeConnections, directconnect:DescribeTags, elasticfilesystem:DescribeFileSystems, s3:ListAllMyBuckets, s3:GetBucketTagging, s3:GetBucketLocation, sagemaker:ListEndpoints, sagemaker:DescribeEndpoint, sagemaker:ListTags, sns:ListTopics, sns:ListTagsForResource)
    - Remediation Handler Role에 12개 신규 리소스 생명주기 API 권한 추가 필요 확인 (sqs:ListQueueTags, sqs:GetQueueUrl, ecs:DescribeServices, ecs:ListTagsForResource, kafka:ListTagsForResource, dynamodb:ListTagsOfResource, cloudfront:ListTagsForResource, wafv2:ListTagsForResource, route53:ListTagsForResource, directconnect:DescribeTags, elasticfilesystem:DescribeFileSystems, s3:GetBucketTagging, sagemaker:ListTags, sns:ListTagsForResource)
    - CloudTrailModifyRule EventPattern에 신규 source + eventName 추가 필요 확인
    - _Requirements: 14.3, 15.1, 15.2, 15.3_

  - [x] 11.2 Green: `template.yaml` IAM 및 EventBridge 확장
    - Daily Monitor Role 추가 권한: SQS/ECS/MSK/DynamoDB/CloudFront/WAF/Route53/DX/EFS/S3/SageMaker/SNS Describe/List/Tags API
    - Remediation Handler Role 추가 권한: 12개 신규 리소스 태그 조회 + 생명주기 API
    - CloudTrailModifyRule EventPattern source에 `aws.sqs`, `aws.ecs`, `aws.kafka`, `aws.dynamodb`, `aws.cloudfront`, `aws.wafv2`, `aws.route53`, `aws.directconnect`, `aws.elasticfilesystem`, `aws.s3`, `aws.sagemaker`, `aws.sns` 추가
    - CloudTrailModifyRule EventPattern eventName에 신규 26개 이벤트 추가 (CreateQueue, DeleteQueue, TagQueue, UntagQueue, CreateService, DeleteService, CreateCluster, DeleteCluster, CreateTable, DeleteTable, CreateDistribution, DeleteDistribution, CreateWebACL, DeleteWebACL, CreateHealthCheck, DeleteHealthCheck, CreateConnection, DeleteConnection, CreateFileSystem, DeleteFileSystem, CreateBucket, DeleteBucket, CreateEndpoint, DeleteEndpoint, CreateTopic, DeleteTopic)
    - 실행 → 통과 확인
    - _Requirements: 14.3, 15.1, 15.2, 15.3_

- [x] 12. Checkpoint — template.yaml 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Alarm Manager 확장 — treat_missing_data + Compound Dimension + region 필드
  - [x] 13.1 Red: `tests/test_alarm_manager.py`에 treat_missing_data, Compound Dimension, region 실패 테스트 작성
    - Route53/DX 알람 생성 시 `put_metric_alarm`의 `TreatMissingData` 파라미터가 `"breaching"`인지 검증
    - MSK ActiveControllerCount 알람 생성 시 `TreatMissingData`가 `"breaching"`인지 검증
    - 기존 리소스 알람 생성 시 `TreatMissingData`가 `"missing"` (기본값)인지 검증
    - ECS 알람 생성 시 `_build_dimensions()`가 `ServiceName` + `ClusterName` 2개 디멘션 반환 검증
    - WAF 알람 생성 시 `_build_dimensions()`가 `WebACL` + `Rule` 2개 디멘션 반환 검증
    - S3 알람 생성 시 `_build_dimensions()`가 `BucketName` + `StorageType` 2개 디멘션 반환 검증 (`needs_storage_type=True`인 경우만)
    - SageMaker 알람 생성 시 `_build_dimensions()`가 `EndpointName` + `VariantName` 2개 디멘션 반환 검증
    - Compound_Dimension 보조 디멘션 누락 시 primary 1개만 반환 + warning 로그 검증
    - CloudFront/Route53 알람 생성 시 `region="us-east-1"` CloudWatch 클라이언트 사용 검증
    - 실행 → 실패 확인
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 18.1, 18.2, 18.3, 18.4_

  - [x] 13.2 Green: `common/alarm_builder.py` treat_missing_data + region 지원 + `common/dimension_builder.py` Compound Dimension 분기 추가
    - `_create_single_alarm()` / `_create_standard_alarm()` / `_recreate_standard_alarm()`: `alarm_def.get("treat_missing_data", "missing")`을 `TreatMissingData` 파라미터로 전달
    - `_create_single_alarm()`: `alarm_def.get("region")` 확인 → 해당 리전 CloudWatch 클라이언트 사용
    - `_build_dimensions()`: ECS 분기 (ServiceName + ClusterName from `_cluster_name`), WAF 분기 (WebACL + Rule from `_waf_rule`), S3 분기 (BucketName + StorageType from `_storage_type` — `needs_storage_type=True`인 경우만), SageMaker 분기 (EndpointName + VariantName from `_variant_name`)
    - 보조 디멘션 누락 시 primary 1개만 반환 + warning 로그
    - 실행 → 통과 확인
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 18.1, 18.2, 18.3, 18.4_

  - [x] 13.3 Refactor: Alarm Builder/Dimension Builder 정리 및 전체 테스트 재실행
    - 기존 알람의 `TreatMissingData="missing"` 동작 변경 없음 확인
    - 기존 OpenSearch Compound_Dimension 동작 변경 없음 확인
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 17.5, 18.4_

- [x] 14. Alarm Search 확장 — 신규 리소스 타입 접두사
  - [x] 14.1 Red: `tests/test_alarm_search.py`에 신규 타입 알람 검색 실패 테스트 작성
    - `_find_alarms_for_resource(resource_id)` (resource_type 미지정) 호출 시 기본 폴백 목록에 12개 신규 타입 포함 검증
    - `_find_alarms_for_resource(resource_id, "SQS")` → `"[SQS] "` 접두사 검색 검증
    - 12개 신규 타입 각각에 대해 `"[{type}] "` 접두사 검색 검증
    - 실행 → 실패 확인
    - _Requirements: 16.2_

  - [x] 14.2 Green: `common/alarm_search.py`의 `_find_alarms_for_resource()` 기본 폴백 목록에 12개 신규 타입 추가
    - 기본 `type_prefixes` 폴백 리스트에 `"SQS", "ECS", "MSK", "DynamoDB", "CloudFront", "WAF", "Route53", "DX", "EFS", "S3", "SageMaker", "SNS"` 추가
    - 실행 → 통과 확인
    - _Requirements: 16.2_

- [x] 15. Checkpoint — Alarm Manager + Search 확장 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 16. PBT — 설계 문서 Correctness Properties 10개
  - [x]* 16.1 PBT Property 1: Alarm Definition Structural Correctness
    - **Property 1: Alarm Definition Structural Correctness**
    - **Validates: Requirements 1.1, 1.2, 2-B.5, 2-B.6, 2-B.7, 3.1, 3.2, 4.1, 4.2, 5.1, 5.2, 6.1, 6.2, 7.1, 7.2, 8.1, 8.2, 9.1, 9.2, 9.3, 10-A.1, 10-A.2, 11-A.1, 11-A.2, 12.1, 12.2, 13.1, 13.2**
    - 파일: `tests/test_pbt_extended_resource_alarm_defs.py`
    - 12개 신규 resource_type 중 랜덤 선택 + 랜덤 resource_tags 생성
    - `_get_alarm_defs(resource_type, resource_tags)` 반환값이 non-empty이고 모든 정의가 올바른 namespace, dimension_key, metric set, comparison direction을 갖는지 검증

  - [x]* 16.2 PBT Property 2: Registry Mapping Table Completeness
    - **Property 2: Registry Mapping Table Completeness**
    - **Validates: Requirements 1.6, 1.7, 2-A.1, 2-D.13, 3.7, 3.8, 4.6, 4.7, 5.7, 5.8, 6.7, 6.8, 7.8, 7.9, 8.7, 8.8, 9.7, 9.8, 10-D.10, 10-D.11, 11-C.9, 11-C.10, 12.6, 12.7, 13.4, 13.5, 13.6, 13.7**
    - 파일: `tests/test_pbt_extended_resource_alarm_defs.py`
    - 12개 신규 타입의 모든 alarm_def에 대해 `_HARDCODED_METRIC_KEYS`, `_NAMESPACE_MAP`, `_DIMENSION_KEY_MAP`, `_METRIC_DISPLAY`, `HARDCODED_DEFAULTS` 매핑 존재 검증

  - [x]* 16.3 PBT Property 3: Tag-Based Collector Filtering (Monitoring=on)
    - **Property 3: Tag-Based Collector Filtering (Monitoring=on)**
    - **Validates: Requirements 1.3, 2-C.8, 3.4, 4.3, 5.4, 6.3, 7.5, 8.4, 9.4, 10-B.4, 11-B.3, 12.3**
    - 파일: `tests/test_pbt_extended_resource_alarm_defs.py`
    - 랜덤 리소스 집합 (Monitoring=on/off 혼합) 생성 → moto mock → 12개 tag-based collector가 정확히 Monitoring=on 리소스만 반환하는지 검증

  - [x]* 16.4 PBT Property 4: ECS _ecs_launch_type Alarm Invariance
    - **Property 4: ECS _ecs_launch_type Alarm Invariance**
    - **Validates: Requirements 2-A.2, 2-A.3, 13.3**
    - 파일: `tests/test_pbt_extended_resource_alarm_defs.py`
    - `_ecs_launch_type` 값 `{"FARGATE", "EC2"}` 중 랜덤 선택 + 랜덤 resource_tags → `_get_alarm_defs("ECS", tags)`가 항상 동일한 알람 정의 `{EcsCPU, EcsMemory, RunningTaskCount}`를 반환하는지 검증

  - [x]* 16.5 PBT Property 5: Compound Dimension Construction (ECS, WAF, S3, SageMaker)
    - **Property 5: Compound Dimension Construction**
    - **Validates: Requirements 2-B.6, 2-C.10, 6.2, 6.4, 10-A.2, 10-A.3, 10-B.5, 11-A.2, 11-B.5, 17.1, 17.2, 17.3, 17.4, 17.5**
    - 파일: `tests/test_pbt_extended_resource_alarm_defs.py`
    - 랜덤 resource_id와 랜덤 Internal_Tag 값 생성 → `_build_dimensions()`가 ECS(ServiceName+ClusterName)/WAF(WebACL+Rule)/S3(BucketName+StorageType)/SageMaker(EndpointName+VariantName) 각각에 대해 올바른 compound dimension을 생성하는지 검증. 보조 디멘션 누락 시 primary dimension만 반환하는지 검증

  - [x]* 16.6 PBT Property 6: treat_missing_data=breaching for Route53/DX/MSK
    - **Property 6: treat_missing_data=breaching**
    - **Validates: Requirements 7.3, 8.3, 3.3, 18.1, 18.2, 18.3, 18.4**
    - 파일: `tests/test_pbt_extended_resource_alarm_defs.py`
    - `_ROUTE53_ALARMS`, `_DX_ALARMS` 모든 정의에 `treat_missing_data="breaching"` 존재 검증
    - `_MSK_ALARMS`에서 `ActiveControllerCount`만 `treat_missing_data="breaching"` 검증
    - 다른 9개 타입 알람 정의에는 `treat_missing_data` 없거나 `"missing"` 검증

  - [x]* 16.7 PBT Property 7: metric_name_to_key Round Trip
    - **Property 7: metric_name_to_key Round Trip**
    - **Validates: Requirements 13.8**
    - 파일: `tests/test_pbt_extended_resource_alarm_defs.py`
    - 12개 신규 타입의 모든 alarm_def에 대해 `_metric_name_to_key(alarm_def["metric_name"]) == alarm_def["metric"]` round-trip 검증
    - ECS/SageMaker CPUUtilization은 collector 직접 반환이므로 제외

  - [x]* 16.8 PBT Property 8: Alive Checker Coverage
    - **Property 8: Alive Checker Coverage**
    - **Validates: Requirements 16.1, 16.3**
    - 파일: `tests/test_pbt_extended_resource_alarm_defs.py`
    - 12개 신규 resource_type에 대해 `alive_checkers` dict에 해당 키 존재 + callable 검증

  - [x]* 16.9 PBT Property 9: CloudFront/Route53 us-east-1 Region
    - **Property 9: CloudFront/Route53 us-east-1 Region**
    - **Validates: Requirements 5.3, 7.4**
    - 파일: `tests/test_pbt_extended_resource_alarm_defs.py`
    - `_CLOUDFRONT_ALARMS`, `_ROUTE53_ALARMS` 모든 정의에 `region="us-east-1"` 존재 검증
    - 다른 10개 타입 알람 정의에는 `region` 필드 없는지 검증

  - [x]* 16.10 PBT Property 10: Lower-is-Dangerous Threshold Direction Consistency
    - **Property 10: Lower-is-Dangerous Threshold Direction Consistency**
    - **Validates: Requirements 2-B.7, 3.3, 7.1, 8.1, 9.3**
    - 파일: `tests/test_pbt_extended_resource_alarm_defs.py`
    - LessThanThreshold 메트릭 (RunningTaskCount, ActiveControllerCount, HealthCheckStatus, ConnectionState, BurstCreditBalance)에 대해 랜덤 current_value와 threshold 생성 → 비교 방향 올바른지 검증

- [x] 17. Final checkpoint — 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- `*` 표시된 태스크는 선택적이며 빠른 MVP를 위해 건너뛸 수 있음
- 각 태스크는 특정 요구사항을 참조하여 추적 가능
- TDD 레드-그린-리팩터링 사이클을 모듈별로 반복
- PBT 테스트는 설계 문서의 Correctness Properties 10개를 모두 커버
- ECS/SageMaker `CPUUtilization` → `EcsCPU`/`SMCPU` 키로 직접 반환하여 기존 `CPU` 매핑 충돌 회피
- MSK 디멘션 키 `"Cluster Name"`은 공백 포함 (AWS 공식 문서 기준)
- CloudFront/Route53 메트릭은 us-east-1에서만 발행 → alarm_def에 `region="us-east-1"` 필드 추가
- Route53/DX/MSK ActiveControllerCount는 `treat_missing_data="breaching"` (기존 VPN 패턴 재사용)
- ECS는 단일 모듈에서 FARGATE/EC2 두 launch type을 수집하며, `_ecs_launch_type` Internal_Tag로 구분하되 알람 정의는 동일
- S3 4xxErrors/5xxErrors는 Request_Metrics 활성화 필요, 데이터 미반환 시 warning 로그
- SageMaker는 InService 추론 엔드포인트만 수집, 학습 작업 제외
- WAF `_waf_rule` Internal_Tag 기본값 `"ALL"`
- Collector 그룹: Simple(SQS, DynamoDB, EFS, SNS, Route53, DX) → Compound(ECS, WAF, S3, SageMaker) → Special(MSK, CloudFront)
