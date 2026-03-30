# Requirements Document

## Introduction

AWS Monitoring Engine에 미구현 8개 리소스 타입을 추가한다.
§11 체크리스트를 준수하며 기존 ElastiCache/NAT 패턴을 따른다.
ACM은 태그 기반이 아닌 전체 인증서 수집 방식으로 별도 처리한다.

## Glossary

- **Monitoring_Engine**: CloudWatch 알람 자동 생성/동기화 전체 시스템
- **Collector**: CollectorProtocol 구현체, 리소스 수집 및 메트릭 조회
- **Alarm_Registry**: 리소스별 알람 정의/매핑 데이터 모듈
- **Daily_Monitor**: 매일 1회 알람 동기화 및 임계치 비교 Lambda
- **Remediation_Handler**: CloudTrail 이벤트 기반 생명주기 대응 Lambda
- **Tag_Based_Collection**: Monitoring=on 태그 리소스만 수집하는 표준 방식
- **Full_Collection**: 태그 무관 전체 리소스 수집 (ACM 전용)
- **Miss_Data_Alarm**: TreatMissingData=breaching 설정 알람
- **Compound_Dimension**: 복수 디멘션 키 조합 (DomainName+ClientId)
- **REST_API**: API Gateway v1 REST API (apigateway 클라이언트, get_rest_apis)
- **HTTP_API**: API Gateway v2 HTTP API (apigatewayv2 클라이언트, get_apis, ProtocolType=HTTP)
- **WebSocket_API**: API Gateway v2 WebSocket API (apigatewayv2 클라이언트, get_apis, ProtocolType=WEBSOCKET)
- **Internal_Tag**: Collector가 설정하는 `_` 접두사 내부 태그 (예: `_api_type`, `_lb_type`)

## Requirements


### Requirement 1: Lambda 모니터링

**User Story:** As a 운영자, I want Lambda의 Duration과 Errors를 모니터링하고 싶다, so that 성능 저하와 오류를 즉시 감지할 수 있다.

#### Acceptance Criteria

1. WHEN Monitoring=on 태그가 있는 Lambda 함수가 존재하면, THE Alarm_Registry SHALL resource_type Lambda에 대해 Duration(>2500ms)과 Errors(>0) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL Lambda 알람에 네임스페이스 AWS/Lambda, 디멘션 키 FunctionName을 사용한다
3. WHEN Lambda Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 Lambda 함수 목록을 반환한다
4. WHEN Lambda Collector가 메트릭을 조회하면, THE Collector SHALL Duration과 Errors 값을 반환한다
5. THE Daily_Monitor SHALL Lambda Collector를 _COLLECTOR_MODULES에 포함한다
6. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 Lambda를 추가한다
7. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 Duration=2500, Errors=0을 추가한다


### Requirement 2: VPN 모니터링

**User Story:** As a 운영자, I want VPN의 TunnelState를 모니터링하고 싶다, so that VPN 터널 다운을 즉시 감지할 수 있다.

#### Acceptance Criteria

1. WHEN Monitoring=on 태그가 있는 VPN 연결이 존재하면, THE Alarm_Registry SHALL resource_type VPN에 대해 TunnelState(<1) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL VPN 알람에 네임스페이스 AWS/VPN, 디멘션 키 VpnId를 사용한다
3. THE VPN 알람 정의 SHALL treat_missing_data를 breaching으로 설정하여 Miss_Data_Alarm을 구성한다
4. WHEN VPN Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 VPN 연결 목록을 반환한다
5. WHEN VPN Collector가 메트릭을 조회하면, THE Collector SHALL TunnelState 값을 반환한다
6. THE Daily_Monitor SHALL VPN Collector를 _COLLECTOR_MODULES에 포함한다
7. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 VPN을 추가한다
8. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 TunnelState=1을 추가한다


### Requirement 3: API Gateway 모니터링 (REST / HTTP / WebSocket)

**User Story:** As a 운영자, I want API Gateway의 3가지 타입(REST, HTTP, WebSocket)을 각각의 메트릭으로 모니터링하고 싶다, so that API 성능 저하, 에러 급증, WebSocket 연결 이상을 감지할 수 있다.

#### Acceptance Criteria

##### 3-A. 공통 구조 (ALB/NLB 패턴 준용)

1. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 단일 resource_type "APIGW"를 추가한다
2. THE APIGW Collector SHALL 수집한 각 API의 ResourceInfo tags에 Internal_Tag `_api_type`을 설정한다 (값: "REST", "HTTP", "WEBSOCKET")
3. THE Alarm_Registry SHALL _get_alarm_defs("APIGW", resource_tags)에서 `_api_type` Internal_Tag 값에 따라 서로 다른 알람 정의 리스트를 반환한다
4. THE Daily_Monitor SHALL APIGW Collector를 _COLLECTOR_MODULES에 단일 모듈로 포함한다

##### 3-B. REST API (v1)

5. WHEN Monitoring=on 태그가 있는 REST_API가 존재하면, THE Alarm_Registry SHALL _api_type="REST"에 대해 ApiLatency(>3000ms), Api4XXError(>1), Api5XXError(>1) 알람 정의를 제공한다
6. THE Alarm_Registry SHALL REST_API 알람에 네임스페이스 AWS/ApiGateway, 디멘션 키 ApiName을 사용한다
7. WHEN APIGW Collector가 REST API를 수집하면, THE Collector SHALL apigateway 클라이언트의 get_rest_apis() API로 Monitoring=on 태그가 있는 REST API 목록을 반환한다
8. THE APIGW Collector SHALL REST_API의 ResourceInfo에 _api_type="REST" Internal_Tag를 설정한다
9. WHEN APIGW Collector가 REST_API 메트릭을 조회하면, THE Collector SHALL Latency, 4XXError, 5XXError 값을 반환한다 (CloudWatch metric_name: Latency, 4XXError, 5XXError)

##### 3-C. HTTP API (v2)

10. WHEN Monitoring=on 태그가 있는 HTTP_API가 존재하면, THE Alarm_Registry SHALL _api_type="HTTP"에 대해 ApiLatency(>3000ms), Api4xx(>1), Api5xx(>1) 알람 정의를 제공한다
11. THE Alarm_Registry SHALL HTTP_API 알람에 네임스페이스 AWS/ApiGateway, 디멘션 키 ApiId를 사용한다 (REST_API의 ApiName과 다름)
12. WHEN APIGW Collector가 HTTP API를 수집하면, THE Collector SHALL apigatewayv2 클라이언트의 get_apis() API로 ProtocolType=HTTP인 API 중 Monitoring=on 태그가 있는 목록을 반환한다
13. THE APIGW Collector SHALL HTTP_API의 ResourceInfo에 _api_type="HTTP" Internal_Tag를 설정한다
14. WHEN APIGW Collector가 HTTP_API 메트릭을 조회하면, THE Collector SHALL Latency, 4xx, 5xx 값을 반환한다 (CloudWatch metric_name: Latency, 4xx, 5xx — REST_API의 4XXError/5XXError와 이름이 다름)

##### 3-D. WebSocket API (v2)

15. WHEN Monitoring=on 태그가 있는 WebSocket_API가 존재하면, THE Alarm_Registry SHALL _api_type="WEBSOCKET"에 대해 WsConnectCount(>1000), WsMessageCount(>10000), WsIntegrationError(>0), WsExecutionError(>0) 알람 정의를 제공한다
16. THE Alarm_Registry SHALL WebSocket_API 알람에 네임스페이스 AWS/ApiGateway, 디멘션 키 ApiId를 사용한다
17. WHEN APIGW Collector가 WebSocket API를 수집하면, THE Collector SHALL apigatewayv2 클라이언트의 get_apis() API로 ProtocolType=WEBSOCKET인 API 중 Monitoring=on 태그가 있는 목록을 반환한다
18. THE APIGW Collector SHALL WebSocket_API의 ResourceInfo에 _api_type="WEBSOCKET" Internal_Tag를 설정한다
19. WHEN APIGW Collector가 WebSocket_API 메트릭을 조회하면, THE Collector SHALL ConnectCount, MessageCount, IntegrationError, ExecutionError 값을 반환한다

##### 3-E. Collector 구현 (단일 모듈)

20. THE APIGW Collector SHALL 단일 모듈 common/collectors/apigw.py에서 REST, HTTP, WebSocket 3가지 타입을 모두 수집한다
21. THE APIGW Collector SHALL REST API 수집 시 apigateway 클라이언트를, HTTP/WebSocket API 수집 시 apigatewayv2 클라이언트를 사용한다
22. THE APIGW Collector SHALL get_metrics() 호출 시 resource_tags의 _api_type에 따라 올바른 디멘션 키(ApiName 또는 ApiId)와 메트릭 이름을 사용한다

##### 3-F. 기본 임계치

23. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 ApiLatency=3000, Api4XXError=1, Api5XXError=1, Api4xx=1, Api5xx=1, WsConnectCount=1000, WsMessageCount=10000, WsIntegrationError=0, WsExecutionError=0을 추가한다


### Requirement 4: ACM 인증서 만료 모니터링

**User Story:** As a 운영자, I want ACM 인증서 만료 잔여일을 모니터링하고 싶다, so that 인증서 만료로 인한 서비스 장애를 사전에 방지할 수 있다.

#### Acceptance Criteria

1. THE Alarm_Registry SHALL resource_type ACM에 대해 DaysToExpiry(<14일) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL ACM 알람에 네임스페이스 AWS/CertificateManager, 디멘션 키 CertificateArn을 사용한다
3. WHEN ACM Collector가 실행되면, THE Collector SHALL 태그 필터 없이 계정 내 모든 ACM 인증서를 수집한다 (Full_Collection)
4. THE ACM Collector SHALL 상태가 ISSUED인 인증서만 모니터링 대상에 포함한다
5. WHEN ACM Collector가 메트릭을 조회하면, THE Collector SHALL DaysToExpiry 값을 반환한다
6. THE Daily_Monitor SHALL ACM Collector를 _COLLECTOR_MODULES에 포함한다
7. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 ACM을 추가한다
8. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 DaysToExpiry=14를 추가한다
9. THE ACM Collector SHALL 반환하는 ResourceInfo의 tags에 Monitoring=on을 자동 삽입하여 하위 파이프라인 호환성을 유지한다


### Requirement 5: AWS Backup 모니터링

**User Story:** As a 운영자, I want AWS Backup의 실패/중단 작업 수를 모니터링하고 싶다, so that 백업 실패를 즉시 감지할 수 있다.

#### Acceptance Criteria

1. WHEN Monitoring=on 태그가 있는 Backup Vault가 존재하면, THE Alarm_Registry SHALL resource_type Backup에 대해 BackupJobsFailed(>0)과 BackupJobsAborted(>0) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL Backup 알람에 네임스페이스 AWS/Backup, 디멘션 키 BackupVaultName을 사용한다
3. WHEN Backup Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 Backup Vault 목록을 반환한다
4. WHEN Backup Collector가 메트릭을 조회하면, THE Collector SHALL NumberOfBackupJobsFailed와 NumberOfBackupJobsAborted 값을 반환한다
5. THE Daily_Monitor SHALL Backup Collector를 _COLLECTOR_MODULES에 포함한다
6. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 Backup을 추가한다
7. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 BackupJobsFailed=0, BackupJobsAborted=0을 추가한다


### Requirement 6: Amazon MQ 모니터링

**User Story:** As a 운영자, I want Amazon MQ 브로커의 CPU, Heap, Store 사용률을 모니터링하고 싶다, so that 메시지 브로커 리소스 포화를 사전에 감지할 수 있다.

#### Acceptance Criteria

1. WHEN Monitoring=on 태그가 있는 MQ 브로커가 존재하면, THE Alarm_Registry SHALL resource_type MQ에 대해 MqCPU(>90%), HeapUsage(>80%), JobSchedulerStoreUsage(>80%), StoreUsage(>80%) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL MQ 알람에 네임스페이스 AWS/AmazonMQ, 디멘션 키 Broker를 사용한다
3. WHEN MQ Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 MQ 브로커 목록을 반환한다
4. WHEN MQ Collector가 메트릭을 조회하면, THE Collector SHALL CpuUtilization, HeapUsage, JobSchedulerStorePercentUsage, StorePercentUsage 값을 반환한다
5. THE Daily_Monitor SHALL MQ Collector를 _COLLECTOR_MODULES에 포함한다
6. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 MQ를 추가한다
7. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 MqCPU=90, HeapUsage=80, JobSchedulerStoreUsage=80, StoreUsage=80을 추가한다


### Requirement 7: Classic Load Balancer (CLB) 모니터링

**User Story:** As a 운영자, I want CLB의 UnHealthyHost, HTTP 에러, SurgeQueue, Spillover를 모니터링하고 싶다, so that 레거시 로드밸런서 가용성 문제를 감지할 수 있다.

#### Acceptance Criteria

1. WHEN Monitoring=on 태그가 있는 CLB가 존재하면, THE Alarm_Registry SHALL resource_type CLB에 대해 CLBUnHealthyHost(>0), CLB5XX(>300), CLB4XX(>300), CLBBackend5XX(>300), CLBBackend4XX(>300), SurgeQueueLength(>300), SpilloverCount(>300) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL CLB 알람에 네임스페이스 AWS/ELB, 디멘션 키 LoadBalancerName을 사용한다
3. WHEN CLB Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 Classic Load Balancer 목록을 반환한다
4. WHEN CLB Collector가 메트릭을 조회하면, THE Collector SHALL UnHealthyHostCount, HTTPCode_ELB_5XX, HTTPCode_ELB_4XX, HTTPCode_Backend_5XX, HTTPCode_Backend_4XX, SurgeQueueLength, SpilloverCount 값을 반환한다
5. THE Daily_Monitor SHALL CLB Collector를 _COLLECTOR_MODULES에 포함한다
6. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 CLB를 추가한다
7. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 CLBUnHealthyHost=0, CLB5XX=300, CLB4XX=300, CLBBackend5XX=300, CLBBackend4XX=300, SurgeQueueLength=300, SpilloverCount=300을 추가한다


### Requirement 8: OpenSearch 모니터링

**User Story:** As a 운영자, I want OpenSearch 도메인의 클러스터 상태, 스토리지, CPU, JVM을 모니터링하고 싶다, so that 검색 엔진 가용성과 성능 문제를 사전에 감지할 수 있다.

#### Acceptance Criteria

1. WHEN Monitoring=on 태그가 있는 OpenSearch 도메인이 존재하면, THE Alarm_Registry SHALL resource_type OpenSearch에 대해 ClusterStatusRed(>0), ClusterStatusYellow(>0), OSFreeStorageSpace(<20480), ClusterIndexWritesBlocked(>0), OsCPU(>80%), JVMMemoryPressure(>80%), MasterCPU(>50%), MasterJVMMemoryPressure(>80%) 알람 정의를 제공한다
2. THE Alarm_Registry SHALL OpenSearch 알람에 네임스페이스 AWS/ES, Compound_Dimension으로 DomainName과 ClientId를 사용한다
3. WHEN OpenSearch Collector가 실행되면, THE Collector SHALL Monitoring=on 태그가 있는 OpenSearch 도메인 목록을 반환한다
4. WHEN OpenSearch Collector가 메트릭을 조회하면, THE Collector SHALL ClusterStatus.red, ClusterStatus.yellow, FreeStorageSpace, ClusterIndexWritesBlocked, CPUUtilization, JVMMemoryPressure, MasterCPUUtilization, MasterJVMMemoryPressure 값을 반환한다
5. THE OpenSearch Collector SHALL 메트릭 조회 시 DomainName과 ClientId 두 디멘션을 모두 포함하여 CloudWatch API를 호출한다
6. THE Daily_Monitor SHALL OpenSearch Collector를 _COLLECTOR_MODULES에 포함한다
7. THE Monitoring_Engine SHALL SUPPORTED_RESOURCE_TYPES에 OpenSearch를 추가한다
8. THE Monitoring_Engine SHALL HARDCODED_DEFAULTS에 ClusterStatusRed=0, ClusterStatusYellow=0, OSFreeStorageSpace=20480, ClusterIndexWritesBlocked=0, OsCPU=80, JVMMemoryPressure=80, MasterCPU=50, MasterJVMMemoryPressure=80을 추가한다


### Requirement 9: Alarm_Registry 데이터 등록 (공통)

**User Story:** As a 개발자, I want 8개 리소스 타입의 알람 정의가 Alarm_Registry에 일관되게 등록되길 원한다, so that alarm_manager가 알람을 자동 생성할 수 있다.

#### Acceptance Criteria

1. THE Alarm_Registry SHALL 8개 신규 리소스 타입 각각에 대해 알람 정의 리스트를 정의한다
2. THE Alarm_Registry SHALL _get_alarm_defs()에서 8개 신규 resource_type을 분기 처리한다
3. THE Alarm_Registry SHALL APIGW resource_type에 대해 _api_type Internal_Tag 값(REST, HTTP, WEBSOCKET)에 따라 서로 다른 알람 정의를 반환한다 (ALB/NLB의 _lb_type 패턴 준용)
4. THE Alarm_Registry SHALL _HARDCODED_METRIC_KEYS에 8개 신규 리소스 타입의 메트릭 키 집합을 등록한다
5. THE Alarm_Registry SHALL _NAMESPACE_MAP에 8개 신규 리소스 타입의 CloudWatch 네임스페이스를 등록한다 (APIGW는 모든 타입이 AWS/ApiGateway 공유)
6. THE Alarm_Registry SHALL _DIMENSION_KEY_MAP에 8개 신규 리소스 타입의 디멘션 키를 등록한다 (APIGW는 _api_type에 따라 ApiName 또는 ApiId 분기)
7. THE Alarm_Registry SHALL _METRIC_DISPLAY에 모든 신규 메트릭의 (display_name, direction, unit) 매핑을 등록한다
8. THE Alarm_Registry SHALL _metric_name_to_key()에 신규 CloudWatch metric_name에서 내부 metric key로의 매핑을 등록한다 (REST의 4XXError/5XXError와 HTTP의 4xx/5xx를 각각 별도 키로 매핑)


### Requirement 10: CloudTrail 이벤트 등록 (공통)

**User Story:** As a 개발자, I want 신규 리소스의 생명주기 API가 CloudTrail 이벤트로 등록되길 원한다, so that 리소스 생성/삭제/태그 변경 시 실시간 대응이 가능하다.

#### Acceptance Criteria

1. THE Monitoring_Engine SHALL MONITORED_API_EVENTS의 CREATE/DELETE/TAG_CHANGE 카테고리에 8개 신규 리소스 타입의 생명주기 API를 추가한다
2. THE Remediation_Handler SHALL _API_MAP에 8개 신규 리소스 타입의 (resource_type, id_extractor) 매핑을 추가한다
3. THE template.yaml SHALL CloudTrailModifyRule EventPattern에 8개 신규 리소스 타입의 API 이벤트를 추가한다
4. IF CloudTrail 이벤트에서 리소스 ID 추출이 실패하면, THEN THE Remediation_Handler SHALL 에러를 로깅하고 해당 이벤트를 건너뛴다

### Requirement 11: template.yaml IAM 권한 (공통)

**User Story:** As a 개발자, I want Lambda가 8개 신규 리소스의 AWS API를 호출할 IAM 권한을 갖길 원한다, so that Collector와 Remediation_Handler가 정상 동작한다.

#### Acceptance Criteria

1. THE template.yaml SHALL Daily_Monitor Lambda IAM Role에 8개 신규 리소스의 Describe/List API 권한을 추가한다
2. THE template.yaml SHALL Daily_Monitor Lambda IAM Role에 8개 신규 리소스의 태그 조회 API 권한을 추가한다
3. THE template.yaml SHALL Remediation_Handler Lambda IAM Role에 8개 신규 리소스의 생명주기 관련 API 권한을 추가한다


### Requirement 12: 고아 알람 정리 지원 (공통)

**User Story:** As a 운영자, I want 삭제된 신규 리소스의 알람이 자동 정리되길 원한다, so that 불필요한 고아 알람이 남지 않는다.

#### Acceptance Criteria

1. THE Daily_Monitor SHALL alive_checkers에 8개 신규 리소스 타입의 존재 확인 함수를 등록한다
2. WHEN 신규 리소스가 삭제되면, THE Daily_Monitor SHALL 해당 리소스의 알람을 고아 알람으로 식별하여 삭제한다
3. THE Daily_Monitor SHALL 각 신규 리소스 타입에 대해 _find_alive_* 함수를 구현한다

### Requirement 13: ACM Full_Collection 특수 처리

**User Story:** As a 개발자, I want ACM Collector가 태그 필터 없이 모든 인증서를 수집하길 원한다, so that 태그 미부착 인증서도 만료 모니터링 대상에 포함된다.

#### Acceptance Criteria

1. THE ACM Collector SHALL list_certificates API로 계정 내 모든 인증서를 조회한다
2. THE ACM Collector SHALL 상태가 ISSUED인 인증서만 모니터링 대상에 포함한다
3. THE ACM Collector SHALL ResourceInfo의 tags에 Monitoring=on을 자동 삽입하여 alarm_manager 파이프라인과 호환성을 유지한다
4. IF list_certificates API 호출이 실패하면, THEN THE ACM Collector SHALL 에러를 로깅하고 예외를 전파한다

### Requirement 14: SRE 골든 시그널 커버리지

**User Story:** As a 운영자, I want 각 신규 리소스의 하드코딩 알람이 SRE 4대 골든 시그널을 가능한 한 커버하길 원한다, so that 핵심 장애 시그널을 놓치지 않는다.

#### Acceptance Criteria

1. THE Alarm_Registry SHALL Lambda 알람에서 Latency(Duration)와 Errors를 커버한다
2. THE Alarm_Registry SHALL APIGW REST/HTTP 알람에서 Latency와 Errors(4XX/4xx, 5XX/5xx)를 커버한다
3. THE Alarm_Registry SHALL APIGW WebSocket 알람에서 Traffic(ConnectCount, MessageCount)과 Errors(IntegrationError, ExecutionError)를 커버한다
4. THE Alarm_Registry SHALL CLB 알람에서 Errors(5XX, 4XX, Backend)와 Saturation(UnHealthyHost, SurgeQueue, Spillover)을 커버한다
5. THE Alarm_Registry SHALL OpenSearch 알람에서 Errors(ClusterStatusRed, WritesBlocked)와 Saturation(CPU, JVM, FreeStorage)을 커버한다
6. THE Alarm_Registry SHALL MQ 알람에서 Saturation(CPU, Heap, Store)을 커버한다
7. THE Alarm_Registry SHALL Backup 알람에서 Errors(JobsFailed, JobsAborted)를 커버한다
