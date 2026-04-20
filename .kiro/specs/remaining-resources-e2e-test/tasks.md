# 구현 계획: Remaining Resources E2E Test

## 개요

8개 신규 리소스 타입(Lambda, VPN, API Gateway REST/HTTP/WebSocket, ACM, AWS Backup, Amazon MQ, CLB, OpenSearch)의 알람 자동 생성을 검증하기 위한 독립 CloudFormation 스택(`infra-test/remaining-resources-test/template.yaml`)과 트래픽 테스트 스크립트(`infra-test/remaining-resources-test/traffic-test.sh`)를 구현한다.

기존 `infra-test/e2e-all-resources/template.yaml` 패턴을 따르며, 순수 CloudFormation(SAM 미사용), AWSTemplateFormatVersion 2010-09-09를 사용한다.

## Tasks

- [ ] 1. CFN 템플릿 스켈레톤 및 공유 리소스 생성
  - [x] 1.1 `infra-test/remaining-resources-test/template.yaml` 파일 생성: AWSTemplateFormatVersion, Description(비용 안내 포함), Parameters(Environment, VpcId, SubnetId1, SubnetId2, MQPassword, AmiId) 정의
    - 기존 `infra-test/e2e-all-resources/template.yaml`의 네이밍 패턴(`${Environment}-e2e-*`) 준수
    - Description에 "테스트 직후 즉시 삭제" 및 예상 비용(~$0.17/hr) 안내 포함
    - _Requirements: 1.1, 1.2, 1.3, 1.6, 13.3, 13.4_
  - [x] 1.2 IAM 리소스 생성: LambdaRole(AWSLambdaBasicExecutionRole), BackupRole(AWSBackupServiceRolePolicyForBackup), Ec2Role+Ec2InstanceProfile(SSM)
    - _Requirements: 2.6, 8.5, 10.5_
  - [x] 1.3 Security Group 리소스 생성: ClbSecurityGroup(HTTP:80 인바운드 0.0.0.0/0), Ec2SecurityGroup(CLB SG로부터 HTTP:80 인바운드 + 전체 아웃바운드)
    - _Requirements: 15.1, 15.2, 15.3_

- [ ] 2. Lambda + API Gateway REST 리소스 생성
  - [x] 2.1 Lambda 리소스 추가: LambdaFunction(Python 3.12, ZipFile 인라인 핸들러, ReservedConcurrentExecutions=2, Monitoring=on 태그), LambdaPermission(APIGW → Lambda 호출 허용)
    - 인라인 코드: `def handler(event, context): return {"statusCode": 200, "body": '{"status":"ok"}'}`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - [x] 2.2 API Gateway REST 리소스 추가: RestApi(Monitoring=on 태그), RestApiMethod(ANY, Lambda 프록시 통합, root 리소스), RestApiDeployment(DependsOn: RestApiMethod), RestApiStage(dev)
    - _Requirements: 3.1, 3.2, 3.3_

- [ ] 3. API Gateway HTTP + WebSocket 리소스 생성
  - [x] 3.1 HTTP API 리소스 추가: HttpApi(ProtocolType=HTTP, Monitoring=on 태그), HttpApiIntegration(Lambda 프록시, payloadFormatVersion=2.0), HttpApiRoute($default), HttpApiStage($default, AutoDeploy=true)
    - _Requirements: 4.1, 4.2, 4.3_
  - [x] 3.2 WebSocket API 리소스 추가: WsApi(ProtocolType=WEBSOCKET, RouteSelectionExpression=$request.body.action, Monitoring=on 태그), WsIntegration(Mock, Type=MOCK), WsConnectRoute($connect), WsDisconnectRoute($disconnect), WsDefaultRoute($default), WsDeployment(DependsOn 3개 라우트), WsStage(dev)
    - _Requirements: 5.1, 5.2, 5.3_

- [ ] 4. Checkpoint - CFN 템플릿 중간 검증
  - YAML 문법 검증 및 리소스 참조 정합성 확인, 질문이 있으면 사용자에게 문의한다.

- [ ] 5. VPN 리소스 생성
  - [x] 5.1 VPN 리소스 추가: VpnGateway(Type=ipsec.1), VpnGatewayAttachment(VpcId 연결), CustomerGateway(IP=203.0.113.1, Type=ipsec.1, BgpAsn=65000), VpnConnection(StaticRoutesOnly=true, Monitoring=on 태그)
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [ ] 6. ACM + AWS Backup 리소스 생성
  - [x] 6.1 ACM 리소스 추가: AcmCertificate(DNS 검증, DomainName=e2e-test.example.com, Monitoring=on 태그)
    - PENDING_VALIDATION 상태 유지 — 검증 완료 불필요
    - _Requirements: 7.1, 7.2, 7.3_
  - [x] 6.2 AWS Backup 리소스 추가: DynamoDBTable(PAY_PER_REQUEST, 단순 파티션 키), BackupVault(Monitoring=on 태그), BackupPlan(일일 백업 cron(0 5 ? * * *), DeleteAfterDays=1), BackupSelection(DynamoDB 테이블 대상)
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [ ] 7. Amazon MQ + CLB 리소스 생성
  - [x] 7.1 MQ 리소스 추가: MqBroker(ActiveMQ, SINGLE_INSTANCE, mq.t3.micro, PubliclyAccessible=true, 관리자 사용자, Monitoring=on 태그)
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 15.4_
  - [x] 7.2 CLB 리소스 추가: ClbEc2Instance(t3.micro, httpd UserData, Ec2InstanceProfile, Monitoring=on 태그), ClassicLoadBalancer(internet-facing, HTTP:80 리스너, Health Check HTTP:80:/, EC2 인스턴스 타겟, Monitoring=on 태그)
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

- [ ] 8. OpenSearch + Outputs 섹션 생성
  - [x] 8.1 OpenSearch 리소스 추가: OpenSearchDomain(t3.small.search, 단일 노드, 전용 마스터 비활성화, EBS gp3 10GB, 오픈 접근 정책, Monitoring=on 태그)
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_
  - [x] 8.2 Outputs 섹션 추가: LambdaFunctionName, RestApiUrl, HttpApiUrl, WsApiUrl, VpnConnectionId, AcmCertificateArn, BackupVaultName, MqBrokerId, MqBrokerName, ClbDnsName, ClbName, OpenSearchDomainName, OpenSearchEndpoint, ExpectedAlarms(리소스별 예상 알람 수 ~35개)
    - _Requirements: 1.5, 3.4, 4.4, 5.4, 14.1, 14.2_

- [ ] 9. Checkpoint - CFN 템플릿 최종 검증
  - 전체 리소스 수 ~30개 확인, 모든 리소스에 Monitoring=on 태그 부착 확인, DeletionProtection 비활성화 확인, 질문이 있으면 사용자에게 문의한다.
  - _Requirements: 1.4, 13.1, 13.2_

- [ ] 10. 트래픽 테스트 스크립트 생성
  - [x] 10.1 `infra-test/remaining-resources-test/traffic-test.sh` 파일 생성: shebang, usage 검증(4개 인자 필수), 변수 할당
    - `Usage: ./traffic-test.sh <REST_API_URL> <HTTP_API_URL> <WS_API_URL> <CLB_DNS>`
    - _Requirements: 12.1, 12.2_
  - [x] 10.2 Phase 1 구현: APIGW REST 순차 curl 요청 (20회)
    - _Requirements: 12.3_
  - [x] 10.3 Phase 2 구현: APIGW REST 동시 curl 요청 (20회, xargs -P 10)
    - _Requirements: 12.4_
  - [ ] 10.4 Phase 3 구현: APIGW HTTP 순차 curl 요청 (20회)
    - _Requirements: 12.5_
  - [x] 10.5 Phase 4 구현: WebSocket 연결 테스트 (5 cycles, wscat 우선 → curl fallback)
    - _Requirements: 12.6_
  - [x] 10.6 Phase 5 구현: CLB 순차 curl 요청 (20회)
    - _Requirements: 12.7_
  - [x] 10.7 Summary 구현: 5분 대기 메시지 출력, VPN/ACM/MQ/OpenSearch/Backup은 트래픽 미전송 안내
    - _Requirements: 12.8_

- [ ] 11. Final Checkpoint - 전체 검증
  - CFN 템플릿 YAML 문법 최종 확인, 트래픽 스크립트 실행 권한(chmod +x) 확인, 질문이 있으면 사용자에게 문의한다.

## Notes

- 이 스펙은 인프라 코드(CloudFormation + bash)이므로 단위 테스트/PBT가 적용되지 않는다
- 검증은 실제 AWS 배포 후 수동으로 수행한다 (스택 배포 → 트래픽 생성 → Daily Monitor 실행 → 알람 수 확인)
- 각 태스크는 이전 태스크의 결과물 위에 증분적으로 빌드된다
- Checkpoint에서 중간 검증을 수행하여 오류를 조기에 발견한다
