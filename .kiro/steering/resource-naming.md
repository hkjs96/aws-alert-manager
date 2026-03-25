---
inclusion: manual
---

# AWS 리소스 Name 태그 네이밍 컨벤션

## 포맷

```
{env}-{resource_type}-{service}-{seq}
```

| 세그먼트 | 설명 | 예시 |
|----------|------|------|
| `env` | 환경 | `dev`, `stg`, `prod` |
| `resource_type` | AWS 리소스 타입 약어 | 아래 표 참조 |
| `service` | 서비스/앱 이름 | `web`, `api`, `order` |
| `seq` | 순번 또는 용도 (선택) | `01`, `http`, `grpc` |

## 리소스 타입 약어

| 약어 | 리소스 | 비고 |
|------|--------|------|
| `ec2` | EC2 Instance | |
| `rds` | RDS Instance | |
| `alb` | Application Load Balancer | |
| `nlb` | Network Load Balancer | |
| `tg` | Target Group | LB 타입과 무관하게 `tg` 사용 |
| `sg` | Security Group | |
| `vpc` | VPC | |
| `sn` | Subnet | |
| `rt` | Route Table | |
| `igw` | Internet Gateway | |
| `nat` | NAT Gateway | |
| `s3` | S3 Bucket | |
| `lam` | Lambda Function | |
| `cw` | CloudWatch Alarm/Dashboard | |

## 예시

```
prod-alb-web
prod-nlb-api
prod-tg-web-http
prod-tg-api-grpc
dev-ec2-web-01
dev-ec2-web-02
dev-rds-order
stg-sg-web-public
prod-vpc-main
prod-sn-public-1a
prod-sn-private-1b
```

## 규칙

- 소문자 + 숫자 + 하이픈(`-`)만 사용
- 하이픈으로 시작하거나 끝나지 않음
- TG 이름은 AWS 제한 32자 이내
- ALB/NLB 이름은 AWS 제한 32자 이내
- CloudFormation 스택 이름에 리소스 타입을 넣지 않음 (혼동 방지)
  - 나쁜 예: `nlb-alb-ec2-lab` → ALB 이름이 `nlb-...`로 시작하는 혼동 유발
  - 좋은 예: `monitoring-lab-dev`, `web-service-prod`
- 환경이 단일 계정에 하나뿐이면 `env` 생략 가능 (`alb-web`, `ec2-api-01`)

## 참고

- [AWS 공식 태깅 가이드](https://docs.aws.amazon.com/tag-editor/latest/userguide/best-practices-and-strats.html)
- 환경 우선 패턴은 클라우드 아키텍트들이 가장 많이 권장하는 방식
- 리소스 타입을 두 번째에 두면 콘솔에서 환경 필터링 + 타입 구분이 동시에 가능
