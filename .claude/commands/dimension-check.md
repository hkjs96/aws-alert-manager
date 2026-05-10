# /dimension-check — 알람 디멘션 검증

> 원본: `.kiro/hooks/dimension-check-reminder.kiro.hook` (fileEdited)

`alarm_registry.py` 또는 `dimension_builder.py`를 수정한 후 이 커맨드를 실행한다.

## 검증 항목

### 1. 새 메트릭 디멘션 확인 (§6-1)
- AWS 공식 문서에서 해당 메트릭의 Dimensions 열을 확인했는가?
- 참고 URL:
  - EC2: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/viewing_metrics_with_cloudwatch.html
  - RDS: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/dimensions.html
  - ALB: https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-cloudwatch-metrics.html
  - NLB: https://docs.aws.amazon.com/elasticloadbalancing/latest/network/load-balancer-cloudwatch-metrics.html

### 2. LB 레벨 vs TG 레벨 구분
- LB 레벨 메트릭에 TG 디멘션 추가 시 `INSUFFICIENT_DATA` 발생
- ALB LB 레벨(`HTTPCode_ELB_5XX_Count` 등) → `LoadBalancer` 단일
- TG 레벨 → `TargetGroup` + `LoadBalancer` 복합

### 3. 글로벌 서비스 디멘션 (§8-3)
| 리소스 | 필수 디멘션 |
|--------|-----------|
| CloudFront | `DistributionId` + `Region: Global` |
| Route53 | `HealthCheckId` |
| WAF | `WebACL` + `Rule` + `Region: {region}` |
| S3 (Request Metrics) | `BucketName` + `FilterId: EntireBucket` |

### 4. Compound Dimension 보조 디멘션
- ECS, WAF, S3, SageMaker 등 복합 디멘션 리소스 확인

### 5. treat_missing_data 설정
- Route53 HealthCheck, DX ConnectionState, MSK ActiveControllerCount → `breaching`
- 기타 기본값은 `missing`

## 실행

`common/alarm_registry.py`와 `common/dimension_builder.py`의 최근 변경 사항을 읽고, 위 5개 항목에 대해 검증 결과를 보고한다.
