# Backend (Python) — Claude Guide

`common/`, `daily_monitor/`, `remediation_handler/`, `tests/` 등 Python(`**/*.py`) 작업 시 적용되는 규칙.
루트의 [`../CLAUDE.md`](../CLAUDE.md)는 그대로 유효하고, 아래 백엔드 전용 규칙이 추가된다.

## 적용 규칙 (import)

- 알람 이름/디멘션/태그 규칙 (§6, §7, §8, §9, §12): @../.kiro/steering/alarm-rules.md
- Collector 인터페이스 & 새 리소스 추가 체크리스트 (§5, §11): @../.kiro/steering/resource-checklist.md

---

## 핵심 체크리스트

### 알람 이름 규칙 (§6)

- 포맷: `[{resource_type}] {label} {display_metric} {direction} {threshold}{unit} (TagName: {resource_id})`
- ALB/NLB/TG는 `resource_id`에 **Short_ID**(`{name}/{hash}`) 사용 — `_shorten_elb_resource_id()` 유틸리티 경유.
- `AlarmDescription`의 `resource_id` 필드에는 항상 **Full_ARN** 저장(매칭/역추적용).
- 알람 이름 255자 초과 시 label → display_metric 순으로 truncate(`...` 접미사).
- 알람 매칭은 메타데이터(Namespace/MetricName/Dimensions) 기반 — 이름 문자열 매칭 금지.
- 검색은 resource_id prefix 기반 — 전체 풀스캔 금지. ALB/NLB/TG는 Short_ID suffix + 레거시 Full_ARN suffix 양쪽 호환.

### 디멘션 규칙 (§6-1, §8-3)

새 메트릭 추가 시 **AWS 공식 문서에서 디멘션을 반드시 확인**한다.

- EC2/RDS는 단일 디멘션 (`InstanceId` / `DBInstanceIdentifier`).
- ALB LB 레벨 메트릭(`HTTPCode_ELB_5XX_Count` 등)은 `LoadBalancer` 단일 디멘션.
- TG 레벨 메트릭은 `TargetGroup` + `LoadBalancer` 복합 디멘션 필수.
- `RequestCountPerTarget`은 `TargetGroup` 디멘션 필수.
- **글로벌 서비스**: CloudFront(`DistributionId` + `Region: Global`), WAF(`WebACL` + `Rule` + `Region: {region}`), S3 Request Metrics(`BucketName` + `FilterId: EntireBucket`).
- Route53 / DX / MSK `ActiveControllerCount`는 `treat_missing_data = breaching`.
- 잘못된 디멘션은 `INSUFFICIENT_DATA` 원인.

### 글로벌 서비스 리전 (§8)

- CloudFront, Route53 메트릭은 **us-east-1에서만 발행**.
- `alarm_registry.py`의 `_GLOBAL_SERVICE_REGION` dict에 등록.
- `alarm_manager.py`의 `sync_alarms_for_resource`/`create_alarms_for_resource`에서 `_get_cw_client_for_region(region)` 사용.
- 크로스 리전 SNS 제약: AlarmActions는 같은 리전 SNS만 허용 → 현재 글로벌 알람은 AlarmActions 비움 (향후 Chatbot 개선 예정, `.kiro/specs/global-service-alarm-notification/`).

### Collector 인터페이스 (§5)

`common/collectors/base.py`의 `CollectorProtocol` 구현. 필수 메서드:

- `collect_monitored_resources() -> list[ResourceInfo]`
- `get_metrics(resource_id, resource_tags) -> dict[str, float] | None`
- `resolve_alive_ids(tag_names) -> set[str]`

메트릭 조회는 `base.query_metric()` 공통 유틸리티 경유.

### resolve_alive_ids 구현 (§5-1)

- 각 Collector가 자기 리소스 alive 체크를 직접 담당 — `daily_monitor/lambda_handler.py`에 하드코딩 금지.
- 역매핑 필요 타입: MQ(`{broker}-{1|2}`), APIGW(`{name}/{id}`), ACM(도메인명), ALB/NLB/TG(short ID).
- 역매핑 불필요 타입 (TagName == resource_id): EC2, RDS, CLB, ElastiCache, NAT, Lambda, VPN, Backup, OpenSearch, DocDB.
- `ClientError`만 catch, 기존 boto3 싱글턴 재사용.

### 새 리소스 추가 체크리스트 (§11)

새 리소스 타입 추가 시 모두 확인:

1. **메트릭/디멘션 확인** — AWS 공식 문서 기준 (§11-1)
2. **CloudTrail 이벤트 등록** — 3개 레이어 모두 (§11-2)
   - `common/__init__.py`의 `MONITORED_API_EVENTS`
   - `template.yaml`의 `CloudTrailModifyRule` EventPattern
   - `remediation_handler/lambda_handler.py`의 `_API_MAP`
3. **하드코딩 알람 정의** — `_*_ALARMS`, `HARDCODED_DEFAULTS`, `SUPPORTED_RESOURCE_TYPES` (§11-3)
4. **태그 기반 임계치 / 동적 알람** — `_NAMESPACE_SEARCH_MAP` 등록 (§11-4)
5. **단위 환산** — 필요한 경우 `multiplier` 필드 (예: GB→bytes `1073741824`) (§11-5)
6. **Collector 구현 + 등록** — `_COLLECTOR_MODULES`, `_RESOURCE_TYPE_TO_COLLECTOR` (alias 포함) (§11-6)
7. **SRE 골든 시그널** — Latency / Traffic / Errors / Saturation 각 1개 이상 검토 (§11-7)
8. **인스턴스 변형별 메트릭 가용성** — Serverless v2 FreeLocalStorage 미발행, Writer/Reader ReplicaLag 차이 등 (§11-8)
9. **퍼센트 기반 임계치** — 필요 시 `_INSTANCE_CLASS_MEMORY_MAP` + `_resolve_free_memory_threshold()` 패턴 (§11-9)
10. **E2E 인프라 cleanup** — Backup Vault, S3, ECR 등 내부 데이터 있는 리소스는 CustomResource Lambda 추가 (§11-10)
11. **Container Insights 의존 메트릭** — ECS `RunningTaskCount` 등 (§11-10 추가)

### CloudTrail ARN 변환 (§9)

`TagResource`/`UntagResource`는 `resourceArn` 반환 → `_extract_id_from_arn(arn, resource_type)`에서 변환:

- DynamoDB: `table/{name}` 마지막 `/` 이후
- ECS: `service/{cluster}/{name}` 마지막 `/` 이후
- EFS: `file-system/{id}` 마지막 `/` 이후
- SNS: `...:{name}` 마지막 `:` 이후
- MSK: `cluster/{name}/{uuid}` 두 번째 `/` 부분
- Lambda/ACM/S3/SageMaker 등: ARN 그대로

새 리소스 추가 시 ARN 패턴 확인 후 `_resolve_multi_tag_type()`의 `_ARN_SERVICE_MAP`에도 등록.

### 태그 제약 (§7)

- 태그 키 128자 (`Threshold_` 10자 제외 시 메트릭 이름 최대 118자)
- 태그 값 256자, 양의 숫자 파싱 가능
- 리소스당 태그 최대 50개
- 허용 문자: 문자/숫자/공백/`_ . : / = + - @`
- `aws:` 접두사 태그는 무시
- 임계치 우선순위: **태그 → 환경 변수(`DEFAULT_{METRIC}_THRESHOLD`) → `HARDCODED_DEFAULTS`**

---

## 테스트 규칙

- 단위 테스트: `moto` 사용 (AWS 서비스 모킹)
- 통합: `unittest.mock`
- Property-Based Test: `hypothesis`
- 파일 네이밍: `tests/test_{module_name}.py`, PBT는 `tests/test_pbt_{property_name}.py`
- 모든 public 함수 최소 1개 케이스 필수
- **TDD Red → Green → Refactor** 사이클 준수
