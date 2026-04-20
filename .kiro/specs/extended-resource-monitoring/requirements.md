# Requirements Document

## Introduction

AWS Monitoring Engine에 12개 신규 리소스 타입을 추가한다.
§11 체크리스트를 준수하며 기존 ElastiCache/NAT/Lambda/VPN/APIGW/OpenSearch 패턴을 따른다.
ECS/Fargate는 _ecs_launch_type Internal_Tag로 FARGATE/EC2 분기를 지원한다.
S3는 요청 메트릭(Request Metrics)이 버킷 레벨 설정으로 활성화되어야 하는 특수 사항이 있다.
SageMaker는 추론 엔드포인트만 모니터링 대상으로 한다 (학습 작업 제외).

## Glossary

- **Monitoring_Engine**: CloudWatch 알람 자동 생성/동기화 전체 시스템
- **Collector**: CollectorProtocol 구현체, 리소스 수집 및 메트릭 조회
- **Alarm_Registry**: 리소스별 알람 정의/매핑 데이터 모듈
- **Daily_Monitor**: 매일 1회 알람 동기화 및 임계치 비교 Lambda
- **Remediation_Handler**: CloudTrail 이벤트 기반 생명주기 대응 Lambda
- **Tag_Based_Collection**: Monitoring=on 태그 리소스만 수집하는 표준 방식
- **Miss_Data_Alarm**: TreatMissingData=breaching 설정 알람
- **Compound_Dimension**: 복수 디멘션 키 조합 (예: ClusterName+ServiceName, WebACL+Rule)
- **Internal_Tag**: Collector가 설정하는 `_` 접두사 내부 태그 (예: `_ecs_launch_type`)
- **Request_Metrics**: S3 버킷 레벨에서 별도 활성화해야 하는 요청 기반 CloudWatch 메트릭
- **Inference_Endpoint**: SageMaker 실시간 추론 엔드포인트 (학습 작업과 구분)

## Requirements


### Requirement 1: SQS 모니터링

**User Story:** As a 운영자, I want SQS 큐의 메시지 체류량, 메시지 연령, 트래픽을 모니터링하고 싶다, so that 큐 적체와 소비자 지연을 즉시 감지할 수 있다.

#### Acceptance Criteria

1. WHEN Monitoring=on 태그가 있는 SQS 큐가 존재하면, THE Alarm_Registry SHALL resource_type SQS에 대해 SQSMessagesVisible(>1000), SQSOldestMessage(>300s), SQSMessagesSent(traffic) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL SQS 알람에 네임스페이스 AWS/SQS, 디멘션 키 QueueName을 사용한다
3. WHEN SQS Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 SQS 큐 목록을 반환한다
4. WHEN SQS Collector가 메트릭을 조회하면, THE Collector SHALL ApproximateNumberOfMessagesVisible, ApproximateAgeOfOldestMessage, NumberOfMessagesSent 값을 반환한다
5. THE Daily_Monitor SHALL SQS Collector를 _COLLECTOR_MODULES에 포함한다
6. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 SQS를 추가한다
7. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 SQSMessagesVisible=1000, SQSOldestMessage=300, SQSMessagesSent=10000을 추가한다


### Requirement 2: ECS/Fargate 모니터링

**User Story:** As a 운영자, I want ECS 서비스의 CPU, 메모리 사용률과 실행 중인 태스크 수를 모니터링하고 싶다, so that 컨테이너 리소스 포화와 서비스 가용성 저하를 감지할 수 있다.

#### Acceptance Criteria

##### 2-A. 공통 구조 (APIGW _api_type 패턴 준용)

1. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 단일 resource_type "ECS"를 추가한다
2. THE ECS Collector SHALL 수집한 각 서비스의 ResourceInfo tags에 Internal_Tag `_ecs_launch_type`을 설정한다 (값: "FARGATE", "EC2")
3. THE Alarm_Registry SHALL _get_alarm_defs("ECS", resource_tags)에서 `_ecs_launch_type` Internal_Tag 값에 관계없이 동일한 알람 정의 리스트를 반환한다
4. THE Daily_Monitor SHALL ECS Collector를 _COLLECTOR_MODULES에 단일 모듈로 포함한다

##### 2-B. 알람 정의

5. WHEN Monitoring=on 태그가 있는 ECS 서비스가 존재하면, THE Alarm_Registry SHALL resource_type ECS에 대해 EcsCPU(>80%), EcsMemory(>80%), RunningTaskCount(<1) 알람 정의를 제공한다
6. THE Alarm_Registry SHALL ECS 알람에 네임스페이스 AWS/ECS, Compound_Dimension으로 ClusterName과 ServiceName을 사용한다
7. THE RunningTaskCount 알람 정의 SHALL comparison을 LessThanThreshold로 설정한다

##### 2-C. Collector 구현

8. WHEN ECS Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 ECS 서비스 목록을 반환한다
9. THE ECS Collector SHALL 서비스 수집 시 해당 서비스의 launchType을 조회하여 `_ecs_launch_type` Internal_Tag를 설정한다
10. THE ECS Collector SHALL ResourceInfo의 tags에 `_cluster_name` Internal_Tag로 클러스터 이름을 저장한다 (Compound_Dimension용)
11. WHEN ECS Collector가 메트릭을 조회하면, THE Collector SHALL CPUUtilization, MemoryUtilization, RunningTaskCount 값을 반환한다
12. THE ECS Collector SHALL 메트릭 조회 시 ClusterName과 ServiceName 두 디멘션을 모두 포함하여 CloudWatch API를 호출한다

##### 2-D. 기본 임계치

13. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 EcsCPU=80, EcsMemory=80, RunningTaskCount=1을 추가한다


### Requirement 3: MSK (Kafka) 모니터링

**User Story:** As a 운영자, I want MSK 클러스터의 컨슈머 지연, 트래픽, 복제 상태, 컨트롤러 상태를 모니터링하고 싶다, so that Kafka 클러스터 가용성과 데이터 파이프라인 지연을 감지할 수 있다.

#### Acceptance Criteria

1. WHEN Monitoring=on 태그가 있는 MSK 클러스터가 존재하면, THE Alarm_Registry SHALL resource_type MSK에 대해 OffsetLag(>1000), BytesInPerSec(traffic), UnderReplicatedPartitions(>0), ActiveControllerCount(<1) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL MSK 알람에 네임스페이스 AWS/Kafka, 디멘션 키 "Cluster Name"을 사용한다
3. THE ActiveControllerCount 알람 정의 SHALL comparison을 LessThanThreshold로 설정하고 treat_missing_data를 breaching으로 설정한다
4. WHEN MSK Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 MSK 클러스터 목록을 반환한다
5. WHEN MSK Collector가 메트릭을 조회하면, THE Collector SHALL SumOffsetLag, BytesInPerSec, UnderReplicatedPartitions, ActiveControllerCount 값을 반환한다
6. THE Daily_Monitor SHALL MSK Collector를 _COLLECTOR_MODULES에 포함한다
7. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 MSK를 추가한다
8. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 OffsetLag=1000, BytesInPerSec=100000000, UnderReplicatedPartitions=0, ActiveControllerCount=1을 추가한다


### Requirement 4: DynamoDB 모니터링

**User Story:** As a 운영자, I want DynamoDB 테이블의 읽기/쓰기 용량 소비, 스로틀링, 시스템 에러를 모니터링하고 싶다, so that 테이블 성능 저하와 용량 부족을 사전에 감지할 수 있다.

#### Acceptance Criteria

1. WHEN Monitoring=on 태그가 있는 DynamoDB 테이블이 존재하면, THE Alarm_Registry SHALL resource_type DynamoDB에 대해 DDBReadCapacity(>80%), DDBWriteCapacity(>80%), ThrottledRequests(>0), DDBSystemErrors(>0) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL DynamoDB 알람에 네임스페이스 AWS/DynamoDB, 디멘션 키 TableName을 사용한다
3. WHEN DynamoDB Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 DynamoDB 테이블 목록을 반환한다
4. WHEN DynamoDB Collector가 메트릭을 조회하면, THE Collector SHALL ConsumedReadCapacityUnits, ConsumedWriteCapacityUnits, ThrottledRequests, SystemErrors 값을 반환한다
5. THE Daily_Monitor SHALL DynamoDB Collector를 _COLLECTOR_MODULES에 포함한다
6. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 DynamoDB를 추가한다
7. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 DDBReadCapacity=80, DDBWriteCapacity=80, ThrottledRequests=0, DDBSystemErrors=0을 추가한다


### Requirement 5: CloudFront 모니터링

**User Story:** As a 운영자, I want CloudFront 배포의 에러율과 트래픽을 모니터링하고 싶다, so that CDN 장애와 오리진 문제를 즉시 감지할 수 있다.

#### Acceptance Criteria

1. WHEN Monitoring=on 태그가 있는 CloudFront 배포가 존재하면, THE Alarm_Registry SHALL resource_type CloudFront에 대해 CF5xxErrorRate(>1%), CF4xxErrorRate(>5%), CFRequests(traffic), CFBytesDownloaded(traffic) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL CloudFront 알람에 네임스페이스 AWS/CloudFront, 디멘션 키 DistributionId를 사용한다
3. THE Alarm_Registry SHALL CloudFront 알람에 Region을 us-east-1로 고정한다 (CloudFront 메트릭은 글로벌 서비스로 us-east-1에서만 발행)
4. WHEN CloudFront Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 CloudFront 배포 목록을 반환한다
5. WHEN CloudFront Collector가 메트릭을 조회하면, THE Collector SHALL 5xxErrorRate, 4xxErrorRate, Requests, BytesDownloaded 값을 반환한다
6. THE Daily_Monitor SHALL CloudFront Collector를 _COLLECTOR_MODULES에 포함한다
7. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 CloudFront를 추가한다
8. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 CF5xxErrorRate=1, CF4xxErrorRate=5, CFRequests=1000000, CFBytesDownloaded=10000000000을 추가한다


### Requirement 6: WAF 모니터링

**User Story:** As a 운영자, I want WAF WebACL의 차단 요청 수와 허용 트래픽을 모니터링하고 싶다, so that 웹 공격 급증과 비정상 트래픽 패턴을 감지할 수 있다.

#### Acceptance Criteria

1. WHEN Monitoring=on 태그가 있는 WAF WebACL이 존재하면, THE Alarm_Registry SHALL resource_type WAF에 대해 WAFBlockedRequests(>100), WAFAllowedRequests(traffic), WAFCountedRequests(traffic) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL WAF 알람에 네임스페이스 AWS/WAFV2, Compound_Dimension으로 WebACL과 Rule을 사용한다
3. WHEN WAF Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 WAF WebACL 목록을 반환한다
4. THE WAF Collector SHALL ResourceInfo의 tags에 `_waf_rule` Internal_Tag로 Rule 이름을 저장한다 (Compound_Dimension용, 기본값 "ALL")
5. WHEN WAF Collector가 메트릭을 조회하면, THE Collector SHALL BlockedRequests, AllowedRequests, CountedRequests 값을 반환한다
6. THE Daily_Monitor SHALL WAF Collector를 _COLLECTOR_MODULES에 포함한다
7. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 WAF를 추가한다
8. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 WAFBlockedRequests=100, WAFAllowedRequests=1000000, WAFCountedRequests=100000을 추가한다


### Requirement 7: Route53 Health Check 모니터링

**User Story:** As a 운영자, I want Route53 Health Check의 상태를 모니터링하고 싶다, so that DNS 헬스체크 실패를 즉시 감지할 수 있다.

#### Acceptance Criteria

1. WHEN Monitoring=on 태그가 있는 Route53 Health Check가 존재하면, THE Alarm_Registry SHALL resource_type Route53에 대해 HealthCheckStatus(<1) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL Route53 알람에 네임스페이스 AWS/Route53, 디멘션 키 HealthCheckId를 사용한다
3. THE Route53 알람 정의 SHALL treat_missing_data를 breaching으로 설정하여 Miss_Data_Alarm을 구성한다 (VPN 패턴 준용)
4. THE Alarm_Registry SHALL Route53 알람에 Region을 us-east-1로 고정한다 (Route53 메트릭은 글로벌 서비스로 us-east-1에서만 발행)
5. WHEN Route53 Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 Route53 Health Check 목록을 반환한다
6. WHEN Route53 Collector가 메트릭을 조회하면, THE Collector SHALL HealthCheckStatus 값을 반환한다
7. THE Daily_Monitor SHALL Route53 Collector를 _COLLECTOR_MODULES에 포함한다
8. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 Route53를 추가한다
9. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 HealthCheckStatus=1을 추가한다


### Requirement 8: Direct Connect 모니터링

**User Story:** As a 운영자, I want Direct Connect 연결의 상태를 모니터링하고 싶다, so that 전용선 연결 다운을 즉시 감지할 수 있다.

#### Acceptance Criteria

1. WHEN Monitoring=on 태그가 있는 Direct Connect 연결이 존재하면, THE Alarm_Registry SHALL resource_type DX에 대해 ConnectionState(<1) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL DX 알람에 네임스페이스 AWS/DX, 디멘션 키 ConnectionId를 사용한다
3. THE DX 알람 정의 SHALL treat_missing_data를 breaching으로 설정하여 Miss_Data_Alarm을 구성한다 (VPN 패턴 준용)
4. WHEN DX Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 Direct Connect 연결 목록을 반환한다
5. WHEN DX Collector가 메트릭을 조회하면, THE Collector SHALL ConnectionState 값을 반환한다
6. THE Daily_Monitor SHALL DX Collector를 _COLLECTOR_MODULES에 포함한다
7. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 DX를 추가한다
8. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 ConnectionState=1을 추가한다


### Requirement 9: EFS 모니터링

**User Story:** As a 운영자, I want EFS 파일 시스템의 버스트 크레딧, I/O 제한, 클라이언트 연결을 모니터링하고 싶다, so that 파일 시스템 성능 저하와 I/O 병목을 사전에 감지할 수 있다.

#### Acceptance Criteria

1. WHEN Monitoring=on 태그가 있는 EFS 파일 시스템이 존재하면, THE Alarm_Registry SHALL resource_type EFS에 대해 BurstCreditBalance(<1000000000), PercentIOLimit(>90%), EFSClientConnections(traffic) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL EFS 알람에 네임스페이스 AWS/EFS, 디멘션 키 FileSystemId를 사용한다
3. THE BurstCreditBalance 알람 정의 SHALL comparison을 LessThanThreshold로 설정한다
4. WHEN EFS Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 EFS 파일 시스템 목록을 반환한다
5. WHEN EFS Collector가 메트릭을 조회하면, THE Collector SHALL BurstCreditBalance, PercentIOLimit, ClientConnections 값을 반환한다
6. THE Daily_Monitor SHALL EFS Collector를 _COLLECTOR_MODULES에 포함한다
7. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 EFS를 추가한다
8. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 BurstCreditBalance=1000000000, PercentIOLimit=90, EFSClientConnections=1000을 추가한다


### Requirement 10: S3 모니터링

**User Story:** As a 운영자, I want S3 버킷의 요청 에러, 버킷 크기, 객체 수를 모니터링하고 싶다, so that 스토리지 이상과 접근 에러를 감지할 수 있다.

#### Acceptance Criteria

##### 10-A. 알람 정의

1. WHEN Monitoring=on 태그가 있는 S3 버킷이 존재하면, THE Alarm_Registry SHALL resource_type S3에 대해 S34xxErrors(>100), S35xxErrors(>10), S3BucketSizeBytes(traffic), S3NumberOfObjects(traffic) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL S3 알람에 네임스페이스 AWS/S3, Compound_Dimension으로 BucketName과 StorageType을 사용한다
3. THE S3 알람 정의 중 S3BucketSizeBytes와 S3NumberOfObjects SHALL StorageType 디멘션 값을 "StandardStorage"로 기본 설정한다

##### 10-B. Collector 구현

4. WHEN S3 Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 S3 버킷 목록을 반환한다
5. THE S3 Collector SHALL ResourceInfo의 tags에 `_storage_type` Internal_Tag로 StorageType을 저장한다 (Compound_Dimension용, 기본값 "StandardStorage")
6. WHEN S3 Collector가 메트릭을 조회하면, THE Collector SHALL 4xxErrors, 5xxErrors, BucketSizeBytes, NumberOfObjects 값을 반환한다
7. THE S3 Collector SHALL 4xxErrors, 5xxErrors 메트릭 조회 시 FilterId 디멘션이 필요한 경우 Request_Metrics 활성화 여부에 따라 데이터 가용성이 달라짐을 로깅한다

##### 10-C. Request Metrics 제약사항

8. THE S3 Collector SHALL 4xxErrors, 5xxErrors 메트릭이 데이터를 반환하지 않을 때 Request_Metrics 미활성화 가능성을 warning 로그로 안내한다

##### 10-D. 기본 임계치

9. THE Daily_Monitor SHALL S3 Collector를 _COLLECTOR_MODULES에 포함한다
10. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 S3를 추가한다
11. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 S34xxErrors=100, S35xxErrors=10, S3BucketSizeBytes=1000000000000, S3NumberOfObjects=10000000을 추가한다


### Requirement 11: SageMaker 추론 엔드포인트 모니터링

**User Story:** As a 운영자, I want SageMaker 추론 엔드포인트의 호출 수, 에러, 레이턴시, CPU 사용률을 모니터링하고 싶다, so that ML 추론 서비스의 성능 저하와 장애를 감지할 수 있다.

#### Acceptance Criteria

##### 11-A. 알람 정의

1. WHEN Monitoring=on 태그가 있는 SageMaker 추론 엔드포인트가 존재하면, THE Alarm_Registry SHALL resource_type SageMaker에 대해 SMInvocations(traffic), SMInvocationErrors(>0), SMModelLatency(>1000ms), SMCPU(>80%) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL SageMaker 알람에 네임스페이스 AWS/SageMaker, Compound_Dimension으로 EndpointName과 VariantName을 사용한다

##### 11-B. Collector 구현

3. WHEN SageMaker Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 SageMaker 추론 엔드포인트 목록을 반환한다 (InService 상태만)
4. THE SageMaker Collector SHALL 학습 작업(Training Job)을 수집 대상에서 제외한다
5. THE SageMaker Collector SHALL ResourceInfo의 tags에 `_variant_name` Internal_Tag로 VariantName을 저장한다 (Compound_Dimension용)
6. WHEN SageMaker Collector가 메트릭을 조회하면, THE Collector SHALL Invocations, InvocationErrors, ModelLatency, CPUUtilization 값을 반환한다
7. THE SageMaker Collector SHALL 메트릭 조회 시 EndpointName과 VariantName 두 디멘션을 모두 포함하여 CloudWatch API를 호출한다

##### 11-C. 기본 임계치

8. THE Daily_Monitor SHALL SageMaker Collector를 _COLLECTOR_MODULES에 포함한다
9. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 SageMaker를 추가한다
10. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 SMInvocations=100000, SMInvocationErrors=0, SMModelLatency=1000, SMCPU=80을 추가한다


### Requirement 12: SNS 모니터링

**User Story:** As a 운영자, I want SNS 토픽의 알림 실패 수와 발행 트래픽을 모니터링하고 싶다, so that 알림 전달 실패를 즉시 감지할 수 있다.

#### Acceptance Criteria

1. WHEN Monitoring=on 태그가 있는 SNS 토픽이 존재하면, THE Alarm_Registry SHALL resource_type SNS에 대해 SNSNotificationsFailed(>0), SNSMessagesPublished(traffic) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL SNS 알람에 네임스페이스 AWS/SNS, 디멘션 키 TopicName을 사용한다
3. WHEN SNS Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 SNS 토픽 목록을 반환한다
4. WHEN SNS Collector가 메트릭을 조회하면, THE Collector SHALL NumberOfNotificationsFailed, NumberOfMessagesPublished 값을 반환한다
5. THE Daily_Monitor SHALL SNS Collector를 _COLLECTOR_MODULES에 포함한다
6. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 SNS를 추가한다
7. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 SNSNotificationsFailed=0, SNSMessagesPublished=1000000을 추가한다


### Requirement 13: Alarm_Registry 데이터 등록 (공통)

**User Story:** As a 개발자, I want 12개 리소스 타입의 알람 정의가 Alarm_Registry에 일관되게 등록되길 원한다, so that alarm_manager가 알람을 자동 생성할 수 있다.

#### Acceptance Criteria

1. THE Alarm_Registry SHALL 12개 신규 리소스 타입 각각에 대해 알람 정의 리스트를 정의한다
2. THE Alarm_Registry SHALL _get_alarm_defs()에서 12개 신규 resource_type을 분기 처리한다
3. THE Alarm_Registry SHALL ECS resource_type에 대해 _ecs_launch_type Internal_Tag 값(FARGATE, EC2)에 관계없이 동일한 알람 정의를 반환한다
4. THE Alarm_Registry SHALL _HARDCODED_METRIC_KEYS에 12개 신규 리소스 타입의 메트릭 키 집합을 등록한다
5. THE Alarm_Registry SHALL _NAMESPACE_MAP에 12개 신규 리소스 타입의 CloudWatch 네임스페이스를 등록한다
6. THE Alarm_Registry SHALL _DIMENSION_KEY_MAP에 12개 신규 리소스 타입의 디멘션 키를 등록한다 (ECS는 ServiceName, S3는 BucketName, WAF는 WebACL, SageMaker는 EndpointName)
7. THE Alarm_Registry SHALL _METRIC_DISPLAY에 모든 신규 메트릭의 (display_name, direction, unit) 매핑을 등록한다
8. THE Alarm_Registry SHALL _metric_name_to_key()에 신규 CloudWatch metric_name에서 내부 metric key로의 매핑을 등록한다


### Requirement 14: CloudTrail 이벤트 등록 (공통)

**User Story:** As a 개발자, I want 신규 리소스의 생명주기 API가 CloudTrail 이벤트로 등록되길 원한다, so that 리소스 생성/삭제/태그 변경 시 실시간 대응이 가능하다.

#### Acceptance Criteria

1. THE Monitoring_Engine SHALL MONITORED_API_EVENTS의 CREATE/DELETE/TAG_CHANGE 카테고리에 12개 신규 리소스 타입의 생명주기 API를 추가한다
2. THE Remediation_Handler SHALL _API_MAP에 12개 신규 리소스 타입의 (resource_type, id_extractor) 매핑을 추가한다
3. THE template.yaml SHALL CloudTrailModifyRule EventPattern에 12개 신규 리소스 타입의 API 이벤트를 추가한다
4. IF CloudTrail 이벤트에서 리소스 ID 추출이 실패하면, THEN THE Remediation_Handler SHALL 에러를 로깅하고 해당 이벤트를 건너뛴다


### Requirement 15: template.yaml IAM 권한 (공통)

**User Story:** As a 개발자, I want Lambda가 12개 신규 리소스의 AWS API를 호출할 IAM 권한을 갖길 원한다, so that Collector와 Remediation_Handler가 정상 동작한다.

#### Acceptance Criteria

1. THE template.yaml SHALL Daily_Monitor Lambda IAM Role에 12개 신규 리소스의 Describe/List API 권한을 추가한다
2. THE template.yaml SHALL Daily_Monitor Lambda IAM Role에 12개 신규 리소스의 태그 조회 API 권한을 추가한다
3. THE template.yaml SHALL Remediation_Handler Lambda IAM Role에 12개 신규 리소스의 생명주기 관련 API 권한을 추가한다


### Requirement 16: 고아 알람 정리 지원 (공통)

**User Story:** As a 운영자, I want 삭제된 신규 리소스의 알람이 자동 정리되길 원한다, so that 불필요한 고아 알람이 남지 않는다.

#### Acceptance Criteria

1. THE Daily_Monitor SHALL alive_checkers에 12개 신규 리소스 타입의 존재 확인 함수를 등록한다
2. WHEN 신규 리소스가 삭제되면, THE Daily_Monitor SHALL 해당 리소스의 알람을 고아 알람으로 식별하여 삭제한다
3. THE Daily_Monitor SHALL 각 신규 리소스 타입에 대해 _find_alive_* 함수를 구현한다


### Requirement 17: Compound_Dimension 처리 (ECS, WAF, S3, SageMaker)

**User Story:** As a 개발자, I want 복합 디멘션이 필요한 리소스의 알람이 올바른 디멘션 조합으로 생성되길 원한다, so that CloudWatch 메트릭 조회가 정확하게 동작한다.

#### Acceptance Criteria

1. THE _build_dimensions() SHALL ECS resource_type에 대해 ServiceName + ClusterName 2개 디멘션을 구성한다 (resource_tags의 `_cluster_name`에서 ClusterName 조회)
2. THE _build_dimensions() SHALL WAF resource_type에 대해 WebACL + Rule 2개 디멘션을 구성한다 (resource_tags의 `_waf_rule`에서 Rule 조회)
3. THE _build_dimensions() SHALL S3 resource_type에 대해 BucketName + StorageType 2개 디멘션을 구성한다 (resource_tags의 `_storage_type`에서 StorageType 조회)
4. THE _build_dimensions() SHALL SageMaker resource_type에 대해 EndpointName + VariantName 2개 디멘션을 구성한다 (resource_tags의 `_variant_name`에서 VariantName 조회)
5. IF Compound_Dimension의 보조 디멘션 값이 누락되면, THEN THE _build_dimensions() SHALL 기본 디멘션 1개만 반환하고 warning 로그를 출력한다


### Requirement 18: Miss_Data_Alarm 처리 (Route53, Direct Connect, MSK ActiveControllerCount)

**User Story:** As a 개발자, I want 연결 상태 모니터링 알람이 데이터 누락 시에도 경보를 발생시키길 원한다, so that 메트릭 발행 중단 자체를 장애로 감지할 수 있다.

#### Acceptance Criteria

1. THE Route53 HealthCheckStatus 알람 정의 SHALL treat_missing_data를 breaching으로 설정한다
2. THE DX ConnectionState 알람 정의 SHALL treat_missing_data를 breaching으로 설정한다
3. THE MSK ActiveControllerCount 알람 정의 SHALL treat_missing_data를 breaching으로 설정한다
4. THE Alarm_Builder SHALL 알람 생성 시 alarm_def의 treat_missing_data 필드를 CloudWatch put_metric_alarm의 TreatMissingData 파라미터로 전달한다 (기존 VPN 패턴 재사용)


### Requirement 19: SRE 골든 시그널 커버리지

**User Story:** As a 운영자, I want 각 신규 리소스의 하드코딩 알람이 SRE 4대 골든 시그널을 가능한 한 커버하길 원한다, so that 핵심 장애 시그널을 놓치지 않는다.

#### Acceptance Criteria

1. THE Alarm_Registry SHALL SQS 알람에서 Saturation(MessagesVisible)과 Latency(OldestMessage)와 Traffic(MessagesSent)을 커버한다
2. THE Alarm_Registry SHALL ECS 알람에서 Saturation(CPU, Memory)과 Errors(RunningTaskCount<1)를 커버한다
3. THE Alarm_Registry SHALL MSK 알람에서 Saturation(OffsetLag)과 Traffic(BytesInPerSec)과 Errors(UnderReplicatedPartitions, ActiveControllerCount)를 커버한다
4. THE Alarm_Registry SHALL DynamoDB 알람에서 Saturation(ReadCapacity, WriteCapacity)과 Errors(ThrottledRequests, SystemErrors)를 커버한다
5. THE Alarm_Registry SHALL CloudFront 알람에서 Errors(5xxErrorRate, 4xxErrorRate)와 Traffic(Requests, BytesDownloaded)을 커버한다
6. THE Alarm_Registry SHALL WAF 알람에서 Errors(BlockedRequests)와 Traffic(AllowedRequests, CountedRequests)을 커버한다
7. THE Alarm_Registry SHALL Route53 알람에서 Errors(HealthCheckStatus)를 커버한다
8. THE Alarm_Registry SHALL DX 알람에서 Errors(ConnectionState)를 커버한다
9. THE Alarm_Registry SHALL EFS 알람에서 Saturation(BurstCreditBalance, PercentIOLimit)과 Traffic(ClientConnections)을 커버한다
10. THE Alarm_Registry SHALL S3 알람에서 Errors(4xxErrors, 5xxErrors)와 Traffic(BucketSizeBytes, NumberOfObjects)을 커버한다
11. THE Alarm_Registry SHALL SageMaker 알람에서 Latency(ModelLatency)와 Traffic(Invocations)과 Errors(InvocationErrors)와 Saturation(CPU)을 커버한다
12. THE Alarm_Registry SHALL SNS 알람에서 Errors(NotificationsFailed)와 Traffic(MessagesPublished)을 커버한다
