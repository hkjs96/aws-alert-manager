# common/ — 핵심 하위 시스템 작동 방식

> 이 문서는 `common/` 모듈의 내부 작동 방식을 설명한다.
> AI 에이전트 또는 새 팀원이 이 코드베이스를 빠르게 이해하기 위한 참조 문서.

## 전체 흐름

```
[Daily Monitor Lambda]                    [Remediation Handler Lambda]
        │                                          │
        ▼                                          ▼
  Collector.collect_monitored_resources()    CloudTrail 이벤트 파싱
        │                                    (_API_MAP → resource_type + id)
        ▼                                          │
  alarm_manager.sync_alarms_for_resource()         ▼
        │                                   alarm_manager.create_alarms_for_resource()
        ▼                                          │
  ┌─────────────────────────────────────────────────┘
  │
  ▼
  alarm_registry._get_alarm_defs()     ← 하드코딩 알람 정의
  threshold_resolver.resolve()         ← 태그 → 환경변수 → 기본값
  alarm_naming._pretty_alarm_name()    ← 이름 생성 (255자 제한)
  dimension_builder._build_dimensions()← 디멘션 조립
  alarm_builder._create_standard_alarm()← CloudWatch PutMetricAlarm
  alarm_search._find_alarms_for_resource()← 기존 알람 검색
  sns_notifier.send_lifecycle_alert()  ← 생명주기 알림
```

## 모듈별 책임

### `__init__.py`
- `ResourceInfo` TypedDict 정의
- `MONITORED_API_EVENTS` — CloudTrail 이벤트 → 카테고리 매핑
- `SUPPORTED_RESOURCE_TYPES` — 지원 리소스 타입 목록
- `HARDCODED_DEFAULTS` — 메트릭별 기본 임계치

### `alarm_registry.py`
- `_EC2_ALARMS`, `_RDS_ALARMS`, `_ALB_ALARMS` 등 하드코딩 알람 정의
- `_get_alarm_defs(resource_type, resource_tags)` — 리소스 타입/태그 기반 알람 정의 반환
- 인스턴스 변형별 분기 (Aurora Serverless v2, Writer/Reader 등)

### `alarm_manager.py`
- `create_alarms_for_resource()` — 전체 삭제 후 재생성 (Remediation용)
- `sync_alarms_for_resource()` — 메타데이터 매칭 기반 개별 업데이트 (Daily Monitor용)
- 동적 알람 처리: `_parse_threshold_tags()` → `_resolve_metric_dimensions()`

### `alarm_builder.py`
- `_create_standard_alarm()` — CloudWatch PutMetricAlarm 호출
- `_create_single_alarm()` / `_recreate_standard_alarm()` — 단일/재생성 변형
- 글로벌 서비스(CloudFront, Route53)는 us-east-1 클라이언트 사용

### `alarm_search.py`
- `_find_alarms_for_resource()` — AlarmNamePrefix 기반 검색
- ALB/NLB/TG는 Short_ID + 레거시 Full_ARN 양쪽 검색

### `alarm_naming.py`
- `_pretty_alarm_name()` — `[{type}] {label} {metric} {dir} {threshold}{unit} (TagName: {id})`
- 255자 초과 시 label → display_metric 순으로 truncate
- `_shorten_elb_resource_id()` — ARN → Short_ID 변환

### `alarm_sync.py`
- 기존 알람과 새 정의를 비교하여 생성/업데이트/삭제 결정
- 메타데이터(Namespace, MetricName, Dimensions) 기반 매칭

### `dimension_builder.py`
- `_build_dimensions()` — 리소스 유형별 CloudWatch Dimensions 조립
- TG는 `TargetGroup` + `LoadBalancer` 복합 디멘션
- 글로벌 서비스는 Region 디멘션 추가 (CloudFront: `Region: Global`)

### `threshold_resolver.py` (= `tag_resolver.py`)
- 임계치 조회 우선순위: 태그 → 환경변수 → HARDCODED_DEFAULTS
- 단위 변환: GB→bytes (`multiplier` 필드)
- 퍼센트 기반 임계치 해석 (FreeMemoryPct 등)

### `sns_notifier.py`
- 생명주기 알림 (리소스 생성/삭제/태그 변경)
- 에러 알림 (처리 실패 시)

### `_clients.py`
- `@functools.lru_cache` 기반 boto3 클라이언트 싱글턴
- 리전별 클라이언트 팩토리 (`_get_cw_client_for_region()`)

## Collector 시스템 (`collectors/`)

모든 Collector는 `base.py`의 `CollectorProtocol`을 구현:

```python
class CollectorProtocol:
    def collect_monitored_resources() -> list[ResourceInfo]  # Monitoring=on 리소스 수집
    def get_metrics(resource_id, resource_tags) -> dict | None  # CW 메트릭 조회
    def resolve_alive_ids(tag_names) -> set[str]  # 알람 TagName → 실존 리소스 확인
```

현재 지원 Collector (28개):
EC2, RDS, ALB/NLB, TG, CLB, ElastiCache, NAT Gateway, Lambda, VPN,
Backup, OpenSearch, DocDB, ACM, API Gateway, MQ, MSK, DynamoDB,
ECS, EFS, S3, SageMaker, SNS, SQS, CloudFront, Route53, WAF, DX

### 내부 태그 컨벤션
- `_` prefix 태그는 Collector가 내부적으로 설정하는 메타데이터
- 예: `_lb_type`, `_lb_arn`, `_target_type`, `_resource_subtype`
- 알람 정의 분기, 디멘션 조립, 네임스페이스 결정에 사용

## 핵심 데이터 흐름 패턴

### 1. 태그 → 알람 생성
```
AWS 리소스 태그 (Monitoring=on, Threshold_CPU=90)
  → Collector.collect_monitored_resources()
  → alarm_registry._get_alarm_defs() + threshold_resolver
  → alarm_builder._create_standard_alarm()
  → CloudWatch PutMetricAlarm
```

### 2. CloudTrail → 실시간 반응
```
CloudTrail 이벤트 (RunInstances, CreateTags, TerminateInstances)
  → EventBridge Rule → Remediation Handler Lambda
  → _API_MAP에서 resource_type + id 추출
  → CREATE/TAG_CHANGE → create_alarms_for_resource()
  → DELETE → 알람 삭제 + lifecycle 알림
```

### 3. 고아 알람 정리 (Daily Monitor)
```
기존 알람의 TagName 집합
  → Collector.resolve_alive_ids()
  → 실존하지 않는 리소스의 알람 삭제
```
