# Requirements Document

## Introduction

이전 E2E 테스트 인프라(`infra-test/remaining-resources-test/`)와 별도로, 12개 확장 리소스 타입(SQS, ECS, MSK, DynamoDB, CloudFront, WAF, Route53, DX, EFS, S3, SageMaker, SNS)의 알람 자동 생성을 검증하기 위한 독립 CloudFormation 스택과 트래픽 테스트 스크립트를 구성한다.

스택 경로: `infra-test/extended-resources-test/`
리전: ap-northeast-2 (서울)
AWS 프로파일: jordy_poc (SSO)

DX(Direct Connect)는 물리 연결이 필요하므로 E2E 테스트에서 제외한다 (INSUFFICIENT_DATA 허용).
SageMaker/MSK는 비용이 높으므로 최소 사양을 사용하고 테스트 후 즉시 삭제한다.

예상 비용: ~$0.25/hr (테스트 직후 즉시 삭제)
예상 알람 수: Daily Monitor 실행 후 약 35개 (DX 제외 11개 리소스)

## Glossary

- **Extended_Stack**: `infra-test/extended-resources-test/template.yaml`로 배포되는 CloudFormation 스택
- **Traffic_Script**: `infra-test/extended-resources-test/traffic-test.sh` 트래픽 생성 스크립트
- **Daily_Monitor**: 매일 1회 알람 동기화 및 임계치 비교 Lambda
- **Monitoring_Tag**: 리소스에 부착하는 `Monitoring=on` 태그 (알람 자동 생성 트리거)
- **SQS_Queue**: Amazon SQS 표준 큐
- **ECS_Service**: Amazon ECS Fargate 서비스 (nginx 컨테이너)
- **ECS_Cluster**: ECS 서비스를 호스팅하는 ECS 클러스터
- **MSK_Cluster**: Amazon MSK (Managed Streaming for Apache Kafka) 클러스터
- **DynamoDB_Table**: Amazon DynamoDB 테이블
- **CloudFront_Distribution**: Amazon CloudFront 배포 (S3 오리진)
- **WAF_WebACL**: AWS WAFv2 Web ACL (ALB 연동)
- **WAF_ALB**: WAF WebACL 연동 대상 Application Load Balancer
- **Route53_HealthCheck**: Amazon Route53 HTTP Health Check
- **EFS_FileSystem**: Amazon EFS 파일시스템
- **S3_Bucket**: Amazon S3 버킷 (Request Metrics 활성화)
- **SageMaker_Endpoint**: Amazon SageMaker 추론 엔드포인트
- **SNS_Topic**: Amazon SNS 토픽
- **Request_Metrics**: S3 버킷에 대한 CloudWatch 요청 수준 메트릭 (활성화 후 15분 대기 필요)

## Requirements

### Requirement 1: CloudFormation 스택 기본 구조

**User Story:** As a 개발자, I want 12개 확장 리소스를 포함하는 독립 CloudFormation 스택을 배포하고 싶다, so that 기존 E2E 스택에 영향 없이 확장 리소스의 알람 자동 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL `infra-test/extended-resources-test/template.yaml` 경로에 순수 CloudFormation 템플릿(SAM 미사용)으로 작성된다
2. THE Extended_Stack SHALL AWSTemplateFormatVersion 2010-09-09를 사용한다
3. THE Extended_Stack SHALL Parameters로 Environment(기본값 dev), VpcId, SubnetId1, SubnetId2를 정의한다
4. THE Extended_Stack SHALL 모든 모니터링 대상 리소스에 Monitoring=on 태그를 부착하여 Daily_Monitor의 알람 자동 생성 대상으로 포함한다
5. THE Extended_Stack SHALL Outputs 섹션에 각 리소스의 식별자와 엔드포인트를 출력한다
6. THE Extended_Stack SHALL 기존 `infra-test/remaining-resources-test/template.yaml`의 네이밍 패턴(`${Environment}-e2e-*`)을 따른다
7. THE Extended_Stack SHALL template.yaml에 non-ASCII 문자를 사용하지 않는다 (AWS CLI 호환)


### Requirement 2: SQS 큐 리소스

**User Story:** As a 개발자, I want SQS 표준 큐를 배포하고 싶다, so that SQSMessagesVisible, SQSOldestMessage, SQSMessagesSent 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL SQS_Queue를 표준 큐(Standard Queue)로 생성한다
2. THE Extended_Stack SHALL SQS_Queue에 Monitoring=on 태그를 부착한다
3. THE Extended_Stack SHALL Outputs에 SQS_Queue의 QueueName과 QueueUrl을 출력한다


### Requirement 3: ECS Fargate 서비스 리소스

**User Story:** As a 개발자, I want ECS Fargate 서비스를 배포하고 싶다, so that EcsCPU, EcsMemory, RunningTaskCount 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL ECS_Cluster를 생성한다
2. THE Extended_Stack SHALL ECS_Service를 FARGATE 런치 타입으로 생성하고 Monitoring=on 태그를 부착한다
3. THE Extended_Stack SHALL ECS_Service에 nginx 컨테이너 이미지를 사용하는 TaskDefinition을 구성한다
4. THE Extended_Stack SHALL ECS TaskDefinition에 최소 사양(256 CPU, 512 Memory)을 설정한다
5. THE Extended_Stack SHALL ECS_Service에 desiredCount를 1로 설정한다
6. THE Extended_Stack SHALL ECS_Service 실행에 필요한 IAM TaskExecutionRole을 생성한다
7. THE Extended_Stack SHALL ECS_Service를 VPC 서브넷에 배치하고 퍼블릭 IP를 할당한다
8. THE Extended_Stack SHALL ECS용 Security Group(아웃바운드 전체 허용)을 생성한다


### Requirement 4: MSK 클러스터 리소스

**User Story:** As a 개발자, I want MSK Kafka 클러스터를 배포하고 싶다, so that OffsetLag, BytesInPerSec, UnderReplicatedPartitions, ActiveControllerCount 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL MSK_Cluster를 kafka.t3.small 인스턴스 타입으로 생성한다
2. THE Extended_Stack SHALL MSK_Cluster를 최소 브로커 수(2개, 단일 AZ 또는 2 AZ)로 구성한다
3. THE Extended_Stack SHALL MSK_Cluster에 Monitoring=on 태그를 부착한다
4. THE Extended_Stack SHALL MSK_Cluster에 EBS 볼륨(최소 사양)을 구성한다
5. THE Extended_Stack SHALL MSK_Cluster를 VPC 서브넷에 배치한다
6. THE Extended_Stack SHALL MSK용 Security Group을 생성한다
7. THE Extended_Stack SHALL Outputs에 MSK_Cluster의 ClusterName과 ClusterArn을 출력한다


### Requirement 5: DynamoDB 테이블 리소스

**User Story:** As a 개발자, I want DynamoDB 테이블을 배포하고 싶다, so that DDBReadCapacity, DDBWriteCapacity, ThrottledRequests, DDBSystemErrors 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL DynamoDB_Table을 PAY_PER_REQUEST 빌링 모드로 생성한다
2. THE Extended_Stack SHALL DynamoDB_Table에 Monitoring=on 태그를 부착한다
3. THE Extended_Stack SHALL DynamoDB_Table에 단순 파티션 키(id, String)를 정의한다
4. THE Extended_Stack SHALL Outputs에 DynamoDB_Table의 TableName을 출력한다


### Requirement 6: CloudFront 배포 리소스

**User Story:** As a 개발자, I want CloudFront 배포를 S3 오리진으로 배포하고 싶다, so that CF5xxErrorRate, CF4xxErrorRate, CFRequests, CFBytesDownloaded 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL CloudFront_Distribution을 S3 버킷 오리진으로 생성한다
2. THE Extended_Stack SHALL CloudFront_Distribution에 Monitoring=on 태그를 부착한다
3. THE Extended_Stack SHALL CloudFront 오리진용 S3 버킷을 생성한다
4. THE Extended_Stack SHALL CloudFront에 Origin Access Control(OAC)을 구성하여 S3 접근을 허용한다
5. THE Extended_Stack SHALL Outputs에 CloudFront_Distribution의 DistributionId와 DomainName을 출력한다
6. WHILE CloudFront 메트릭이 us-east-1에서만 발행되는 동안, THE Daily_Monitor SHALL us-east-1 리전의 CloudWatch에서 알람을 생성한다


### Requirement 7: WAF WebACL 리소스

**User Story:** As a 개발자, I want WAFv2 WebACL을 ALB에 연동하여 배포하고 싶다, so that WAFBlockedRequests, WAFAllowedRequests, WAFCountedRequests 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL WAF_WebACL을 REGIONAL 스코프로 생성하고 Monitoring=on 태그를 부착한다
2. THE Extended_Stack SHALL WAF_WebACL에 기본 Allow 액션과 Rate-based 규칙을 구성한다
3. THE Extended_Stack SHALL WAF_ALB를 생성하고 WAF_WebACL을 연동한다
4. THE Extended_Stack SHALL WAF_ALB에 HTTP:80 리스너와 고정 응답 타겟 그룹을 구성한다
5. THE Extended_Stack SHALL WAF_ALB용 Security Group(HTTP:80 인바운드)을 생성한다
6. THE Extended_Stack SHALL Outputs에 WAF_WebACL의 Name과 WAF_ALB의 DNS를 출력한다


### Requirement 8: Route53 Health Check 리소스

**User Story:** As a 개발자, I want Route53 HTTP Health Check를 배포하고 싶다, so that HealthCheckStatus 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL Route53_HealthCheck를 HTTP 타입으로 생성한다
2. THE Extended_Stack SHALL Route53_HealthCheck에 Monitoring=on 태그를 부착한다
3. THE Extended_Stack SHALL Route53_HealthCheck의 대상을 WAF_ALB DNS 또는 외부 HTTP 엔드포인트로 설정한다
4. THE Extended_Stack SHALL Outputs에 Route53_HealthCheck의 HealthCheckId를 출력한다
5. WHILE Route53 메트릭이 us-east-1에서만 발행되는 동안, THE Daily_Monitor SHALL us-east-1 리전의 CloudWatch에서 알람을 생성한다


### Requirement 9: DX (Direct Connect) 테스트 제외

**User Story:** As a 개발자, I want DX 리소스의 E2E 테스트 제외 사유를 명시하고 싶다, so that 물리 연결이 필요한 리소스에 대한 테스트 범위가 명확하다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL DX(Direct Connect) 리소스를 포함하지 않는다
2. THE Extended_Stack SHALL Description 또는 주석에 DX 제외 사유(물리 연결 필요)를 명시한다
3. WHILE DX 리소스가 E2E 테스트에서 제외되는 동안, THE Daily_Monitor SHALL DX 알람에 대해 INSUFFICIENT_DATA 상태를 허용한다


### Requirement 10: EFS 파일시스템 리소스

**User Story:** As a 개발자, I want EFS 파일시스템을 배포하고 싶다, so that BurstCreditBalance, PercentIOLimit, EFSClientConnections 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL EFS_FileSystem을 Bursting 처리량 모드로 생성한다
2. THE Extended_Stack SHALL EFS_FileSystem에 Monitoring=on 태그를 부착한다
3. THE Extended_Stack SHALL EFS_FileSystem에 최소 1개의 Mount Target을 VPC 서브넷에 생성한다
4. THE Extended_Stack SHALL EFS Mount Target용 Security Group(NFS:2049 인바운드)을 생성한다
5. THE Extended_Stack SHALL Outputs에 EFS_FileSystem의 FileSystemId를 출력한다


### Requirement 11: S3 버킷 리소스

**User Story:** As a 개발자, I want S3 버킷을 Request Metrics 활성화 상태로 배포하고 싶다, so that S34xxErrors, S35xxErrors, S3BucketSizeBytes, S3NumberOfObjects 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL S3_Bucket을 생성하고 Monitoring=on 태그를 부착한다
2. THE Extended_Stack SHALL S3_Bucket에 Request Metrics(MetricsConfiguration)를 활성화한다
3. THE Extended_Stack SHALL S3_Bucket에 스택 삭제 시 객체를 정리하는 CustomResource Lambda를 생성한다
4. THE Extended_Stack SHALL Outputs에 S3_Bucket의 BucketName을 출력한다
5. WHILE S3 Request Metrics가 활성화된 후 15분 대기가 필요한 동안, THE Traffic_Script SHALL S3 트래픽 전송 전 대기 안내를 출력한다


### Requirement 12: SageMaker 엔드포인트 리소스

**User Story:** As a 개발자, I want SageMaker 추론 엔드포인트를 배포하고 싶다, so that SMInvocations, SMInvocationErrors, SMModelLatency, SMCPU 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL SageMaker_Endpoint를 ml.t2.medium 인스턴스 타입(최소 사양)으로 생성한다
2. THE Extended_Stack SHALL SageMaker_Endpoint에 Monitoring=on 태그를 부착한다
3. THE Extended_Stack SHALL SageMaker Model, EndpointConfig, Endpoint 리소스를 생성한다
4. THE Extended_Stack SHALL SageMaker 실행에 필요한 IAM Role을 생성한다
5. THE Extended_Stack SHALL 사전 빌드된 SageMaker 컨테이너 이미지(예: scikit-learn)를 사용하여 별도 모델 아티팩트 없이 배포한다
6. THE Extended_Stack SHALL Outputs에 SageMaker_Endpoint의 EndpointName을 출력한다
7. IF SageMaker 비용이 과도하다고 판단되면, THEN THE Extended_Stack SHALL SageMaker 리소스를 주석 처리하고 제외 사유를 명시한다


### Requirement 13: SNS 토픽 리소스

**User Story:** As a 개발자, I want SNS 토픽을 배포하고 싶다, so that SNSNotificationsFailed, SNSMessagesPublished 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL SNS_Topic을 생성하고 Monitoring=on 태그를 부착한다
2. THE Extended_Stack SHALL Outputs에 SNS_Topic의 TopicName과 TopicArn을 출력한다


### Requirement 14: 트래픽 테스트 스크립트

**User Story:** As a 개발자, I want CloudWatch 메트릭을 발생시키는 트래픽 테스트 스크립트를 실행하고 싶다, so that 알람 임계치 비교가 실제 메트릭 데이터로 검증된다.

#### Acceptance Criteria

1. THE Traffic_Script SHALL `infra-test/extended-resources-test/traffic-test.sh` 경로에 bash 스크립트로 작성된다
2. WHEN Traffic_Script가 실행되면, THE Traffic_Script SHALL SQS_Queue에 메시지 발송(aws sqs send-message) 및 수신(aws sqs receive-message) 요청을 전송하여 SQS 메트릭을 발생시킨다
3. WHEN Traffic_Script가 실행되면, THE Traffic_Script SHALL DynamoDB_Table에 PutItem/GetItem 요청을 전송하여 DynamoDB 메트릭을 발생시킨다
4. WHEN Traffic_Script가 실행되면, THE Traffic_Script SHALL CloudFront_Distribution의 DomainName에 curl 요청을 전송하여 CloudFront 메트릭을 발생시킨다
5. WHEN Traffic_Script가 실행되면, THE Traffic_Script SHALL WAF_ALB의 DNS에 curl 요청을 전송하여 WAF 메트릭을 발생시킨다
6. WHEN Traffic_Script가 실행되면, THE Traffic_Script SHALL S3_Bucket에 PutObject/GetObject 요청을 전송하여 S3 Request Metrics를 발생시킨다
7. WHEN Traffic_Script가 실행되면, THE Traffic_Script SHALL SNS_Topic에 aws sns publish 요청을 전송하여 SNS 메트릭을 발생시킨다
8. THE Traffic_Script SHALL ECS, MSK, Route53, EFS, SageMaker에 대해 트래픽을 전송하지 않는다 (자동 메트릭 발행 리소스 또는 별도 클라이언트 필요)
9. THE Traffic_Script SHALL CloudFormation Outputs에서 필요한 리소스 식별자를 인자로 받는다
10. IF 인자가 누락되면, THEN THE Traffic_Script SHALL usage 메시지를 출력하고 종료한다


### Requirement 15: 비용 관리

**User Story:** As a 운영자, I want E2E 테스트 비용을 최소화하고 싶다, so that 불필요한 AWS 비용이 발생하지 않는다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL 최소 사양 인스턴스를 사용한다 (MSK: kafka.t3.small, SageMaker: ml.t2.medium, ECS: 256CPU/512MB)
2. THE Extended_Stack SHALL 테스트 완료 후 즉시 삭제 가능하도록 DeletionProtection을 비활성화한다
3. THE Extended_Stack SHALL Description에 예상 시간당 비용과 테스트 직후 즉시 삭제 안내를 포함한다
4. THE Extended_Stack SHALL MSK/SageMaker 등 고비용 리소스에 대해 주석으로 비용 경고를 명시한다


### Requirement 16: 예상 알람 검증

**User Story:** As a 개발자, I want Daily Monitor 실행 후 생성되는 알람 수를 사전에 파악하고 싶다, so that 알람 자동 생성이 정상 동작하는지 검증할 수 있다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL Outputs의 ExpectedAlarms에 리소스별 예상 알람 수와 알람 메트릭을 명시한다
2. THE Extended_Stack SHALL 예상 총 알람 수를 약 35개로 명시한다 (SQS:3, ECS:3, MSK:4, DynamoDB:4, CloudFront:4, WAF:3, Route53:1, EFS:3, S3:4, SageMaker:4, SNS:2)
3. WHEN Daily_Monitor가 Extended_Stack 리소스를 스캔하면, THE Daily_Monitor SHALL 각 리소스에 대해 Monitoring=on 태그를 감지하고 알람을 자동 생성한다


### Requirement 17: 스택 삭제 시 리소스 정리

**User Story:** As a 운영자, I want 스택 삭제 시 내부 데이터가 있는 리소스를 자동 정리하고 싶다, so that DELETE_FAILED 없이 스택이 완전히 삭제된다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL S3_Bucket 삭제 전 객체를 정리하는 CustomResource Lambda를 포함한다
2. THE Extended_Stack SHALL CustomResource의 Delete 핸들러에서 에러 발생 시에도 SUCCESS를 반환하여 스택 삭제가 블로킹되지 않도록 한다
3. THE Extended_Stack SHALL MSK_Cluster, SageMaker_Endpoint 등 삭제에 시간이 소요되는 리소스에 대해 주석으로 예상 삭제 시간을 명시한다


### Requirement 18: 네트워크 및 보안 그룹

**User Story:** As a 개발자, I want 스택 내 리소스 간 네트워크 통신에 필요한 보안 그룹을 구성하고 싶다, so that ECS, MSK, WAF ALB, EFS 등의 네트워크 통신이 정상 동작한다.

#### Acceptance Criteria

1. THE Extended_Stack SHALL ECS용 Security Group에 아웃바운드 전체 허용을 설정한다
2. THE Extended_Stack SHALL MSK용 Security Group에 Kafka 포트(9092/9094) 인바운드를 허용한다
3. THE Extended_Stack SHALL WAF_ALB용 Security Group에 HTTP:80 인바운드를 0.0.0.0/0에서 허용한다
4. THE Extended_Stack SHALL EFS Mount Target용 Security Group에 NFS:2049 인바운드를 허용한다
5. THE Extended_Stack SHALL 모든 Security Group을 VpcId 파라미터로 지정된 VPC에 생성한다
