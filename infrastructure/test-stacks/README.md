# E2E / 통합 테스트 스택

알람 엔진의 리소스 디스커버리·알람 생성을 실제 AWS 리소스로 검증하기 위한
CloudFormation 테스트 스택 모음입니다.

> ⚠️ **과금 주의**: 이 스택들은 RDS·DocDB·ElastiCache·EC2·ALB/NLB 등
> **시간당 과금되는 실 리소스**를 생성합니다. 테스트가 끝나면 **반드시 스택을
> 삭제**해 비용이 계속 발생하지 않도록 하십시오.

## 스택 목록

| 디렉터리 | 용도 | 주요 리소스 |
|----------|------|-------------|
| `e2e-db-resources/` | DB 계열 디스커버리/알람 E2E | RDS, Aurora, DocDB, ElastiCache |
| `e2e-web-resources/` | 웹/트래픽 계열 E2E (+ ElastiCache) | EC2, ALB, NLB, TargetGroup, NAT, ElastiCache(Redis) |
| `e2e-all-resources/` | 전체 리소스 통합 | 다수 |
| `ec2-cwagent-test/` | CWAgent 메트릭(디스크/메모리) | EC2 |
| `extended-resources-test/` | 확장 리소스군 | 다수 |
| `nat-elasticache-test/` | NAT GW / ElastiCache | NAT, ElastiCache |
| `remaining-resources-test/` | 나머지 리소스군 | 다수 |

## 배포

```bash
aws cloudformation deploy \
  --stack-name e2e-db-resources \
  --template-file infrastructure/test-stacks/e2e-db-resources/template.yaml \
  --parameter-overrides Environment=test VpcId=... PrivateSubnetA=... PrivateSubnetB=... \
  --capabilities CAPABILITY_NAMED_IAM
```

파라미터(VPC/서브넷/AMI 등)는 각 `template.yaml`의 `Parameters` 섹션을 참고하십시오.

## Teardown (테스트 후 필수)

```bash
aws cloudformation delete-stack --stack-name e2e-db-resources
aws cloudformation wait stack-delete-complete --stack-name e2e-db-resources
```

배포한 모든 테스트 스택에 대해 위 삭제를 수행하십시오. 남은 스택 확인:

```bash
aws cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query "StackSummaries[?contains(StackName, 'e2e') || contains(StackName, 'test')].StackName"
```
