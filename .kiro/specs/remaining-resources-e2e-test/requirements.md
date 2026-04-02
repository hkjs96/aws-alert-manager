# Requirements Document

## Introduction

기존 E2E 테스트 인프라(`infra-test/e2e-all-resources/`)와 별도로, 8개 신규 리소스 타입(Lambda, VPN, API Gateway REST/HTTP/WebSocket, ACM, AWS Backup, Amazon MQ, CLB, OpenSearch)의 알람 자동 생성을 검증하기 위한 독립 CloudFormation 스택과 트래픽 테스트 스크립트를 구성한다.

스택 경로: `infra-test/remaining-resources-test/`
예상 비용: ~$0.12/hr (테스트 직후 즉시 삭제)
예상 알람 수: Daily Monitor 실행 후 약 35개

## Glossary

- **E2E_Stack**: `infra-test/remaining-resources-test/template.yaml`로 배포되는 CloudFormation 스택
- **Traffic_Script**: `infra-test/remaining-resources-test/traffic-test.sh` 트래픽 생성 스크립트
- **Daily_Monitor**: 매일 1회 알람 동기화 및 임계치 비교 Lambda
- **Monitoring_Tag**: 리소스에 부착하는 `Monitoring=on` 태그 (알람 자동 생성 트리거)
- **REST_API**: API Gateway v1 REST API (apigateway 서비스)
- **HTTP_API**: API Gateway v2 HTTP API (apigatewayv2 서비스, ProtocolType=HTTP)
- **WebSocket_API**: API Gateway v2 WebSocket API (apigatewayv2 서비스, ProtocolType=WEBSOCKET)
- **Lambda_Backend**: APIGW REST/HTTP 통합 백엔드로 사용되는 Lambda 함수
- **CLB**: Classic Load Balancer (Elastic Load Balancing v1)
- **VPN_Connection**: Site-to-Site VPN 연결 (Virtual Private Gateway + Customer Gateway)
- **Backup_Vault**: AWS Backup 볼트 (백업 저장소)
- **MQ_Broker**: Amazon MQ ActiveMQ 브로커
- **OpenSearch_Domain**: Amazon OpenSearch Service 도메인

## Requirements

### Requirement 1: CloudFormation 스택 기본 구조

**User Story:** As a 개발자, I want 8개 신규 리소스를 포함하는 독립 CloudFormation 스택을 배포하고 싶다, so that 기존 E2E 스택에 영향 없이 신규 리소스의 알람 자동 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE E2E_Stack SHALL `infra-test/remaining-resources-test/template.yaml` 경로에 순수 CloudFormation 템플릿(SAM 미사용)으로 작성된다
2. THE E2E_Stack SHALL AWSTemplateFormatVersion 2010-09-09를 사용한다
3. THE E2E_Stack SHALL Parameters로 Environment(기본값 dev), VpcId, SubnetId1, SubnetId2를 정의한다
4. THE E2E_Stack SHALL 모든 리소스에 Monitoring=on 태그를 부착하여 Daily_Monitor의 알람 자동 생성 대상으로 포함한다
5. THE E2E_Stack SHALL Outputs 섹션에 각 리소스의 식별자와 엔드포인트를 출력한다
6. THE E2E_Stack SHALL 기존 `infra-test/e2e-all-resources/template.yaml`의 네이밍 패턴(`${Environment}-e2e-*`)을 따른다


### Requirement 2: Lambda 함수 리소스

**User Story:** As a 개발자, I want APIGW 통합 백엔드용 Lambda 함수를 배포하고 싶다, so that Lambda Duration/Errors 알람과 APIGW Latency/Error 알람을 동시에 검증할 수 있다.

#### Acceptance Criteria

1. THE E2E_Stack SHALL Lambda_Backend 함수를 Python 3.12 런타임으로 생성한다
2. THE E2E_Stack SHALL Lambda_Backend의 ReservedConcurrentExecutions를 2로 설정하여 Throttles 테스트를 지원한다
3. THE E2E_Stack SHALL Lambda_Backend에 Monitoring=on 태그를 부착한다
4. THE E2E_Stack SHALL Lambda_Backend의 인라인 코드가 HTTP 200 응답을 반환하는 핸들러를 포함한다
5. THE E2E_Stack SHALL Lambda_Backend에 APIGW 호출을 허용하는 Lambda Permission 리소스를 생성한다
6. THE E2E_Stack SHALL Lambda_Backend 실행에 필요한 IAM Role(기본 Lambda 실행 권한)을 생성한다


### Requirement 3: API Gateway REST API 리소스

**User Story:** As a 개발자, I want API Gateway REST API를 Lambda 통합으로 배포하고 싶다, so that REST API의 ApiLatency, Api4XXError, Api5XXError 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE E2E_Stack SHALL API Gateway REST API를 생성하고 Monitoring=on 태그를 부착한다
2. THE E2E_Stack SHALL REST API에 ANY 메서드의 Lambda 프록시 통합을 구성한다
3. THE E2E_Stack SHALL REST API를 배포하고 스테이지(dev)를 생성한다
4. THE E2E_Stack SHALL Outputs에 REST API의 호출 URL을 출력한다


### Requirement 4: API Gateway HTTP API 리소스

**User Story:** As a 개발자, I want API Gateway HTTP API를 Lambda 통합으로 배포하고 싶다, so that HTTP API의 ApiLatency, Api4xx, Api5xx 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE E2E_Stack SHALL API Gateway HTTP API(ProtocolType=HTTP)를 생성하고 Monitoring=on 태그를 부착한다
2. THE E2E_Stack SHALL HTTP API에 Lambda 프록시 통합을 구성한다
3. THE E2E_Stack SHALL HTTP API에 auto-deploy 스테이지($default)를 생성한다
4. THE E2E_Stack SHALL Outputs에 HTTP API의 호출 URL을 출력한다


### Requirement 5: API Gateway WebSocket API 리소스

**User Story:** As a 개발자, I want API Gateway WebSocket API를 Mock 통합으로 배포하고 싶다, so that WebSocket API의 WsConnectCount, WsMessageCount, WsIntegrationError, WsExecutionError 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE E2E_Stack SHALL API Gateway WebSocket API(ProtocolType=WEBSOCKET)를 생성하고 Monitoring=on 태그를 부착한다
2. THE E2E_Stack SHALL WebSocket API에 $connect, $disconnect, $default 라우트를 Mock 통합으로 구성한다
3. THE E2E_Stack SHALL WebSocket API를 배포하고 스테이지(dev)를 생성한다
4. THE E2E_Stack SHALL Outputs에 WebSocket API의 연결 URL(wss://)을 출력한다


### Requirement 6: VPN 리소스

**User Story:** As a 개발자, I want Site-to-Site VPN 연결을 배포하고 싶다, so that VPN TunnelState 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE E2E_Stack SHALL Virtual Private Gateway를 생성하고 VpcId에 연결한다
2. THE E2E_Stack SHALL Customer Gateway를 더미 IP 주소(예: 203.0.113.1)로 생성한다
3. THE E2E_Stack SHALL VPN Connection을 생성하고 Monitoring=on 태그를 부착한다
4. THE E2E_Stack SHALL VPN Connection의 Type을 ipsec.1로 설정한다


### Requirement 7: ACM 인증서 리소스

**User Story:** As a 개발자, I want ACM 인증서를 배포하고 싶다, so that DaysToExpiry 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE E2E_Stack SHALL ACM 인증서를 DNS 검증 방식으로 요청한다
2. THE E2E_Stack SHALL ACM 인증서의 DomainName을 테스트용 도메인(예: e2e-test.example.com)으로 설정한다
3. WHILE ACM 인증서가 PENDING_VALIDATION 상태이더라도, THE CloudWatch SHALL DaysToExpiry 메트릭을 발행한다 (검증 완료 불필요)


### Requirement 8: AWS Backup 리소스

**User Story:** As a 개발자, I want AWS Backup Vault와 Backup Plan을 배포하고 싶다, so that BackupJobsFailed, BackupJobsAborted 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE E2E_Stack SHALL Backup Vault를 생성하고 Monitoring=on 태그를 부착한다
2. THE E2E_Stack SHALL Backup Plan을 생성하고 Backup Vault를 대상으로 지정한다
3. THE E2E_Stack SHALL Backup Plan의 백업 대상으로 간단한 DynamoDB 테이블을 생성한다
4. THE E2E_Stack SHALL Backup Selection으로 DynamoDB 테이블을 백업 대상에 포함한다
5. THE E2E_Stack SHALL Backup 실행에 필요한 IAM Role을 생성한다


### Requirement 9: Amazon MQ 브로커 리소스

**User Story:** As a 개발자, I want Amazon MQ ActiveMQ 브로커를 배포하고 싶다, so that MqCPU, HeapUsage, JobSchedulerStoreUsage, StoreUsage 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE E2E_Stack SHALL Amazon MQ ActiveMQ 브로커를 mq.t3.micro 인스턴스 타입으로 생성한다
2. THE E2E_Stack SHALL MQ 브로커를 SINGLE_INSTANCE 배포 모드로 구성한다
3. THE E2E_Stack SHALL MQ 브로커에 Monitoring=on 태그를 부착한다
4. THE E2E_Stack SHALL MQ 브로커에 관리자 사용자를 구성한다
5. THE E2E_Stack SHALL Parameters에 MQ 브로커 비밀번호를 NoEcho 파라미터로 정의한다


### Requirement 10: Classic Load Balancer 리소스

**User Story:** As a 개발자, I want Classic Load Balancer를 배포하고 싶다, so that CLBUnHealthyHost, CLB5XX, CLB4XX, CLBBackend5XX, CLBBackend4XX, SurgeQueueLength, SpilloverCount 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE E2E_Stack SHALL Classic Load Balancer를 internet-facing으로 생성한다
2. THE E2E_Stack SHALL CLB에 HTTP:80 리스너를 구성한다
3. THE E2E_Stack SHALL CLB에 Monitoring=on 태그를 부착한다
4. THE E2E_Stack SHALL CLB의 Health Check를 HTTP:80 경로로 구성한다
5. THE E2E_Stack SHALL CLB에 최소 EC2 인스턴스를 타겟으로 등록한다 (신규 t3.micro 인스턴스 생성)
6. THE E2E_Stack SHALL CLB 타겟 EC2 인스턴스에 간단한 HTTP 서버(httpd)를 UserData로 설치한다
7. THE E2E_Stack SHALL CLB용 Security Group(HTTP:80 인바운드)을 생성한다


### Requirement 11: OpenSearch 도메인 리소스

**User Story:** As a 개발자, I want OpenSearch 도메인을 배포하고 싶다, so that ClusterStatusRed, ClusterStatusYellow, OSFreeStorageSpace, ClusterIndexWritesBlocked, OsCPU, JVMMemoryPressure, MasterCPU, MasterJVMMemoryPressure 알람 생성을 검증할 수 있다.

#### Acceptance Criteria

1. THE E2E_Stack SHALL OpenSearch 도메인을 t3.small.search 인스턴스 타입으로 생성한다
2. THE E2E_Stack SHALL OpenSearch 도메인을 단일 노드(InstanceCount=1)로 구성한다
3. THE E2E_Stack SHALL OpenSearch 도메인에 전용 마스터 노드를 비활성화한다
4. THE E2E_Stack SHALL OpenSearch 도메인에 Monitoring=on 태그를 부착한다
5. THE E2E_Stack SHALL OpenSearch 도메인에 EBS 볼륨(gp3, 10GB)을 구성한다
6. THE E2E_Stack SHALL OpenSearch 도메인의 접근 정책을 구성한다


### Requirement 12: 트래픽 테스트 스크립트

**User Story:** As a 개발자, I want CloudWatch 메트릭을 발생시키는 트래픽 테스트 스크립트를 실행하고 싶다, so that 알람 임계치 비교가 실제 메트릭 데이터로 검증된다.

#### Acceptance Criteria

1. THE Traffic_Script SHALL `infra-test/remaining-resources-test/traffic-test.sh` 경로에 bash 스크립트로 작성된다
2. THE Traffic_Script SHALL 사용법을 `Usage: ./traffic-test.sh <REST_API_URL> <HTTP_API_URL> <WS_API_URL> <CLB_DNS>` 형식으로 출력한다
3. WHEN Traffic_Script가 실행되면, THE Traffic_Script SHALL APIGW REST 엔드포인트에 순차 curl 요청을 전송하여 Lambda Duration/Errors 및 APIGW Latency/4XX/5XX 메트릭을 발생시킨다
4. WHEN Traffic_Script가 실행되면, THE Traffic_Script SHALL APIGW REST 엔드포인트에 동시 curl 요청(xargs -P 10)을 전송하여 Lambda ConcurrentExecutions/Throttles 메트릭을 발생시킨다
5. WHEN Traffic_Script가 실행되면, THE Traffic_Script SHALL APIGW HTTP 엔드포인트에 curl 요청을 전송하여 HTTP API 메트릭을 발생시킨다
6. WHEN Traffic_Script가 실행되면, THE Traffic_Script SHALL APIGW WebSocket 엔드포인트에 wscat 연결을 시도하여 ConnectCount/MessageCount 메트릭을 발생시킨다
7. WHEN Traffic_Script가 실행되면, THE Traffic_Script SHALL CLB 엔드포인트에 curl 요청을 전송하여 CLB 메트릭을 발생시킨다
8. THE Traffic_Script SHALL VPN, ACM, MQ, OpenSearch, Backup에 대해 트래픽을 전송하지 않는다 (자동 메트릭 발행 리소스)


### Requirement 13: 비용 관리

**User Story:** As a 운영자, I want E2E 테스트 비용을 최소화하고 싶다, so that 불필요한 AWS 비용이 발생하지 않는다.

#### Acceptance Criteria

1. THE E2E_Stack SHALL 최소 사양 인스턴스를 사용한다 (MQ: mq.t3.micro, OpenSearch: t3.small.search, EC2: t3.micro)
2. THE E2E_Stack SHALL 테스트 완료 후 즉시 삭제 가능하도록 DeletionProtection을 비활성화한다
3. THE E2E_Stack SHALL Description에 "테스트 직후 즉시 삭제" 안내를 포함한다
4. THE E2E_Stack SHALL 예상 시간당 비용(~$0.12/hr)을 Description 또는 주석에 명시한다


### Requirement 14: 예상 알람 검증

**User Story:** As a 개발자, I want Daily Monitor 실행 후 생성되는 알람 수를 사전에 파악하고 싶다, so that 알람 자동 생성이 정상 동작하는지 검증할 수 있다.

#### Acceptance Criteria

1. THE E2E_Stack SHALL Outputs의 ExpectedAlarms에 리소스별 예상 알람 수와 알람 이름을 명시한다
2. THE E2E_Stack SHALL 예상 총 알람 수를 약 35개로 명시한다 (Lambda:2, VPN:1, APIGW REST:3, APIGW HTTP:3, APIGW WebSocket:4, ACM:1, Backup:2, MQ:4, CLB:7, OpenSearch:8)
3. WHEN Daily_Monitor가 E2E_Stack 리소스를 스캔하면, THE Daily_Monitor SHALL 각 리소스에 대해 Monitoring=on 태그를 감지하고 알람을 자동 생성한다


### Requirement 15: 공유 리소스 및 보안 그룹

**User Story:** As a 개발자, I want 스택 내 리소스 간 네트워크 통신에 필요한 보안 그룹을 구성하고 싶다, so that CLB와 EC2 간 트래픽이 정상 동작한다.

#### Acceptance Criteria

1. THE E2E_Stack SHALL CLB용 Security Group에 HTTP:80 인바운드를 0.0.0.0/0에서 허용한다
2. THE E2E_Stack SHALL EC2용 Security Group에 CLB Security Group으로부터의 HTTP:80 인바운드를 허용한다
3. THE E2E_Stack SHALL EC2용 Security Group에 아웃바운드 전체 허용을 설정한다
4. THE E2E_Stack SHALL MQ 브로커를 퍼블릭 접근 가능하도록 설정하거나, VPC 내 서브넷에 배치한다
