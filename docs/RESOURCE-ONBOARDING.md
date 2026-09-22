# Resource Onboarding Checklist

백엔드가 지원하는 AWS 리소스 타입을 추가·수정할 때 반드시 따르는 체크리스트다.
**이 파일이 SSOT다.** (구 `.kiro/steering/resource-checklist.md` 전문 병합본 →
구 `.claude/commands/new-collector.md`에서 이전)

- 트리거 스킬: `.claude/skills/new-collector/SKILL.md`
- 알람 네이밍·디멘션·Severity 계약: `docs/ALARM-RULES.md`
- 안티패턴 전체 목록: 루트 `AGENTS.md` §5

## Collector 인터페이스 (§5) — 범용 수집기 위에 쓴다 (docs/specs/resource-type-registry P3)

모든 수집기 모듈은 `common/collectors/generic.py`의 `GenericCollector`를 스펙에 묶어 `CollectorProtocol`
(`collect_monitored_resources`·`get_metrics`·`resolve_alive_ids`)을 얻는다. 모듈에 **직접 쓰는 것은 셋**뿐이다:

```python
from common.collectors.generic import GenericCollector
from common.resource_types.<type> import SPEC

@functools.lru_cache(maxsize=None)
def _get_<svc>_client(): ...                    # 이름 규칙 `_get*client` — daily_monitor가 계정 전환 시 비운다, 테스트가 패치한다

def _enumerate() -> list[tuple[str, dict]]: ...  # 태그 캐시가 없을 때의 describe 나열: (TagName, tags). 옛 코드 그대로.
def _alive(tag_names: set[str]) -> set[str]: ... # 알람 TagName 중 실제 존재하는 것 — **describe 고정**(RGT는 태그 벗겨진 리소스를 고아로 오판)

COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
```

- **나열**: 스펙에 `identity`(ARN → TagName, 순수 함수 — `arn_tail(":")`/`arn_tail("/")` 또는 짧은 람다)가 있고 `rgt_prime=True`면
  범용이 활성 태그 캐시(RGT `GetResources`)에서 Monitoring=on 리소스를 읽는다 — 서비스 콜 0. 캐시가 없으면(IAM 미부여·
  `TAG_CACHE=off`·프라임 실패) `_enumerate`. Monitoring=on 필터는 범용이 건다(후속 describe를 아끼려면 미리 걸어도 된다).
- **identity를 줄 수 없는 경우**(이유를 스펙 `notes`에 "identity 없음: …"으로 — 테스트가 강제): 태그 없는 리소스도 모아야 함(ACM),
  상태·엔진 필터에 describe가 필요(DX·ElastiCache·RDS 계열), TagName이 ARN에 없음(APIGW REST), 서버 측 태그 필터가 있음(EC2 계열),
  **글로벌 서비스**(S3·CloudFront·Route53 — RGT는 리전 API라 실행 리전 캐시로 나열하면 0개/누락 오판).
  한 리소스가 TagName 여럿이 되거나 내부 태그를 붙여야 하면 `identities=(arn, tags) -> [(TagName, tags)]`를 모듈에서 준다
  (MQ `{broker}-{1|2}`, OpenSearch `_client_id`, SageMaker `_variant_name`, CLB/WAF의 공유 필터 ARN 판별) — `notes`에 "_identities".
- **메트릭**: 기본은 스펙의 알람 정의에서 생성된다(namespace·metric_name·stat, 디멘션은 알람과 같은 `dimension_builder._build_dimensions`).
  타입 고유 `get_metrics`를 새로 쓰지 않는다. 정의로 표현이 안 되는 것(CWAgent 디스크 경로 발견, 추가 인자, 다른 리전 클라이언트)만
  `metrics=_metrics` 오버라이드 — `notes`에 "오버라이드" 이유. 수집 결과 키는 정의의 `metric_key`(없으면 `metric`)여야 한다.
  **단위 변환은 오버라이드 사유가 아니다** — 정의에 `transform_threshold`(표시→CW)와 `transform_value`(CW→표시)를 짝으로 둔다(register가
  강제). 한 모듈이 타입 여럿을 내면 daily_monitor가 `get_metrics(id, tags, resource_type=)`로 스펙을 고른다 — 모듈에 타입별 함수를 두지 않는다.
- 한 모듈이 타입 여럿을 내면(rds → RDS·AuroraRDS, elb → ALB·NLB·TG) `_enumerate`가 `(TagName, tags, type)` 3튜플을 준다.
- 게이트: `tests/test_generic_collector.py`에 (a) RGT 경로 == describe 경로 ResourceInfo 동일, (b) 범용 `get_metrics` 쿼리가 기대 셋과 같음
  (오라클 `tests/fixtures/collector_metrics_snapshot_2026-09.json` 방식)을 추가하고, `test_rgt_enumeration_roster`에 타입을 넣는다.

### resolve_alive_ids 구현 규칙 (§5-1)

- 각 Collector가 자기 리소스의 alive 체크를 직접 담당한다. `daily_monitor/lambda_handler.py`에
  alive 체크 로직을 하드코딩하지 않는다 (AGENTS.md AP-8).
- 입력: 알람 TagName 집합 (알람 이름의 `(TagName: ...)` 부분에서 추출된 값).
  출력: 실제 AWS 리소스가 존재하는 TagName 부분집합.
- TagName은 `_shorten_elb_resource_id()`가 생성한 short ID 형식이므로, collector가 원본
  리소스 식별자로 **역매핑**해야 한다:
  - MQ: `{broker_name}-{1|2}` → suffix 제거 후 broker name으로 조회
  - APIGW HTTP/WS: `{api_name}/{api_id}` → split 후 api_id로 조회
  - ACM: 도메인명 → `list_certificates` + `describe_certificate`로 도메인 매칭
  - ALB/NLB/TG: short ID (`{name}/{hash}`) → ARN이 아닌 경우 보수적으로 alive 처리
  - 역매핑 불필요 (TagName == resource_id): EC2, RDS, CLB, ElastiCache, NAT, Lambda, VPN,
    Backup, OpenSearch, DocDB
- 에러 처리: `ClientError`만 catch, 기존 collector의 boto3 클라이언트 싱글턴 재사용.

## Required Updates

1. **메트릭/디멘션 확인 (AWS 공식 문서 필수):** 메트릭 목록·네임스페이스·디멘션을 확인한다.
   LB 레벨 vs TG 레벨 등 디멘션 계층 구분 필수 (`docs/ALARM-RULES.md` §6-1).
   CWAgent 등 커스텀 에이전트 네임스페이스는 별도 확인.
2. **CloudTrail 이벤트 (생명주기):** CREATE/MODIFY/DELETE/TAG_CHANGE API를 확인하고 **스펙에 적는다**
   (docs/specs/resource-type-registry P2):
   - `backend/common/resource_types/__init__.py` — 해당 `ResourceTypeSpec`의 `lifecycle=(Lifecycle("EventName", KIND), …)`.
     `MONITORED_API_EVENTS`와 `_API_MAP`의 타입은 여기서 **파생**되니 손대지 않는다.
   - `backend/remediation_handler/lambda_handler.py::_EXTRACTORS` — 이벤트 → ID 추출기 한 줄. 스펙과 어긋나면
     **import 시 RuntimeError**(조용한 누락 금지).
   - `infrastructure/backend/template.yaml` CloudTrail EventPattern `detail.eventName` — 파생 불가(CFN). 대신
     `test_resource_type_registry.py`의 템플릿 정합 테스트가 레지스트리와 같은지 고정한다.
   - CREATE 이벤트는 `responseElements`에서 ID를 추출하는 경우가 많으므로 주의.
   - ARN → 리소스 ID 변환: 수집기 쪽은 스펙 `identity`(위 §5), remediation 쪽은 `_EXTRACTORS` — 둘이 같은 TagName을 내야 한다.
     `docs/ALARM-RULES.md` §9-1 표를 갱신.
   - 여러 서비스가 같은 이벤트 이름을 쓰면(`TagResource`) 스펙이 아니라 `SHARED_LIFECYCLE`(MULTI)에.
3. **필수 알람 자동 생성 (Monitoring=on):**
   - 알람 정의 `_*_ALARMS`는 **스펙 파일**(`backend/common/resource_types/<type>.py`)에 두고 스펙의 `alarm_defs=`로 가리킨다
     (리스트, 태그 조건부면 `Callable[[tags], list]` + `variants`). `alarm_registry._ALARM_DEFS_BY_TYPE`는 파생 — 손대지 않는다.
   - `_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`_DIMENSION_KEY_MAP`은 **손대지 않는다** — 정의에서 파생된다
     (docs/specs/resource-type-registry P1). 대신:
     - 조건부 함수가 `resource_tags.get(...)`으로 **새 태그를 읽으면** `_ALARM_DEF_VARIANTS`에 그 조합을 추가한다
       (완전성 테스트가 함수 소스를 훑어 누락을 잡는다)
     - 태그가 있어야 붙는 알람은 정의에 `"opt_in": True` — 기본 메트릭 키 집합에서 빠진다
     - 빌드 시 해석기가 바꿔 끼우는 네임스페이스만 `_EXTRA_NAMESPACES`(현재 TG의 NLB)
   - 표시명(알람 이름의 지표명·방향·단위)과 기본 임계치는 **스펙의 `display`/`defaults`**에 — 정의한 메트릭 키마다
     둘 다 있어야 하고, 빠지면 import 시 실패한다. 다른 타입도 쓰는 키(CPUUtilization 등)는 같은 값으로 선언한다(다르면 실패).
     `_METRIC_DISPLAY`·`HARDCODED_DEFAULTS`·`_metric_name_to_key`는 파생 — 손대지 않는다.
   - 옛 태그 키 호환처럼 타입에 속하지 않는 항목만 `common/resource_types/legacy.py`에 `add_shared_thresholds(reason=…)`.
   - `SUPPORTED_RESOURCE_TYPES`는 `__init__`의 import 순서에서 파생 — 스펙 모듈을 만들고 `__init__`에 한 줄.
4. **태그 기반 임계치:** `Threshold_{MetricName}` 태그 suffix가 알람 정의 `metric_key`와 매칭돼야
   한다. 동적 알람용 탐색 네임스페이스를 `_NAMESPACE_SEARCH_MAP`에 등록.
   우선순위: 태그 → 환경 변수(`DEFAULT_{METRIC}_THRESHOLD`) → `HARDCODED_DEFAULTS`.
5. **단위 환산 검토:** bytes 메트릭(FreeableMemory 등)은 GB 단위 `metric_key` + `multiplier`
   (GB→bytes: 1073741824)로 환산하고, 알람 이름의 `display_metric`/`unit`도 환산 단위로 표시.
6. **스펙 + Collector 모듈:**
   - **스펙 파일** `backend/common/resource_types/<type>.py`: 알람 정의 `_X_ALARMS`(또는 태그 조건부 함수 + `variants`) 뒤에
     `SPEC = register(ResourceTypeSpec(type=…, label=…, collector="<모듈 이름>", rgt_filters=(…), rgt_prime=True,
     identity=arn_tail("/"), lifecycle=(…), alarm_defs=…, display={…}, defaults={…}, notes=…))`. `__init__.py`에 import 한 줄
     (순서 = `SUPPORTED_RESOURCE_TYPES` 순서). `daily_monitor`의 두 맵·`tag_cache.TAGGED_SERVICES`·`MONITORED_API_EVENTS`·
     `_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`_DIMENSION_KEY_MAP`·`_METRIC_DISPLAY`·`HARDCODED_DEFAULTS`는 전부 파생 — 손대지 않는다.
   - `rgt_filters`는 실계정에서 유효한 `ResourceTypeFilters` 문자열(design.md 부록 A). `identity ⇒ rgt_prime`(register가 강제).
   - 파생 규칙에서 벗어나는 것(`rgt_prime=False`·`lifecycle=()`·identity 없음·메트릭 오버라이드)은 `notes`에 이유 — 테스트가 강제.
   - **수집기 모듈** `backend/common/collectors/<모듈>.py`: 위 §5의 셋(`_get*client`·`_enumerate`·`_alive`)과 `GenericCollector` 묶기.
     `_enumerate`의 태그 조회 래퍼는 `common.tag_cache.cached_tags(arn)`를 먼저 보고 `None`일 때만 리소스별 API를 부른다.
   - TagName ≠ resource_id인 타입은 `_alive` 역매핑 필수 (§5-1); 옛 `resolve_alive_ids` 역매핑 규칙 그대로.
   - **복합 디멘션**은 파생되지 않는다 — 타입이 복합 디멘션(ECS·WAF·S3·SageMaker 계열)을 쓰면
     `backend/common/dimension_builder.py`에 손으로 쓴 분기가 여전히 필요하다. 그 외 타입은 스펙만으로 끝난다.
7. **테스트:** `backend/tests/` 하위에 추가.
8. **프론트엔드 노출 시:**
   - `frontend/lib/constants.ts`, `frontend/types`
   - `docs/API-CONTRACT.md`, `docs/DATA-MODEL.md`, `docs/API-WORKFLOWS.md`

## 설계 검토 항목

### SRE 골든 시그널 기반 메트릭 선정 (§11-7, 필수)

시그널별 최소 1개 이상의 하드코딩 메트릭이 있는지 확인하고 판단 근거를 기록한다:

| 시그널 | 하드코딩 기준 | 동적 알람 후보 |
|--------|-------------|---------------|
| Latency | 사용자 체감 직결 (예: TargetResponseTime) | 워크로드별 차이가 큰 메트릭 |
| Traffic | 과부하 감지용 (예: RequestCount) | 급증/급감 감지 세부 메트릭 |
| Errors | 가용성 직결 (예: 5XX, StatusCheckFailed) | 앱 레벨 에러 (Deadlocks 등) |
| Saturation | CPU, 메모리, 스토리지, 연결 수 | I/O 병목 (DiskQueueDepth) 등 |

- 비교 방향 명시: "높을수록 위험" `GreaterThanThreshold` / "낮을수록 위험" `LessThanThreshold`
  (동적 알람은 `Threshold_LT_` prefix 안내).

### 인스턴스 변형별 메트릭 가용성 (§11-8)

- 클래스별 차이 (예: Aurora Serverless v2는 `FreeLocalStorage` 미발행 — KI-006)
- 역할별 차이 (예: Aurora Writer만 `AuroraReplicaLagMaximum` — KI-007)
- 확인된 차이는 `_get_alarm_defs()`에서 `resource_tags` 기반 조건부 분기로 처리하고
  E2E 테스트로 검증한다.

### 퍼센트 기반 임계치 (§11-9)

절대값 메트릭(FreeableMemory 등)이 인스턴스 사양에 따라 의미가 달라지면:
1. Collector에서 `_total_{resource}_bytes` 내부 태그 설정
2. `_INSTANCE_CLASS_MEMORY_MAP` 등 lookup 테이블에 클래스 추가
3. `_resolve_free_memory_threshold()` 패턴으로 퍼센트 해석 로직 구현
- Serverless/Auto-scaling은 퍼센트 부적합할 수 있음 (ACUUtilization 등 대체 메트릭 사용).

### Container Insights 의존 메트릭 (ECS/EKS)

`RunningTaskCount`/`NetworkRx/TxBytes`는 `ECS/ContainerInsights` 네임스페이스 전용 —
Container Insights 미활성 시 영구 INSUFFICIENT_DATA. 현재 ECS 하드코딩 알람은 `AWS/ECS`의
CPU/Memory만 포함하며, RunningTaskCount는 동적 알람 태그로 사용 가능.

### E2E 테스트 인프라 정리 (§11-10)

스택 삭제 시 내부 데이터가 남으면 `DELETE_FAILED`: Backup Vault(recovery point),
S3(객체), ECR(이미지)는 cleanup CustomResource를 추가하고, Delete 핸들러는 에러 시에도
`SUCCESS`를 반환해 스택 삭제를 블로킹하지 않는다. OpenSearch는 삭제에 10~15분 소요.

## IAM 체크 (필수 — 단위 테스트가 잡지 못하는 유일한 계층)

새 AWS API 호출이나 새 DynamoDB 테이블/연산을 추가하면 **같은 커밋에서** 권한을 확인한다.
2026-08-31 라이브 검증에서 세 번 연속 IAM 누락이 배포 후에야 드러났다
(온보딩 롤 `GetMetricStatistics`, 워커 롤 run history `Query`, `GetMetricData`).

- 워커/핸들러 롤: `infrastructure/backend/template.yaml`의 해당 Role Policies에 액션 추가
  (DynamoDB는 테이블 ARN + `/index/*` 둘 다, CloudWatch 읽기는 `Resource: "*"`)
- 크로스어카운트 호출이면 **온보딩 템플릿 3곳 동기화**: `infrastructure/customer-onboarding/template.yaml`
  → `frontend/public/customer-onboarding.yaml`(복사) → 공개 S3 버킷 재업로드(`text/yaml`)
- 배포 후 첫 run 로그에서 `AccessDenied`를 grep 한다 — 코드는 대부분 권한 오류를 삼키고 폴백하므로
  기능이 "조용히 동작 안 함"으로 나타난다

## Verification

```bash
cd backend && pytest tests/ -x -q --tb=short
```

Do not expose a new resource type in frontend filters or settings until the
frontend API contract, DTO mapping, and tests are complete for that type.
