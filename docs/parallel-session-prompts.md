# 병렬 작업 세션 프롬프트

## 실행 순서

```
세션 1 (기반 + Collector 전반부)  ──────────────────────────────►
세션 2 (Collector 후반부 NEW 파일) ─────────►                     
                                            세션 3 (통합 + 인프라)
```

- 세션 1 + 세션 2: 동시 실행 가능
- 세션 3: 세션 1 완료 후 시작 (공유 파일 의존)

---

## 세션 1: 기반 + Collector 전반부 (Lambda, VPN, APIGW, ACM)

> 이미 돌리고 있는 세션에서 계속 진행. tasks.md의 Task 1~5를 순서대로 수행.

기존 spec 기반으로 진행 중이므로 별도 프롬프트 불필요.

---

## 세션 2: Collector 후반부 NEW 파일만 (Backup, MQ, CLB, OpenSearch)

> 새 채팅에서 아래 프롬프트를 붙여넣기

```
아래 4개 Collector 모듈 파일을 새로 생성해줘. 기존 패턴(natgw.py, elasticache.py, docdb.py)을 정확히 따라야 해.

## 공통 규칙
- `functools.lru_cache(maxsize=None)` 기반 boto3 클라이언트 싱글턴
- `from common import ResourceInfo`
- `from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES, CW_STAT_AVG, CW_STAT_SUM`
- `logger = logging.getLogger(__name__)`
- `collect_monitored_resources() -> list[ResourceInfo]`: Monitoring=on 태그 필터링
- `get_metrics(resource_id, resource_tags=None) -> dict[str, float] | None`: CW 메트릭 조회
- `_collect_metric()` 헬퍼로 개별 메트릭 조회 + skip 로그
- `_get_tags()` 헬퍼로 태그 조회 (ClientError 시 빈 dict + error 로그)
- `region = boto3.session.Session().region_name or "us-east-1"`
- 에러 처리: `botocore.exceptions.ClientError`만 catch
- 로그: `logger.error("메시지: %s", e)` 포맷 (f-string 금지)

## 1. `common/collectors/backup.py`
- 클라이언트: `boto3.client("backup")`
- `collect_monitored_resources()`:
  - `list_backup_vaults()` paginator
  - `list_tags(ResourceArn=vault_arn)` 으로 태그 조회
  - `Monitoring=on` 필터
  - `ResourceInfo(type="Backup", id=vault_name)`
- `get_metrics(vault_name, resource_tags=None)`:
  - namespace: `AWS/Backup`, dimension: `BackupVaultName`
  - `NumberOfBackupJobsFailed` (Sum) → `"BackupJobsFailed"`
  - `NumberOfBackupJobsAborted` (Sum) → `"BackupJobsAborted"`

## 2. `common/collectors/mq.py`
- 클라이언트: `boto3.client("mq")`
- `collect_monitored_resources()`:
  - `list_brokers()` paginator
  - `describe_broker(BrokerId=broker_id)` 로 태그 조회 (Tags 필드)
  - `Monitoring=on` 필터
  - `ResourceInfo(type="MQ", id=broker_name)`
- `get_metrics(broker_name, resource_tags=None)`:
  - namespace: `AWS/AmazonMQ`, dimension: `Broker`
  - `CpuUtilization` (Average) → `"MqCPU"`
  - `HeapUsage` (Average) → `"HeapUsage"`
  - `JobSchedulerStorePercentUsage` (Average) → `"JobSchedulerStoreUsage"`
  - `StorePercentUsage` (Average) → `"StoreUsage"`

## 3. `common/collectors/clb.py`
- 클라이언트: `boto3.client("elb")` (Classic ELB, elbv2 아님!)
- `collect_monitored_resources()`:
  - `describe_load_balancers()` paginator
  - `describe_tags(LoadBalancerNames=[name])` 으로 태그 조회
  - `Monitoring=on` 필터
  - `ResourceInfo(type="CLB", id=lb_name)`
- `get_metrics(lb_name, resource_tags=None)`:
  - namespace: `AWS/ELB`, dimension: `LoadBalancerName`
  - `UnHealthyHostCount` (Average) → `"CLBUnHealthyHost"`
  - `HTTPCode_ELB_5XX` (Sum) → `"CLB5XX"`
  - `HTTPCode_ELB_4XX` (Sum) → `"CLB4XX"`
  - `HTTPCode_Backend_5XX` (Sum) → `"CLBBackend5XX"`
  - `HTTPCode_Backend_4XX` (Sum) → `"CLBBackend4XX"`
  - `SurgeQueueLength` (Maximum) → `"SurgeQueueLength"`
  - `SpilloverCount` (Sum) → `"SpilloverCount"`

## 4. `common/collectors/opensearch.py`
- 클라이언트: `boto3.client("opensearch")`, `boto3.client("sts")`
- `collect_monitored_resources()`:
  - `list_domain_names()` → `describe_domains(DomainNames=[...])`
  - `list_tags(ARN=domain_arn)` 으로 태그 조회
  - `Monitoring=on` 필터
  - `_client_id` Internal_Tag: STS `get_caller_identity()["Account"]` 또는 ARN에서 account_id 파싱
  - `ResourceInfo(type="OpenSearch", id=domain_name, tags={..., "_client_id": account_id})`
- `get_metrics(domain_name, resource_tags=None)`:
  - namespace: `AWS/ES`
  - Compound Dimension: `DomainName` + `ClientId` (resource_tags["_client_id"])
  - `ClusterStatus.red` (Maximum) → `"ClusterStatusRed"`
  - `ClusterStatus.yellow` (Maximum) → `"ClusterStatusYellow"`
  - `FreeStorageSpace` (Minimum) → `"OSFreeStorageSpace"`
  - `ClusterIndexWritesBlocked` (Maximum) → `"ClusterIndexWritesBlocked"`
  - `CPUUtilization` (Average) → `"OsCPU"` (직접 키 반환, _metric_name_to_key 미사용)
  - `JVMMemoryPressure` (Maximum) → `"JVMMemoryPressure"`
  - `MasterCPUUtilization` (Average) → `"MasterCPU"`
  - `MasterJVMMemoryPressure` (Maximum) → `"MasterJVMMemoryPressure"`

## 참고: 기존 패턴 예시 (natgw.py 구조)
```python
import functools
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from common import ResourceInfo
from common.collectors.base import query_metric, CW_LOOKBACK_MINUTES, CW_STAT_SUM

logger = logging.getLogger(__name__)

@functools.lru_cache(maxsize=None)
def _get_ec2_client():
    return boto3.client("ec2")

def collect_monitored_resources() -> list[ResourceInfo]:
    # ... paginator + tag filter + ResourceInfo 반환

def get_metrics(resource_id, resource_tags=None) -> dict[str, float] | None:
    # ... dimension 구성 + _collect_metric 호출 + metrics or None 반환

def _collect_metric(namespace, cw_metric_name, dimensions,
                    start_time, end_time, result_key, metrics_dict):
    value = query_metric(namespace, cw_metric_name, dimensions,
                         start_time, end_time, CW_STAT_SUM)
    if value is not None:
        metrics_dict[result_key] = value
    else:
        logger.info("Skipping %s metric for ...: no data", result_key, ...)
```

테스트는 작성하지 마. 파일 4개만 생성해줘.
```

---

## 세션 3: 통합 + 인프라 (세션 1 완료 후 실행)

> 새 채팅에서 아래 프롬프트를 붙여넣기

```
remaining-resource-monitoring spec의 Task 6~17을 수행해줘.
세션 1에서 Task 1~5 (Alarm Registry, Constants, 8개 Collector)가 완료된 상태야.

남은 작업 요약:

### Task 6: Remediation Handler 확장
`remediation_handler/lambda_handler.py`의 `_API_MAP`에 8개 신규 리소스 이벤트 매핑 추가.
각 리소스별 `_extract_*_ids()` 함수 구현.
TagResource/UntagResource는 "MULTI" 타입 + ARN 기반 서비스 판별.

### Task 7: Tag Resolver 확장
`common/tag_resolver.py`의 `get_resource_tags()`에 8개 신규 타입 분기 추가.
- Lambda: `lambda` 클라이언트 `list_tags(Resource=arn)`
- VPN: `ec2` 클라이언트 `describe_vpn_connections` → Tags
- APIGW: `_api_type`에 따라 `apigateway`/`apigatewayv2` 태그 조회
- ACM: `acm` 클라이언트 `list_tags_for_certificate`
- Backup: `backup` 클라이언트 `list_tags`
- MQ: `mq` 클라이언트 `describe_broker` → Tags
- CLB: `elb` 클라이언트 `describe_tags`
- OpenSearch: `opensearch` 클라이언트 `list_tags`

### Task 9: Daily Monitor 통합
`daily_monitor/lambda_handler.py`에:
- 8개 import 추가 (lambda_fn, vpn, apigw, acm, backup, mq, clb, opensearch)
- `_COLLECTOR_MODULES`에 8개 모듈 추가
- `alive_checkers`에 8개 타입별 `_find_alive_*` 함수 등록 + 구현
- `_process_resource()` "낮을수록 위험" 메트릭 세트에 `TunnelState`, `DaysToExpiry`, `OSFreeStorageSpace` 추가

### Task 11: template.yaml IAM + EventBridge 확장
- Daily Monitor Role: 8개 신규 리소스 Describe/List/Tags API 권한 추가
- Remediation Handler Role: 8개 신규 리소스 생명주기 API 권한 추가
- CloudTrailModifyRule EventPattern: 신규 source + eventName 추가

### Task 13: Alarm Manager 확장
- `common/alarm_builder.py`: `treat_missing_data` 지원 (VPN breaching)
- `common/dimension_builder.py`: OpenSearch Compound Dimension (DomainName + ClientId)

### Task 14: Alarm Search 확장
- `common/alarm_search.py`: `_find_alarms_for_resource()` 기본 폴백 목록에 8개 신규 타입 추가

### Task 16: PBT 10개 Property
- `tests/test_pbt_remaining_resource_alarm_defs.py` 파일에 10개 PBT 작성
- Property 1~10은 design.md의 Correctness Properties 참조

TDD 사이클(Red→Green→Refactor)을 따르되, 이미 구현된 코드(Task 1~5)에 대한 테스트는 Green부터 시작해도 됨.
각 Task 완료 후 `pytest` 실행하여 회귀 없음 확인.

참고 파일:
- `.kiro/specs/remaining-resource-monitoring/tasks.md` (전체 태스크 목록)
- `.kiro/specs/remaining-resource-monitoring/design.md` (설계 상세)
- `.kiro/specs/remaining-resource-monitoring/requirements.md` (요구사항)
```

---

## 머지 순서

1. 세션 1 완료 → git commit
2. 세션 2 결과물 (4개 NEW 파일) → 세션 1 브랜치에 복사 (충돌 없음, 전부 새 파일)
3. 세션 3 완료 → git commit
4. 전체 `pytest` 실행하여 통합 검증
