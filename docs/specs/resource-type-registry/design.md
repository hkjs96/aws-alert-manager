# 리소스 타입 레지스트리 — 설계 (2026-09-15)

> 질문: "메트릭을 걸어야 하는 리소스들을 하나하나 코딩으로 만들었는데, 이 방식이 앞으로도 괜찮은가?"
> 답: **정의를 손으로 쓴 것은 옳았고 계속 그래야 한다. 문제는 정의가 아니라 한 타입이 코드 15곳에
> 흩어져 있는 것이다.** 고칠 방향은 코드 생성도 YAML도 아니고, **타입 하나 = 스펙 객체 하나**로 모은 뒤
> 나머지를 거기서 파생시키는 것이다. 이미 이 저장소가 알림 채널에서 같은 수법을 썼다
> (`notification_adapters.py` — 어댑터 하나 등록하면 검증·응답 가림·카탈로그·계약 테스트가 따라온다).

## 1. 지금 모양 — 실측 (2026-09-14)

| 항목 | 값 |
|---|---|
| 리소스 타입 | 29 (`SUPPORTED_RESOURCE_TYPES`) |
| 알람 정의 | 31개 `_*_ALARMS` 리스트, **110개** |
| 정의의 필드 | 공통 9개(`metric` `namespace` `metric_name` `dimension_key` `stat` `comparison` `period` `evaluation_periods` + `treat_missing_data` 52건) · 옵션 5개(`needs_client_id` 8, `transform_threshold` 5, `region` 5, `needs_storage_type` 2, `dynamic_dimensions` 1) |
| 수집기 | 26개 파일 **4,927줄**(평균 190, `base.py` 319) |
| `alarm_registry.py` | 1,902줄 |
| `resource_type == "…"` 분기 | **111곳 / 10개 파일** |
| 타입 하나 추가 시 편집 지점 | **약 15곳 / 12개 파일** (`/new-collector` 체크리스트) — CloudTrail 이벤트만 3곳 동기화 |
| 최근 3개월 커밋(수집기·레지스트리) | 12건 — **새 타입 추가 0건**, 전부 횡단 수정·성능 |

### 1-1. 파생 가능한 것을 손으로 세 번 적는다

병행 맵 셋을 알람 정의에서 계산한 값과 대조했다(`_get_alarm_defs_raw(type, {})` 기준):

| 맵 | 일치 | 불일치와 이유 |
|---|---|---|
| `_DIMENSION_KEY_MAP` | 29/29 | — |
| `_NAMESPACE_MAP` | 28/29 | TG: `AWS/NetworkELB` — NLB 대상그룹 변형이 조건 분기(`_resolve_tg_namespace`)에만 있음 |
| `_HARDCODED_METRIC_KEYS` | 27/29 | AuroraRDS: `ACUUtilization`·`ReplicaLag`·`ServerlessDatabaseCapacity` / APIGW: `Api4xx`·`Api5xx`·`Ws*` — **태그 조건부 정의**(`_get_aurora_alarm_defs`, `_get_apigw_alarm_defs`)에만 나오는 키 |

즉 셋 다 "정의의 모든 변형을 열거하면" 나온다. 지금은 `test_pbt_registry_completeness.py`가 어긋남을 잡아
드리프트는 없다 — **그 테스트가 필요하다는 사실이 두 번 적고 있다는 증거**다. `_metric_name_to_key`는
`_METRIC_DISPLAY`의 역인덱스(`_METRIC_NAME_TO_KEY`)라 이미 파생이다. `_METRIC_DISPLAY`(표시명·방향·단위)는
사람이 정하는 도메인 데이터라 파생이 아니고, 스펙 안으로 들어가야 할 것이다.

`HARDCODED_DEFAULTS`는 117개인데 정의의 메트릭은 94개 — 여분 23개는 ① 옛 키(`CPU` `Memory` `Disk` `Connections`
`ELB5XX` `TCP*Reset` `TGResponseTime` `Free*GB` — 메트릭 키 개명 전 태그 호환) ② 퍼센트 변형(`FreeMemoryPct` 등)
③ 동적 알람 전용(`Api4xx` `Ws*`) ④ 변형 전용(`ACUUtilization` 등) ⑤ 옵트인(`StatusCheckFailed_Application`)이다.
전부 이유가 있지만 **맵은 그 이유를 말해 주지 않는다** — 스펙에 붙으면 각 항목이 왜 있는지가 자리로 드러난다.

### 1-2. 수집기 26개는 같은 뼈대의 복제다

26개 전부 `나열 → 태그 → Monitoring=on 필터 → ResourceInfo`. 타입 고유한 부분은 셋뿐이다 —
① 어떤 API로 나열하나 ② ARN/ID에서 CloudWatch 디멘션 값을 어떻게 뽑나 ③ 메트릭 3~5개 목록.
`sqs.py` 128줄에서 이 셋은 20줄이 안 된다.

대가는 **횡단 변경이 중간에 멈추는 것**이다. 6월의 RGT 태그 캐시(N+1 제거, `706b315`)는 26개 중 **15개**에만
붙어 있다(`acm` `apigw` `clb` `ec2` `efs` `mq` `msk` `natgw` `route53` `sqs` `vpn`은 없음). 일부는 정당하다 —
`natgw`는 `describe_nat_gateways(Filter=tag:Monitoring=on)`로 **서버 측 필터**를 쓰고 있어 N+1이 애초에 없다.
그런데 그 더 나은 수법을 다른 25개가 공유할 방법이 없었다는 것이 정확히 문제다. GetMetricData 배치(`4b95f1c`),
디스크 차원 메모(`4948555`), 등급 정책(`0ac4080`)도 전부 "26번 방문" 류였다.

### 1-3. 나열 인프라는 이미 있는데 캐시로만 쓴다

`tag_cache.py`가 Resource Groups Tagging `GetResources`를 이미 부른다(`TAGGED_SERVICES` 20개 서비스,
100건/콜). 이 API는 "태그가 있는 리소스 전부"를 돌려주므로 `TagFilters=[Monitoring=on]`을 걸면 **감시 대상
목록 그 자체**가 나온다. IAM `tag:GetResources`는 온보딩 역할(`customer-onboarding/template.yaml:90`)과
백엔드 역할 둘 다에 이미 있다. 지금은 태그 조회 캐시로만 쓰고, 나열은 서비스별 `describe_*`를 26번 한다.

## 2. 결정

### D1. 알람 정의는 Python 데이터로 남긴다 — YAML/JSON 외부화 안 함

정의에는 `transform_threshold: lambda gb: gb * 1024**3`, 태그 조건부 변형(Aurora Serverless/Writer/Readers,
APIGW REST/HTTP/WS, EC2 앱 상태검사 옵트인, NLB 대상그룹 제외), 등급별 M-of-N 후처리가 있다. 이걸 YAML로
옮기면 그걸 표현할 미니 언어를 발명하게 된다. 데이터클래스가 정답이고 이미 거의 그렇다.

### D2. 메트릭 자동 발견(`ListMetrics`)으로 알람을 늘리지 않는다

110개는 SRE 골든 시그널 기준으로 **고른** 것이다(`/new-collector` §11-7). 자동 발견은 소음을 늘린다.
이 제품의 가치는 큐레이션이다.

### D3. 타입 하나 = 스펙 객체 하나 — 나머지는 파생

```python
# common/resource_types/sqs.py  ← 타입 추가 = 이 파일 하나 + 테스트
SPEC = register(ResourceTypeSpec(
    type="SQS",
    label="SQS 큐",
    dimension_key="QueueName",
    rgt_type="sqs",                                   # RGT ResourceTypeFilters
    identity=lambda arn, tags: Identity(resource_id=arn.rsplit(":", 1)[-1]),
    alarms=[
        AlarmDef("SQSMessagesVisible", "AWS/SQS", "ApproximateNumberOfMessagesVisible",
                 stat="Average", comparison=">", period=300, display=("…", ">", ""), default=1000),
        …
    ],
    alive=_alive_by_get_queue_url,                    # describe 기반 — RGT로는 존재를 증명할 수 없다
    lifecycle=(Lifecycle("DeleteQueue", DELETE, extract=_queue_from_url),
               Lifecycle("TagQueue", TAG_CHANGE, extract=_queue_from_url)),
))
```

`ResourceTypeSpec`이 담는 것과 그로부터 **파생되는 기존 이름**(호출부 111곳은 그대로 둔다):

| 스펙 필드 | 파생되는 기존 이름 |
|---|---|
| `type`, `aliases` | `SUPPORTED_RESOURCE_TYPES`, `_RESOURCE_TYPE_TO_COLLECTOR`(alias 포함) |
| `alarms` (리스트 또는 `Callable[[tags], list]`) | `_get_alarm_defs_raw` 분기, `_HARDCODED_METRIC_KEYS`(모든 변형 열거), `_NAMESPACE_MAP`, `_DIMENSION_KEY_MAP` |
| `AlarmDef.display`, `AlarmDef.default` | `_METRIC_DISPLAY`, `_METRIC_NAME_TO_KEY`, `HARDCODED_DEFAULTS` |
| `extra_threshold_keys` (옛 키·퍼센트 변형·동적 전용 — 이유 문자열 필수) | `HARDCODED_DEFAULTS`의 나머지 23개 |
| `lifecycle` | `MONITORED_API_EVENTS`, `remediation._API_MAP` |
| `rgt_type`, `enumerate`, `identity`, `alive`, `metrics` | 수집기(§D4) , `tag_cache.TAGGED_SERVICES` |

레지스트리 API는 알림 어댑터와 같다: `register()`, `get(type)`, `all_specs()`, `types()`. 중복 등록은 즉시 실패.

### D4. 범용 수집기 — 나열은 RGT, 타입 코드는 "ARN → 정체"만

```
GenericCollector(spec).collect_monitored_resources():
    if tag_cache 활성 and spec.rgt_type:
        for arn, tags in cache.matching(rgt_type=spec.rgt_type, tag=Monitoring=on):
            yield spec.identity(arn, tags) → ResourceInfo
    elif spec.enumerate:            # RGT 부족·IAM 미부여 → 타입 고유 나열(기존 코드 그대로)
        yield from spec.enumerate()
```

- `get_metrics`는 **알람 정의에서 생성**한다 — 정의가 이미 `namespace`·`metric_name`·`stat`을 갖고 있고
  `collect_metric`/`MetricBatch`가 일반화돼 있다. 타입별 `get_metrics`가 하던 일은 그 셋을 나열하는 것뿐이었다.
- `resolve_alive_ids`는 **describe 기반을 유지**한다. RGT는 "태그 있는 리소스"만 돌려주므로 태그가 벗겨진
  리소스를 고아로 오판한다. 존재 증명은 서비스 API여야 한다.
- 서버 측 태그 필터를 지원하는 서비스(EC2 인스턴스·NAT·VPN의 `Filter=tag:…`)는 `enumerate`가 그걸 쓰면
  RGT 없이도 N+1이 없다 — natgw가 이미 하는 방식을 다른 EC2 계열이 공유한다.

**RGT를 쓰지 않고 `enumerate`를 유지해야 하는 타입** (0단계에서 확정):
EC2(CWAgent 디스크 경로 발견·인스턴스 상태) · ELB/TG(short-id 역매핑, LB↔TG 계층, `get_metrics(lb_arn=)` 특수 인자) ·
RDS/Aurora/DocDB(인스턴스 클래스·엔진·Writer/Reader 판정으로 내부 태그 `_is_serverless_v2` 등 생성) ·
APIGW(REST/HTTP/WS 판별) · S3·CloudFront·Route53(글로벌 → us-east-1) · WAF(REGIONAL/CLOUDFRONT 스코프).
나머지 — SQS SNS Lambda DynamoDB MSK MQ ACM Backup DX EFS ElastiCache OpenSearch SageMaker ECS NAT VPN —
는 RGT 한 경로로 충분하다(16개, 수집기 줄 수로 ~2,300줄).

**P3 1파에서 확정된 수정(2026-09-15):**
- `identity`는 스펙의 **순수 함수 `ARN → TagName`**(`arn_tail(":")` 등)이고, `enumerate`/`alive`는 boto3가 필요하므로 스펙이 아니라
  수집기 모듈에 남아 `GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)`로 묶인다(스펙 패키지는 표준 라이브러리만).
- **모듈은 삭제되지 않고 축소된다.** describe 폴백은 IAM 미부여·`TAG_CACHE=off`·프라임 실패에서 동작을 같게 하는 데 필요하고,
  존재 확인은 describe 고정이다. 남는 건 팩토리·`_enumerate`·`_alive` 셋 — 1파 10개가 1,386 → 883줄.
- 위 16개 중 **ACM과 DX는 RGT 나열이 아니다**: ACM은 Full_Collection(태그 없는 인증서도 수집)이라 태그 기반 RGT로는 대상을 다 못
  본다. DX는 `connectionState=available` 필터에 describe_connections가 어차피 필요해 아낄 콜이 없다. MQ는 브로커 1 → 인스턴스
  1~2(`{name}-{1|2}`)에 DeploymentMode describe가 들어가 스펙 `identity` 대신 모듈 `_identities`가 맡는다(캐시 경로는 쓴다).
  스펙에 `identity`가 없으면 `notes`에 "identity 없음"과 이유 — 테스트가 강제.
- `matching()`은 필터의 서비스가 프라임 목록에 없으면 빈 목록이 아니라 `None`을 돌려 폴백시킨다(빈 결과를 "0개"로 오판하지 않게).

### D5. 이관은 스트랭글러 — 중간 상태가 항상 동작한다

1. **파생부터**(동작 변화 0): 세 맵을 정의에서 계산하고 같은 이름으로 노출. **스냅숏 테스트**로
   "파생값 == 현재 손 맵"을 증명한 뒤 손 맵을 지운다. 완전성 PBT는 "파생 함수가 변형을 다 열거하는가"로 성격이 바뀐다.
2. **스펙 + 뷰**: 기존 수집기 모듈을 `LegacyCollectorSpec`으로 감싸 레지스트리에 올리고, §D3의 파생 이름을
   전부 뷰로 바꾼다. 이 시점부터 "타입 추가 = 스펙 파일 하나". 알람·생명주기 정의는 타입별로 스펙 안으로 옮긴다.
3. **범용 수집기**: §D4의 16개부터 `GenericCollector`로, 파일 삭제. 검증은 **alarm-sync 드라이런** —
   이관 전후 생성되는 알람 이름·차원 집합이 동일해야 한다(알람 이름이 곧 정체이므로 이게 회귀의 정의다).
4. **정리**: `/new-collector` 체크리스트를 "스펙 파일 작성 규칙"으로 다시 쓴다. 편집 지점 15 → **3**
   (스펙 파일, 테스트, CFN EventPattern).

### D6. CFN 템플릿의 EventPattern은 손으로 두되 정적 테스트로 묶는다

CloudTrail `detail.eventName` 목록은 CloudFormation이라 파생시킬 수 없다. 대신 `test_severity_consistency.py`와
같은 수법으로 **"템플릿의 eventName 집합 == 스펙의 lifecycle 집합"** 을 단위 테스트로 고정한다. 3곳 동기화가
1곳 + 테스트가 된다.

## 3. 데이터 흐름 (이관 후)

```
common/resource_types/*.py  ──register()──▶  registry(all_specs)
                                                 │
        ┌────────────────────────────────────────┼──────────────────────────────┐
        ▼                                        ▼                              ▼
  파생 뷰(기존 이름)                    GenericCollector(spec)          lifecycle → _API_MAP,
  SUPPORTED_RESOURCE_TYPES,             ├ RGT GetResources(Monitoring=on)  MONITORED_API_EVENTS
  _HARDCODED_METRIC_KEYS, _NAMESPACE_MAP│   └ spec.identity(arn) → ResourceInfo   (템플릿과 정적 테스트로 묶임)
  _DIMENSION_KEY_MAP, _METRIC_DISPLAY,  ├ get_metrics ← spec.alarms(namespace/metric/stat)
  HARDCODED_DEFAULTS, TAGGED_SERVICES   └ resolve_alive_ids ← spec.alive (describe)
        │                                        │
        ▼                                        ▼
  alarm_builder / dimension_builder /     daily_monitor(_COLLECTOR_MODULES ← all_specs)
  alarm_manager / resources.py (무변경)
```

## 4. 위험과 한계

| 위험 | 대응 |
|---|---|
| RGT 태그 반영 지연(분 단위) | 일일 런에는 무의미. 새 리소스는 다음 런에 잡힌다 — 지금도 그렇다 |
| RGT `ResourceTypeFilters` 문자열이 서비스마다 다름(`elasticloadbalancing:loadbalancer/app` 등) | **0단계**에서 29개 전부 실계정으로 확인해 표로 고정 |
| RGT가 못 나열하는 리소스·글로벌 서비스 | `enumerate` 유지 대상 명시(§D4) — 강제하지 않는다 |
| IAM `tag:GetResources` 없는 고객사 | 캐시의 기존 의미론 — 비활성이면 `enumerate`로 폴백, 동작은 예전과 같다 |
| 고아 판정이 RGT를 쓰면 태그 벗겨진 리소스를 고아로 오판 | `alive`는 describe 고정(§D4) |
| 이관 중 알람 이름·차원이 미세하게 바뀜 | alarm-sync 드라이런 집합 비교를 단계마다 게이트로 |
| ELB `get_metrics(lb_arn=)` 같은 특수 인자 | 스펙의 `metrics` 오버라이드로 남긴다 — 범용화 대상이 아니다 |

## 5. 기대 효과 — 무엇이 좋아지고 무엇은 아닌가

- **좋아지는 것**: 횡단 변경이 26번 방문 없이 한 곳에서 끝난다(태그 캐시 15/26 같은 반쪽 적용이 구조적으로
  불가능해진다). 드리프트 계층(병행 맵 3개)이 사라진다. 타입 추가가 15곳 → 3곳. 수집기 ~2,300줄 삭제.
- **좋아지지 않는 것**: 알람 정의 110개를 쓰는 일은 그대로다 — 그게 일이고, 그게 맞다. 타입 추가 빈도 자체는
  낮아(3개월 0건) "빨리 추가"는 주된 이득이 아니다.
- **비용**: RGT `GetResources`는 무료 API. describe 호출은 줄어든다.

## 부록 A. RGT `ResourceTypeFilters` 문자열 — 실계정 확인 (P0.1, 2026-09-15)

`resourcegroupstaggingapi:GetResources`에 29개 후보를 하나씩 넣어 **전부 유효**(거부 0)함을 확인했다
(`tlsgks678_poc`/us-east-1). `home-dev`/서울(태그 있는 리소스 2,688개)에서 실제 분포도 봤다 — `ec2:instance` 36,
`rds` 35, `elasticloadbalancing:targetgroup` 83, `backup` 38, `lambda` 20, `s3` 31 등. 두 계정 모두 `Monitoring=on`
태그는 0건이었다(home-dev의 알람 244개는 이 도구가 관리하는 것이 아니다).

| 타입 | 필터 | 비고 |
|---|---|---|
| EC2 | `ec2:instance` | |
| RDS · AuroraRDS · DocDB | `rds:db` | **셋이 한 필터** — 엔진·클러스터 판정은 describe 필요 → RDS 계열은 `enumerate` 오버라이드 유지(D4) |
| ALB · NLB · CLB | `elasticloadbalancing:loadbalancer` | **셋이 한 필터** — ARN의 `loadbalancer/app/`·`loadbalancer/net/`·(접미 없음=classic)으로 가른다 |
| TG | `elasticloadbalancing:targetgroup` | LB 계층·short-id 역매핑 때문에 `enumerate` 유지 |
| ElastiCache | `elasticache:cluster` | |
| NAT | `ec2:natgateway` | EC2 서버 측 태그 필터(`describe_nat_gateways Filter=tag:`)도 동등 — 둘 중 하나 |
| Lambda | `lambda:function` | |
| VPN | `ec2:vpn-connection` | |
| APIGW | `apigateway:restapis` + `apigateway:apis` | **두 필터** — REST와 HTTP/WS가 다른 리소스 타입, 디멘션 키도 다르다(`ApiName`/`ApiId`) |
| ACM | `acm:certificate` | 도메인명 역매핑은 `alive`에서 describe |
| Backup | `backup:backup-vault` | |
| MQ | `mq:broker` | TagName `{broker}-{1\|2}` 역매핑은 `alive`에서 |
| OpenSearch | `es:domain` | |
| SQS | `sqs` | 서비스 단위 필터(리소스 타입 세그먼트 없음) |
| ECS | `ecs:service` | |
| MSK | `kafka:cluster` | |
| DynamoDB | `dynamodb:table` | |
| CloudFront | `cloudfront:distribution` | 글로벌 → us-east-1에서 조회 |
| WAF | `wafv2:webacl` | REGIONAL은 리전, CLOUDFRONT 스코프는 us-east-1 |
| Route53 | `route53:healthcheck` | 글로벌 → us-east-1 |
| DX | `directconnect:dxcon` | |
| EFS | `elasticfilesystem:file-system` | |
| S3 | `s3` | 서비스 단위 필터, 버킷 리전은 별도 조회 |
| SageMaker | `sagemaker:endpoint` | |
| SNS | `sns` | 서비스 단위 필터 |

결론: D4의 "RGT 순수 16타입 / 오버라이드 유지" 구분은 그대로 성립한다. 추가된 사실은 **LB 셋·RDS 셋이 필터 하나를
공유**한다는 것 — 범용 수집기는 필터당 한 번 부르고 `identity()`가 ARN으로 타입을 갈라야 한다(같은 필터를 타입마다
세 번 부르지 않도록 스펙에 `rgt_type` 공유를 허용하고 결과를 타입별로 분배한다).

## 6. 비교한 대안

| 대안 | 왜 안 하나 |
|---|---|
| YAML/JSON 설정 파일 | 람다·조건 분기·정책 후처리를 표현할 미니 언어 필요(D1) |
| `ListMetrics` 자동 발견 | 큐레이션이 가치, 소음 증가(D2) |
| AWS Config 인벤토리 | 고객사에 Config 활성화 요구(비용·권한) — RGT는 무료·이미 권한 있음 |
| 전면 재작성 | 중간 상태가 깨진다. 스트랭글러(D5)로 단계마다 드라이런 게이트 |
| 그대로 두기 | 다음 횡단 변경에서 또 26번 방문하고 또 반쪽에서 멈춘다 |
