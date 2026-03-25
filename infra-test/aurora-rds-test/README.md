# Aurora RDS 모니터링 테스트 인프라

Aurora MySQL Serverless v2 최소 사양으로 AuroraRDS 모니터링 기능 E2E 검증.

## 배포

```bash
aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name aurora-rds-test \
  --parameter-overrides \
    VpcId=vpc-xxxxxxxx \
    SubnetIds=subnet-aaaa,subnet-bbbb \
    MasterUserPassword=YourPassword123
```

## 테스트 순서

1. 스택 생성 완료 대기 (~10분)
2. Daily Monitor Lambda 수동 실행 (콘솔 또는 CLI)
3. CloudWatch 알람 확인:
   - `[AuroraRDS] aurora-rds-test-writer CPUUtilization >90% (aurora-rds-test-writer)` 
   - `[AuroraRDS] aurora-rds-test-writer FreeableMemory <2GB (aurora-rds-test-writer)`
   - `[AuroraRDS] aurora-rds-test-writer DatabaseConnections >100 (aurora-rds-test-writer)`
   - `[AuroraRDS] aurora-rds-test-writer FreeLocalStorage <5GB (aurora-rds-test-writer)`
   - `[AuroraRDS] aurora-rds-test-writer AuroraReplicaLagMaximum >2000000μs (aurora-rds-test-writer)`
4. 태그 변경 테스트: `Threshold_CPU=95`로 변경 → re-sync 확인
5. 스택 삭제 → 고아 알람 정리 확인

## 정리

```bash
aws cloudformation delete-stack --stack-name aurora-rds-test
```

## 비용

- Serverless v2 최소 0.5 ACU (~$0.06/hr, 서울 리전 기준)
- 스토리지: 최소 과금
- 테스트 후 즉시 삭제 권장
