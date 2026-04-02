# 구현 계획: Extended Resources E2E Test

## 개요

11개 확장 리소스 타입(SQS, ECS, MSK, DynamoDB, CloudFront, WAF, Route53, EFS, S3, SageMaker, SNS)의 알람 자동 생성을 검증하기 위한 독립 CloudFormation 스택(`infra-test/extended-resources-test/template.yaml`)과 트래픽 테스트 스크립트(`infra-test/extended-resources-test/traffic-test.sh`)를 구현한다.

기존 `infra-test/remaining-resources-test/` 패턴을 따르며, 순수 CloudFormation(SAM 미사용), AWSTemplateFormatVersion 2010-09-09를 사용한다. DX(Direct Connect)는 물리 연결이 필요하므로 제외한다.

## Tasks

- [x] 1. CFN 템플릿 스켈레톤 및 IAM/SG 리소스 생성
  - [x] 1.1 `infra-test/extended-resources-test/template.yaml` 파일 생성: AWSTemplateFormatVersion, Description(비용 ~$0.20/hr 안내, DX 제외 사유, 테스트 직후 즉시 삭제 안내), Parameters(Environment, VpcId, SubnetId1, SubnetId2) 정의
    - 기존 `infra-test/remaining-resources-test/template.yaml`의 네이밍 패턴(`${Environment}-e2e-extended-*`) 준수
    - template.yaml에 non-ASCII 문자 사용 금지 (AWS CLI 호환)
    - _Requirements: 1.1, 1.2, 1.3, 1.6, 1.7, 9.1, 9.2, 15.3_
  - [x] 1.2 IAM 리소스 생성: EcsTaskExecutionRole(AmazonECSTaskExecutionRolePolicy), SageMakerRole(AmazonSageMakerFullAccess + S3), S3CleanupRole(s3:DeleteObject, s3:ListBucket)
    - _Requirements: 3.6, 12.4, 17.1_
  - [x] 1.3 Security Group 리소스 생성: EcsSecurityGroup(아웃바운드 전체 허용), MskSecurityGroup(9092/9094 인바운드), WafAlbSecurityGroup(HTTP:80 인바운드 0.0.0.0/0), EfsMountTargetSecurityGroup(NFS:2049 인바운드)
    - 모든 SG를 VpcId 파라미터로 지정된 VPC에 생성
    - _Requirements: 3.8, 4.6, 7.5, 10.4, 18.1, 18.2, 18.3, 18.4, 18.5_

- [x] 2. SQS + ECS Fargate + SNS 리소스 생성
  - [x] 2.1 SQS 리소스 추가: SqsQueue(표준 큐, Monitoring=on 태그)
    - _Requirements: 2.1, 2.2, 2.3_
  - [x] 2.2 ECS 리소스 추가: EcsCluster, EcsTaskDefinition(Fargate, 256 CPU/512 MB, public.ecr.aws/nginx/nginx:latest), EcsService(FARGATE, desiredCount=1, 퍼블릭 IP 할당, Monitoring=on 태그)
    - EcsService를 SubnetId1에 배치, AssignPublicIp=ENABLED
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.7_
  - [x] 2.3 SNS 리소스 추가: SnsTopic(표준 토픽, Monitoring=on 태그)
    - _Requirements: 13.1, 13.2_

- [x] 3. MSK + DynamoDB 리소스 생성
  - [x] 3.1 MSK 리소스 추가: MskCluster(kafka.t3.small x 2 브로커, 10GB EBS, 2 AZ 서브넷, Monitoring=on 태그). 비용 경고 주석 포함 (~$0.08/hr)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.7, 15.1, 15.4_
  - [x] 3.2 DynamoDB 리소스 추가: DynamoDBTable(PAY_PER_REQUEST, 파티션 키 id:String, Monitoring=on 태그)
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [x] 4. Checkpoint - CFN 템플릿 중간 검증 (Part 1)
  - YAML 문법 검증 및 리소스 참조 정합성 확인, 질문이 있으면 사용자에게 문의한다.

- [x] 5. CloudFront + S3 Origin 리소스 생성
  - [x] 5.1 CloudFront 오리진용 S3 버킷 생성: CloudFrontOriginBucket
    - _Requirements: 6.3_
  - [x] 5.2 CloudFront 리소스 추가: CloudFrontOAC(Origin Access Control), CloudFrontDistribution(S3 오리진, OAC 연동, Monitoring=on 태그), CloudFrontBucketPolicy(OAC를 통한 S3 접근 허용)
    - _Requirements: 6.1, 6.2, 6.4, 6.5_

- [x] 6. WAF + ALB + Route53 리소스 생성
  - [x] 6.1 WAF 리소스 추가: WafWebAcl(REGIONAL 스코프, 기본 Allow, Rate-based 규칙 limit=2000, Monitoring=on 태그), WafAlb(internet-facing, 2 AZ 서브넷), WafAlbTargetGroup, WafAlbListener(HTTP:80, 고정 응답 200), WafWebAclAssociation
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.6_
  - [x] 6.2 Route53 리소스 추가: Route53HealthCheck(HTTP 타입, WAF ALB DNS 대상, Port 80, Monitoring=on 태그)
    - DependsOn 또는 !GetAtt WafAlb.DNSName 참조로 의존성 해결
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 7. EFS + S3 (Request Metrics) 리소스 생성
  - [x] 7.1 EFS 리소스 추가: EfsFileSystem(Bursting 처리량 모드, Monitoring=on 태그), EfsMountTarget(SubnetId1, 1개)
    - _Requirements: 10.1, 10.2, 10.3, 10.5_
  - [x] 7.2 S3 리소스 추가: S3Bucket(MetricsConfiguration 활성화, Monitoring=on 태그), S3CleanupFunction(스택 삭제 시 객체 정리 Lambda), S3CleanupCustomResource
    - CustomResource Delete 핸들러에서 에러 시에도 SUCCESS 반환
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 17.1, 17.2_

- [x] 8. SageMaker 리소스 생성
  - [x] 8.1 SageMaker 리소스 추가: SageMakerModelBucket(모델 아티팩트 S3 버킷), SageMakerModelUpload(CustomResource Lambda - 빈 tar.gz 업로드), SageMakerModel(scikit-learn 컨테이너 366743142698.dkr.ecr.ap-northeast-2.amazonaws.com/sagemaker-scikit-learn:1.2-1-cpu-py3), SageMakerEndpointConfig(ml.t2.medium), SageMakerEndpoint(Monitoring=on 태그)
    - 비용 경고 주석 포함 (~$0.065/hr)
    - S3CleanupFunction 공유하여 SageMakerModelBucket도 정리
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 15.1, 15.4_

- [x] 9. Outputs 섹션 및 최종 태그 검증
  - [x] 9.1 Outputs 섹션 추가: SqsQueueName, SqsQueueUrl, EcsClusterName, EcsServiceName, MskClusterName, MskClusterArn, DynamoDBTableName, CloudFrontDistributionId, CloudFrontDomainName, WafWebAclName, WafAlbDns, Route53HealthCheckId, EfsFileSystemId, S3BucketName, SageMakerEndpointName, SnsTopicName, SnsTopicArn, ExpectedAlarms(리소스별 예상 알람 수 ~35개)
    - _Requirements: 1.5, 2.3, 4.7, 5.4, 6.5, 7.6, 8.4, 10.5, 11.4, 12.6, 13.2, 16.1, 16.2_
  - [x] 9.2 전체 리소스 Monitoring=on 태그 부착 확인, DeletionProtection 비활성화 확인, 삭제 시간 소요 리소스(MSK/SageMaker/CloudFront) 주석 확인
    - _Requirements: 1.4, 15.2, 17.3_

- [x] 10. Checkpoint - CFN 템플릿 최종 검증
  - 전체 리소스 수 ~40개 확인, YAML 문법 최종 검증, 모든 리소스 참조 정합성 확인, 질문이 있으면 사용자에게 문의한다.

- [x] 11. 트래픽 테스트 스크립트 생성
  - [x] 11.1 `infra-test/extended-resources-test/traffic-test.sh` 파일 생성: shebang, usage 검증(6개 인자 필수: SQS_QUEUE_URL, DDB_TABLE_NAME, CF_DOMAIN, WAF_ALB_DNS, S3_BUCKET, SNS_TOPIC_ARN), 변수 할당
    - 인자 누락 시 usage 출력 후 exit 1
    - _Requirements: 14.1, 14.9, 14.10_
  - [x] 11.2 Phase 1-2 구현: SQS(10 send + 10 receive, aws sqs send-message/receive-message), DynamoDB(10 put + 10 get, aws dynamodb put-item/get-item)
    - _Requirements: 14.2, 14.3_
  - [x] 11.3 Phase 3-4 구현: CloudFront(20 curl, CF DomainName), WAF ALB(20 curl, ALB DNS)
    - _Requirements: 14.4, 14.5_
  - [x] 11.4 Phase 5-6 구현: S3(10 put + 10 get, aws s3api put-object/get-object), SNS(10 publish, aws sns publish)
    - S3 트래픽 전송 전 Request Metrics 15분 대기 안내 출력
    - _Requirements: 14.6, 14.7, 11.5_
  - [x] 11.5 Summary 구현: 완료 메시지 출력, ECS/MSK/Route53/EFS/SageMaker는 트래픽 미전송 안내 (자동 메트릭 발행)
    - _Requirements: 14.8_

- [x] 12. Final Checkpoint - 전체 검증
  - CFN 템플릿 YAML 문법 최종 확인, 트래픽 스크립트 실행 권한(chmod +x) 확인, 질문이 있으면 사용자에게 문의한다.

## Notes

- 이 스펙은 인프라 코드(CloudFormation + bash)이므로 단위 테스트/PBT가 적용되지 않는다
- 검증은 실제 AWS 배포 후 수동으로 수행한다 (스택 배포 → 트래픽 생성 → Daily Monitor 실행 → 알람 수 확인)
- 각 태스크는 이전 태스크의 결과물 위에 증분적으로 빌드된다
- Checkpoint에서 중간 검증을 수행하여 오류를 조기에 발견한다
- MSK 클러스터 생성 15~25분, SageMaker 엔드포인트 5~10분, CloudFront 배포 5~15분 소요
- 예상 총 비용: ~$0.20/hr — 테스트 직후 즉시 삭제 필수
- CloudFront/Route53 메트릭은 us-east-1에서만 발행 — Daily Monitor가 해당 리전에 알람 생성
