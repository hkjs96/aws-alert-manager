# AWS Monitoring Engine — 리소스 타입별 테스트 가능성 매트릭스

discovery/토글을 **실물 리소스로 검증**할 때, 각 리소스 타입을 실제로
프로비저닝하는 것이 얼마나 현실적인지(비용·난이도·제약)를 기록한다.

> **전제:** discovery는 *계정에 실제로 존재하는* 리소스만 인벤토리에 올린다.
> 어떤 타입의 리소스가 0개면 필터 드롭다운에 옵션은 떠도 리스트엔 행이 안 나온다.
> 이는 버그가 아니라 정상 동작이다. 따라서 UI에서 어떤 타입을 "보려면"
> 그 타입의 실물이 계정에 있어야 한다.

관련: discovery 커버리지 = `SUPPORTED_RESOURCE_TYPES` 29종 전부
(`backend/common/resource_discovery.py::discover_resources`). 토글은 Resource
Groups Tagging API로 일반화(`_set_resource_monitoring_tag`). 메트릭 제약은
`docs/KNOWN-ISSUES.md` 참조.

---

## 현재 계정 스냅샷 (2026-06-09, us-east-1, profile tlsgks678_poc)

`daily_monitor` invoke 결과 `discovered: 29, synced: 29`. 실물이 있는 타입:

| 타입 | 개수 | 출처 |
|------|------|------|
| Lambda | 8 | 매니저 자기 인프라 |
| S3 | 5 | 매니저 자기 인프라(배포 버킷 등) |
| DynamoDB | 6 | 매니저 자기 테이블(inventory/jobs/accounts 등) |
| SNS | 6 | 매니저 알림 토픽 등 |
| SQS | 3 | 매니저 bulk 큐 등 |
| APIGW | 1 | `alarm-manager-api-dev`(HTTP API v2) |

나머지 23종(EC2/RDS/LB/ElastiCache/MQ/MSK/WAF/DX/SageMaker/CloudFront/Route53/
EFS/Backup/NAT/VPN/ACM/OpenSearch/DocDB/CLB/ECS/TG/AuroraRDS …)은 **현재 0개**.
(이전 e2e 검증 스택을 내린 상태라 모니터링 "대상" 리소스가 없다.)

---

## 등급별 분류

### A. 이미 존재 — $0 즉시 검증 (provision 불필요)
**Lambda · S3 · SQS · DynamoDB · SNS · APIGW**

매니저 자기 인프라라 이미 인벤토리에 떠 있다. 토글(ON→태그 확인→OFF)을
**지금 바로** 검증할 수 있다. (SQS/DynamoDB/SNS/APIGW는 이번에 추가한 신규 타입.)

### B. 무료 · 즉시 생성 (CLI 한 줄, $0) — ⭐ 권장 테스트
| 타입 | 생성 | 비용 | 비고 |
|------|------|------|------|
| **Backup** | `aws backup create-backup-vault --backup-vault-name <name>` | **$0** | 빈 vault는 무과금(복구 포인트 저장 시 과금) |
| **EFS** | `aws efs create-file-system --tags Key=Name,Value=<name>` | **$0** | 저장 데이터 0이면 무과금, bursting 처리량 무료 |
| **TG** | `aws elbv2 create-target-group --name <name> --protocol HTTP --port 80 --vpc-id <vpc>` | **$0** | LB 없이 standalone 생성 가능. 기본 VPC 필요 |

→ 신규 타입(Backup/EFS) 라이브 검증에 가장 적합. 검증 후 즉시 삭제 가능.

### C. 저렴 / 프리티어 (필요 시)
| 타입 | 생성 | 비용 | 비고 |
|------|------|------|------|
| **EC2** | `run-instances` t4g.nano/t3.micro | 프리티어 or ~시간당 수원 | "진짜 모니터링 대상"을 갖는 의미도 있음 |
| **Route53** | `create-health-check` (감시할 엔드포인트 지정) | ~$0.50/월 | 글로벌. 공개 IP/도메인 하나 필요 |
| **RDS** | `create-db-instance` db.t3.micro | 프리티어(첫 12개월) | 생성 ~10분 |
| **CloudFront** | `create-distribution` (origin=기존 S3) | idle ~무료 | 글로벌, 배포 ~15분 |
| **WAF** | `create-web-acl --scope REGIONAL` | ~$5/월 + $1/rule | 월 과금 누적 주의 |

### D. 시간당 실비 — "잠깐 띄웠다 내리기"면 몇 센트
| 타입 | 최소 사양 | 대략 비용 |
|------|-----------|-----------|
| **ALB / NLB** | — | ~$0.0225/hr (~$16/월) |
| **CLB** | — | ~$0.025/hr (~$18/월) |
| **NAT** | — | ~$0.045/hr (~$32/월) + 데이터 |
| **ElastiCache** | cache.t3.micro | ~$0.017/hr (~$12/월) |
| **MQ** | mq.t3.micro | ~$0.03/hr (~$22/월) |
| **OpenSearch** | t3.small.search | ~$0.036/hr (~$26/월) + 스토리지 |
| **AuroraRDS** | Serverless v2 0.5 ACU / db.t3.medium | ~$0.06+/hr |

> 검증만 하고 바로 삭제하면 부담이 적다. 단 생성/삭제에 수 분 걸리는 타입이 많다.

### E. 제외 — 불가 / 비쌈 / 셋업 복잡
| 타입 | 이유 |
|------|------|
| **DX** (Direct Connect) | 물리 cross-connect(콜로) 필요 → **자가 생성 불가** |
| **DocDB** | db.t3.medium 클러스터, 월 $50+ |
| **MSK** | 프로비저닝 브로커 비쌈, 서버리스도 셋업 복잡 |
| **SageMaker** | 모델 배포 + 엔드포인트 인스턴스, 셋업 복잡 + 비쌈 |
| **VPN** | 시간당 과금 + Customer/VPN Gateway 셋업 필요(터널은 피어 없으면 DOWN) |
| **ACM** | 인증서는 무료지만 **도메인 검증(DNS/이메일) 필요** — 검증 안 되면 ISSUED가 안 돼 discovery에서 제외됨. *Route53 관리 도메인이 있으면 조건부 가능* |

---

## 타입별 테스트 주의사항

- **ACM** — full-collection: ISSUED 인증서 전부를 `monitoring=on`으로 수집하므로
  **토글이 무의미**(태그를 꺼도 collector가 다시 대상에 포함).
- **MQ** — 인벤토리는 **브로커 단위**로 1행, 알람은 인스턴스 단위(`{name}-1`/`-2`).
  상세페이지 알람 링크가 불완전할 수 있음(알려진 갭).
- **ECS** — 인벤토리는 **서비스 단위**. 클러스터만 만들면 안 뜨고, 실행 중인
  서비스(Fargate task 등)가 있어야 함.
- **Compound-dimension 타입**(ECS/WAF/SageMaker/APIGW) — `_cluster_name`/
  `_waf_rule`/`_variant_name`/`_api_type` 같은 내부 디멘션 힌트는 tags에만 있고
  인벤토리(`_sanitize_inventory_item`)엔 영속화되지 않아, **상세페이지 메트릭
  차트가 제한적**일 수 있음(후속 작업 대상).
- **글로벌 서비스**(CloudFront/Route53) — us-east-1 기준, 계정당 1회 discover.
  메트릭 리전도 us-east-1 고정(`_GLOBAL_SERVICE_REGION`).
- **NLB TG (TargetType=alb)** — `HealthyHostCount` 미발행, 알람 영구
  `INSUFFICIENT_DATA` (KI-001). TargetType=instance/ip는 정상.

---

## 신규 타입을 UI에 띄우는 절차

1. 위 표대로 실물 리소스를 생성한다(예: Backup vault).
2. 인벤토리 싱크를 트리거한다 — 둘 중 하나:
   - 스케줄 대기: daily monitor cron `cron(0 0 * * ? *)` = 09:00 KST
   - 즉시: daily monitor Lambda 수동 invoke
     (`aws lambda invoke --function-name aws-monitoring-engine-daily-monitor-dev ...`)
3. 인벤토리 테이블(`aws-monitoring-resource-inventory-dev`)에 `entity_type=resource`
   행이 생기고 UI 리스트/필터에 노출된다.
4. (토글 검증) 상세에서 모니터링 ON → RGT가 `Monitoring=on` 태그 부여 →
   다음 daily run에 해당 타입 알람 생성. 흔적 없이 끝내려면 ON 검증 후 OFF.
