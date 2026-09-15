# 리소스 타입 레지스트리 — 작업 계획

스트랭글러 순서다. 각 단계 끝에서 전체 테스트 + alarm-sync 드라이런 집합 비교가 게이트고, 어느 단계에서
멈춰도 저장소는 동작한다. 예상 규모는 순수 작업 시간이며, 라이브 검증·리뷰는 별도.

## Phase 0 — 확인 (반나절)

- [x] 0.1 **RGT 리소스 타입 문자열 표** — 29개 전부 유효 확인(2026-09-15, `tlsgks678_poc`/us-east-1 + `home-dev`/서울).
      결과와 주의점(LB 셋·RDS 셋이 필터 하나를 공유, APIGW는 두 필터)은 `design.md` 부록 A.
- [x] 0.2 **현재 손 맵 스냅숏** — `backend/tests/fixtures/registry_snapshot_2026-09.json`(2026-09-15, 코드 변경 전).
      기본 변형 정의 103개·생명주기 이벤트 66개 포함.
- [x] 0.3 **alarm-sync 드라이런 도구** — `scripts/alarm_sync_dryrun.py`(2026-09-15). 드라이런 기능이 없어서 만들었다.
      이름·차원을 따로 계산하지 않고 **진짜 생성 경로**(`create_alarms_for_resource`)를 쓰기만 가로채는 CloudWatch
      스텁(`RecordingCloudWatch`) 위에서 돌려 `put_metric_alarm` payload를 그대로 덤프한다 → 디스크 경로 발견·동적
      알람·등급 태그까지 실제와 같다. `--diff before after`가 이관 게이트(종료 코드 0 = 0 diff). 단위 테스트
      `tests/test_alarm_sync_dryrun.py`(쓰기가 실제 클라이언트에 닿지 않음·정렬·diff).
      **기준선은 비어 있다**: dev·home-dev 모두 `Monitoring=on` 리소스가 0개(P0.1 실측). Phase 3 게이트로 쓰려면
      dev 리소스 몇 개에 태그를 붙여야 한다(사용자 결정 — 알람 개당 월 $0.10). 그때까지는 수집기 단위 테스트
      (`test_collectors.py`, 26개 모듈 mock)가 나열·정체 회귀를 맡는다.

## Phase 1 — 파생 (하루, 동작 변화 0) ✅ 2026-09-15

- [x] 1.1 `_ALARM_DEF_VARIANTS` — 조건부 함수가 읽는 태그의 모든 조합(EC2 옵트인 2, Aurora 2³=8, TG 3, APIGW 3).
      `_variant_defs(type)`이 전부 열거해 합친다. 규칙은 셋이 다르다: 메트릭 키 = 합집합 − `opt_in`, 네임스페이스 =
      합집합 + `_EXTRA_NAMESPACES`(TG의 NLB — 빌드 시 해석기가 바꿔 끼움), 디멘션 키 = **기본 변형**(APIGW HTTP/WS는
      `ApiId`라 변형끼리 다르다 — 정적 표는 REST 기본값).
- [x] 1.2 세 맵을 파생값으로, 이름 유지 → 호출부 무변경. 덤: `elif` 29분기가 `_ALARM_DEFS_BY_TYPE` 표 + 3줄 디스패치로
      (TG 인라인 분기는 `_get_tg_alarm_defs`로). **이 표의 키가 곧 타입 목록** — P2 스펙 레지스트리의 씨앗.
      EC2 앱 상태검사 정의에 `"opt_in": True`. `alarm_registry.py` 1,902 → 1,855줄.
- [x] 1.3 스냅숏 테스트 통과. 의도한 차이 1건을 `ACCEPTED_DIFFS`에 이유와 함께: Aurora `ServerlessDatabaseCapacity` —
      정의(`_AURORA_SERVERLESS_CAPACITY`)는 있지만 어떤 변형도 emit하지 않고(ACUUtilization이 대신) 정적 표의
      **런타임 소비처가 없다**(`alarm_manager`는 import만 — facade 재수출 — 실제로는 태그 기반
      `_get_hardcoded_metric_keys()`를 쓴다). 옛 리터럴을 단언하던 `test_alarm_registry.py` 2건을 파생 기준으로 고침.
- [x] 1.4 `test_pbt_registry_completeness.py` 재정의 — ① 파생 == 스냅숏(+이유 있는 예외, 죽은 예외는 실패)
      ② 조건부 함수 **소스를 훑어** `resource_tags.get(키)`가 전부 변형에 열거돼 있는지 ③ 변형이 실제로 정의를
      바꾸는지 ④ 기본 변형은 디멘션 키 하나 ⑤ 옵트인은 기본 집합에 없고 태그와 함께는 있음. `/new-collector` 3항 갱신.
      편집 지점 15 → 12. 전체 스위트 통과.

## Phase 2 — 스펙 객체와 뷰 (2~3일)

- [x] 2.1 `common/resource_types/__init__.py`(2026-09-15) — `ResourceTypeSpec`(frozen)·`Lifecycle`·`register/get/all_specs/types`,
      중복 타입·별칭 즉시 실패. 순환 회피: 이 모듈은 `alarm_registry`(logging만)와 stdlib만 의존 — 수집기는 **모듈 이름**으로,
      CloudTrail ID 추출기는 remediation에 둔다(이벤트→타입 매핑만 스펙). `AlarmDef`·`Identity`는 2.4/P3에서.
- [x] 2.2 어댑터 없이 끝냈다 — 스펙이 `collector` 이름과 `alarms(tags)`(→`_get_alarm_defs_raw`)로 기존 데이터를 **가리킨다**.
      29개 등록, 등록 순서 = `SUPPORTED_RESOURCE_TYPES` 순서. LB 셋은 이벤트를 ALB 스펙에 `target="ELB"`로, `TagResource`/
      `UntagResource`는 `SHARED_LIFECYCLE`(MULTI). 예외마다 `notes` 필수(테스트가 강제: 프라임 안 함·생명주기 없음).
- [x] 2.3 파생 뷰 전환 — `common.SUPPORTED_RESOURCE_TYPES`·`MONITORED_API_EVENTS`(뷰), `daily_monitor._COLLECTOR_MODULES`·
      `_RESOURCE_TYPE_TO_COLLECTOR`(importlib, 명시 import는 테스트 패치 경로라 유지), `remediation._API_MAP`(타입 절반은
      레지스트리, 추출기 표 `_EXTRACTORS`와 어긋나면 **import 시 RuntimeError**), `tag_cache.TAGGED_SERVICES`(`rgt_prime`).
      `tests/test_resource_type_registry.py`가 스냅숏 동일성·불변식·소비처 연결을 고정. 함정: 패치 정규식이 `EC2`·`Route53`·`S3`
      (숫자 포함 타입명)를 놓쳐 10항목이 반쯤 바뀐 채 남았다 — 사후 검증을 같은 패턴으로 하면 공허하다.
- [x] 2.4a 알람 정의 이관(2026-09-15) — `_X_ALARMS` 리스트·조건부 함수·상수 **1,347줄**을 ast 소스 구간 이동으로
      `common/resource_types/<type>.py` 29개에 원문 그대로(선행 주석 포함). 각 모듈 끝에 `SPEC = register(ResourceTypeSpec(…,
      alarm_defs=…, variants=…))`. `base.py`가 데이터클래스·레지스트리·뷰, `__init__`이 import 순서(=타입 순서).
      `alarm_registry.py` 1,855 → **449줄**: `_ALARM_DEFS_BY_TYPE`·`_ALARM_DEF_VARIANTS`·`_GLOBAL_SERVICE_REGION`을 스펙에서
      파생, 옛 이름(`_EC2_ALARMS` 등 43개)은 재수출(alarm_manager facade·테스트 경로). 게이트: 스냅숏 `alarm_defs_default`
      29/29 동일. 이동 구간이 모듈 내 다른 이름을 하나도 참조하지 않아(분석으로 확인) import 수정 0.
      함정: `'''`가 든 긴 heredoc은 Git Bash 파싱에서 죽는다 — 스크립트는 파일로 쓰고 실행할 것(메모리에 있던 규칙).
- [x] 2.4b(2026-09-15) `_METRIC_DISPLAY`(114)·`HARDCODED_DEFAULTS`(117) → 스펙의 `display`/`defaults`(타입의 변형 정의가 쓰는 키,
      공유 키 CPUUtilization×5 등은 타입마다 선언하고 뷰가 값 동일성 강제). 잔여는 `legacy.py`의 `add_shared_thresholds(reason=…)`:
      옛 친숙 태그 키 11(`_LEGACY_TAG_MAP` 값 전부 — 메트릭 키 개명 전 호환)·퍼센트 변형 2. `ServerlessDatabaseCapacity`는
      Aurora 모듈에(정의는 있으나 미emit, 주석). 뷰 `metric_display()`·`hardcoded_defaults()`는 **정의된 모든 메트릭 키에 표시명·기본치가
      있는지**도 검사해 없으면 import 시 실패(정의만 추가하고 기본치를 빠뜨리는 실수를 막는다). `alarm_registry.py` 449 → **337줄**,
      `common/__init__`의 `HARDCODED_DEFAULTS`도 뷰. 게이트: 스냅숏 두 표 동일 + 전체 스위트.
      실제 여분은 23이 아니라 14였다 — 나머지 9(Api4xx·Ws*·ACU·ReplicaLag·StatusCheckFailed_Application)는 변형 정의 키였다(P1 변형 열거 덕에 드러남).
- [x] 2.5 생명주기 이관 — 66개 이벤트가 타입별 `lifecycle`로(2.1에서 함께). 추출기는 remediation에 남고 `_build_api_map()`이
      둘을 맞춘다. ELB 이벤트는 ALB 스펙(`target="ELB"`), DocDB·Aurora는 RDS 이벤트 공유(notes에 명시).
- [x] 2.6 **템플릿 정합 테스트**(R8) — `test_template_cloudtrail_event_pattern_equals_the_registry_events`: 템플릿의 CloudTrail
      EventPattern `detail.eventName` 집합 == 레지스트리 이벤트 합집합. 통과(66개).
- [x] 2.7 시연(2026-09-15) — 테스트로 고정: `test_adding_a_type_is_one_spec_and_everything_follows`(가짜 Kinesis 스펙 하나 등록 →
      타입 목록·수집기 맵·이벤트·RGT 서비스·표시명·기본치에 전부 나타남), `test_a_definition_without_display_or_default_fails_at_view_time`,
      `test_a_type_cannot_redefine_a_shared_key`. 레지스트리 전역은 픽스처가 복사·복원한다.

## Phase 3 — 범용 수집기 (3~4일, 3파)

- [x] 3.1(2026-09-15) `common/collectors/generic.py` `GenericCollector(spec, alive=, enumerate=, identities=)` — `CollectorProtocol`
      그대로. 나열: `spec.identity`(ARN→TagName, 순수) + `rgt_prime`이면 활성 태그 캐시의 `matching(rgt_filters)`(서비스 콜 0) →
      아니면 모듈의 `_enumerate()`(옛 describe 코드, `(TagName, tags)` 반환) → Monitoring=on 필터는 범용이 건다. `get_metrics`는
      `spec.alarms(tags)`를 그대로 `collect_metric`에(배치 record/serve 그대로 탄다; 옵트인은 `alarms(tags)`가 이미 가르므로 따로
      안 뺀다). `resolve_alive_ids` = 모듈 `_alive`(describe 고정). `tag_cache`: `TagCache.matching()`·`cached_matching()`·
      `arn_matches_filter()`(RGT 필터 문자열 의미 그대로 — `sqs`는 서비스 전체, `lambda:function`은 `type/`·`type:` 접두, APIGW의
      `/restapis/…`는 앞 슬래시 제거), 프라임한 서비스를 기억해 **프라임 안 된 서비스 필터엔 None**(빈 결과를 0개로 오판 금지).
      `base.py`: `identity` 필드, `arn_tail(sep)`·`arn_resource()`, register 불변식 `identity ⇒ rgt_prime`, 뷰 `rgt_enumerated_types()`.
- [x] 3.2(2026-09-15) **1파** SQS SNS Lambda DynamoDB MSK MQ ACM Backup DX EFS → 범용 위로. **파일 삭제가 아니라 축소**: 폴백
      나열(`_enumerate`)과 describe 존재 확인(`_alive`)은 환원 불가능해 모듈에 남는다(IAM 미부여·`TAG_CACHE=off`·프라임 실패 시
      동작이 같아야 하고, 테스트 60여 건이 `_get_<svc>_client`를 패치한다). 1,386 → 883줄(+generic 130). RGT 나열 7타입(SQS SNS
      Lambda DynamoDB MSK Backup EFS — EFS는 `rgt_prime` 켬, TAGGED_SERVICES += elasticfilesystem 스냅숏 갱신), MQ는 모듈
      `_identities`(브로커 1 → 인스턴스 1~2, DeploymentMode describe), **ACM·DX는 describe 유지**(ACM Full_Collection은 태그 없는
      인증서도 수집하므로 RGT 불가; DX는 상태 필터에 describe가 어차피 필요) — 이유는 스펙 `notes`("identity 없음"), 테스트가 강제.
      게이트(라이브 드라이런 기준선이 비어 있어 오프라인): ① `tests/fixtures/collector_metrics_snapshot_2026-09.json` — 이관 **전**
      타입별 `get_metrics`가 내던 쿼리(41변형 중 40 캡처, CloudFront는 자체 CW 클라이언트라 3파에서) == 범용이 내는 쿼리, 10/10 동일.
      ② 같은 가짜 리소스를 RGT 페이지와 describe 응답에 넣고 두 경로 ResourceInfo 동일(`tests/test_generic_collector.py`).
      ③ 기존 `test_collectors.py` 1파 69건·orphan PBT·`test_resolve_alive_ids` 그대로 통과(폴백 경로).
- [x] 3.3(2026-09-15) **2파** ElastiCache OpenSearch SageMaker ECS NAT VPN → 범용 위로, 961 → 584줄. 태그 캐시 나열은
      **OpenSearch·SageMaker만**(둘 다 모듈 `_identities`: OpenSearch는 `_client_id`를 ARN 계정 세그먼트에서 — 옛 경로의 STS와 같은
      값, 콜 0; SageMaker는 describe_endpoint로 InService 판정 + `_variant_name` — 옛 경로도 같은 describe를 했다). **ElastiCache
      (엔진 redis/valkey·상태 필터, RGT는 memcached도 돌려줌)·ECS(구 형식 ARN엔 클러스터 없음, launchType에 describe_services)는
      describe 유지**, NAT·VPN은 서버 측 `Filter=tag:Monitoring`이라 RGT 자체가 불필요 — 넷 다 스펙 `notes` "identity 없음".
      공유 헬퍼는 만들지 않았다(둘의 `_enumerate`가 각 15줄이고 API 모양이 달라 헬퍼가 더 길다). 범용 `get_metrics`는 디멘션을
      **알람 쪽 빌더 `dimension_builder._build_dimensions`로** 만든다(OpenSearch ClientId·SageMaker VariantName·ECS ClusterName
      복합 디멘션이 내부 태그에서 나오므로 — 메트릭과 알람이 같은 시리즈를 본다). 게이트: 오라클에 2파 내부 태그 시나리오를
      **이관 전에** 추가(`_meta.extra_scenarios`)해 비교 — 옛 ECS/SageMaker 코드가 내부 태그 없이 빈 디멘션 값으로 질의하던
      `{}` 변형은 CloudWatch가 거부하는 쿼리라 제외(테스트 주석). 옛 ECS의 디멘션 순서(ClusterName 먼저)는 정렬 비교로 흡수.
      **태그 캐시 나열 최종 명단 10/16**: SQS SNS Lambda DynamoDB MSK Backup EFS MQ OpenSearch SageMaker — 설계 D4의 16개 중
      ACM DX ElastiCache ECS NAT VPN 여섯은 describe가 맞았다(이유는 각 스펙 notes, `test_rgt_enumeration_roster`가 명단 고정).
      **받아들인 차이 1건**: 옛 ElastiCache `get_metrics`는 CPUUtilization을 개명 전 키 `CPU`로 돌려줬다(Task 16 잔재). 범용은 정의
      키 `CPUUtilization` — daily run 임계치 해석은 두 키가 같음을 확인(기본 80, `Threshold_CPU` 태그는 `_LEGACY_TAG_MAP`으로
      적용), 바뀌는 건 임계치 알림의 metric_name 표기. `ACCEPTED_KEY_RENAMES`(테스트)에 이유와 함께. 같은 잔재가 RDS·Aurora·DocDB
      (CPU·FreeMemoryGB·FreeStorageGB·Connections…)와 NLB·TG(`RequestCount`, 정의 없음)에도 있다 — 3파 주의: `daily_monitor`
      L1035가 `FreeMemoryGB`류 **옛 키 이름으로 "작을수록 위험" 방향을 판정**하고 GB 변환도 옛 키에 묶여 있으므로 RDS 계열은
      `get_metrics` 오버라이드를 유지해야 하고, 키를 바꾸려면 그 분기와 함께 바꿔야 한다.
- [x] 3.4(2026-09-15) **3파** 10모듈 2,260 → 1,707줄. 둘로 갈렸다:
      **(a) 메트릭이 정의로 표현되는 다섯 — 범용 `get_metrics`**: CLB WAF Route53 APIGW S3. 나열은 CLB·WAF만 태그 캐시(모듈
      `_identities`가 ARN으로 가른다: CLB는 공유 필터 `elasticloadbalancing:loadbalancer`에서 `loadbalancer/<name>`(app/·net/·gwy/ 접두
      없음)만, WAF는 `regional/webacl/<name>/<id>`만 — CLOUDFRONT 스코프는 옛 수집기도 안 모았다). **Route53·S3·CloudFront는 글로벌
      서비스라 RGT 불가**(RGT는 리전 API — Route53/CloudFront는 us-east-1에만, 버킷은 버킷 리전에만 나오므로 실행 리전 캐시로
      나열하면 0개·누락으로 오판; `tag_cache`가 이 셋을 `trust_negative=False`로 다루던 이유와 같다). APIGW는 REST TagName이 API
      이름이라 ARN만으로 안 나오고 v2는 get_apis가 태그·프로토콜을 한 콜에 줘 RGT 이득이 REST 태그 N+1뿐 — describe 유지, REST
      태그만 캐시 히트를 보게 고침(옛 수집기는 캐시를 안 썼다). `arn_matches_filter`가 WAF 스코프 접두(`regional/`·`global/`)를 안다.
      **받아들인 차이 2건(알람과 같은 시리즈를 보게 된 것)**: 옛 WAF `get_metrics`는 WebACL+Rule로, 옛 S3 요청 지표(4xx/5xx)는
      BucketName만으로 물었다 — 알람은 각각 +Region, +FilterId를 쓴다. CloudWatch는 디멘션 집합이 정확히 일치해야 돌려주므로 옛
      질의는 데이터가 없었고(데일리 런에서 조용히 skip), 범용은 `_build_dimensions`로 알람과 같은 디멘션을 쓴다. 테스트
      `ACCEPTED_EXTRA_DIMS`에 이유. S3 요청 지표의 "Request_Metrics 미설정" warning 로그는 base의 info skip 로그로 바뀜(테스트 수정).
      **(b) 오버라이드 다섯 — `GenericCollector(…, metrics=_metrics)`**: EC2(CWAgent 메모리·디스크 경로별 list_metrics 디멘션
      발견, 결과 키 CPU/Memory/Disk_*가 임계치 분기에 묶임) · RDS+Aurora(`_enumerate`가 항목마다 타입을 준다 — 범용이
      `(TagName, tags, type)` 3튜플을 받는다; GB 변환·개명 전 키; `get_aurora_metrics`는 모듈 함수로 남고 daily_monitor가 타입으로
      가른다) · DocDB(같은 이유) · ELB(ALB·NLB·TG 3튜플, `lb_arn` 인자를 범용이 그대로 전달, NLB 대상그룹 AWS/NetworkELB, 정의에 없는
      RequestCount) · CloudFront(us-east-1 전용 CW 클라이언트, 배치 안 탐). 나열은 다섯 다 describe(엔진·클러스터 역할·LB 계층·
      상태 필터·글로벌) — 스펙 notes에 "identity 없음"과 "오버라이드" 이유, 테스트가 둘 다 강제. 옛 코드는 원문 그대로 `_enumerate`/
      `_metrics`/`_alive`로 이름만 바뀌었다(테스트 60여 건이 `_get_*_client`·`get_metrics` 모듈 속성을 패치 — 전부 통과).
      **최종 명단(29타입)**: 태그 캐시 나열 12(SQS SNS Lambda DynamoDB MSK Backup EFS MQ OpenSearch SageMaker CLB WAF) / describe
      나열 17(그중 정의 기반 메트릭 9: ACM DX ElastiCache ECS NAT VPN Route53 APIGW S3; 오버라이드 8: EC2 RDS AuroraRDS ALB NLB TG
      DocDB CloudFront). `test_rgt_enumeration_roster`·`test_every_collector_module_is_on_the_generic_collector`가 고정.
      수집기 디렉터리 **4,927 → 3,643줄**(generic 154 포함) — 설계의 "~2,300줄 삭제"에는 못 미쳤다: 폴백 나열·describe 존재 확인이
      환원 불가능했고, 오버라이드 다섯은 메트릭까지 남았다. 줄어든 것은 26개 모듈의 `get_metrics`·ResourceInfo 조립·Monitoring 필터.
- [x] 3.5(2026-09-15) 런 성능 — dev `daily_stage collect_resources`(감시 리소스 **0개**, 수집기 26개, 태그 캐시 36리소스 1콜):
      이관 전 8일간 정기 런 9.4~10.4초(중앙값 ≈9.8초) → 1파 배포 후 7.7~8.6초, 2파 배포 후 7.7~8.0초(≈ **-20%**). 줄어든 것은
      태그 캐시로 나열하는 12타입의 서비스 list 콜(리소스가 0개라 태그 N+1은 원래 없었다 — 실 고객사 계정에서는 N+1이 사라지는
      만큼 더 벌어진다). 태그 캐시 적용률: 옛 26개 중 15개 → 나열 12 + 폴백 태그 조회 전부(범용 경로 100%, AC 4). 측정은
      CloudWatch Logs `PERF_METRIC` 표본 비교이며 부하 벤치마크가 아니다. 3파 배포 후 수동 런 1회: **5.3초**(12타입 "via tag cache",
      오류·AccessDenied 0) — 표본 하나라 참고치.

## Phase 4 — 정리 (반나절)

- [x] 4.1(2026-09-15) `.claude/commands/new-collector.md` — §5를 "범용 수집기 위에 쓴다"(모듈에 쓰는 셋: 클라이언트 팩토리·
      `_enumerate`·`_alive`; identity/identities/metrics 오버라이드 규칙과 이유 필수), 3번(정의는 스펙 파일)·6번(스펙 + 모듈)·
      2번(ARN→ID는 스펙 identity + `_EXTRACTORS`) 재작성.
- [x] 4.2(2026-09-15) `docs/ALARM-RULES.md` §9-1에 스펙 `identity` 안내(remediation `_EXTRACTORS`와 같은 TagName), `backend/common/CLAUDE.md`
      온보딩 8단계 → 스펙 우선 7단계(파생 맵은 손대지 않는다), `backend/common/HOW_DOES_THIS_WORK.md` Collector 절을 범용 수집기·명단으로.
- [x] 4.3(2026-09-15) `alarm_registry.py` 337줄 — 남은 것: 평가 정책(`_apply_eval_policy`), 파생 셋(`_derive_*`), 태그 기반 키 조회,
      severity 표, 그리고 옛 이름 43개 **재수출**(alarm_manager facade·테스트가 그 경로로 import — 지우면 깨진다, P2.4a 함정). 수집기
      디렉터리 3,643줄: 모듈 26개 전부 `GenericCollector` 위(테스트 `test_every_collector_module_is_on_the_generic_collector`).

## 하지 않는 것 (기록)

- YAML 설정화, `ListMetrics` 자동 발견, 알람 의미 변경, 프런트엔드 변경.
- Phase 3에서 RGT가 안 되는 타입을 억지로 RGT로 옮기기 — `enumerate` 오버라이드가 정답이다.
