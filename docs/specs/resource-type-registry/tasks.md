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
- [ ] 2.4b `_METRIC_DISPLAY`(176)·`HARDCODED_DEFAULTS`(117)를 스펙의 `display`/`defaults`로. 여분 23개 임계치 키는
      `legacy.py`에 **이유 필수**(옛 태그 키 호환·퍼센트 변형·동적 전용). 파생 뷰 `_METRIC_DISPLAY`·`HARDCODED_DEFAULTS`는 이름 유지,
      충돌(같은 키 다른 값)은 import 시 실패. 게이트: 스냅숏 두 표 동일.
- [x] 2.5 생명주기 이관 — 66개 이벤트가 타입별 `lifecycle`로(2.1에서 함께). 추출기는 remediation에 남고 `_build_api_map()`이
      둘을 맞춘다. ELB 이벤트는 ALB 스펙(`target="ELB"`), DocDB·Aurora는 RDS 이벤트 공유(notes에 명시).
- [x] 2.6 **템플릿 정합 테스트**(R8) — `test_template_cloudtrail_event_pattern_equals_the_registry_events`: 템플릿의 CloudTrail
      EventPattern `detail.eventName` 집합 == 레지스트리 이벤트 합집합. 통과(66개).
- [ ] 2.7 시연: 가짜 타입 하나를 스펙 파일 + 테스트만으로 추가해 카탈로그·수집·생명주기에 나타나는지(AC 2).

## Phase 3 — 범용 수집기 (3~4일, 3파)

- [ ] 3.1 `GenericCollector(spec)` — RGT 경로(`tag_cache`를 "태그 조회"에서 "나열 소스"로 승격: `matching(rgt_type,
      tag=...)` 추가) + `enumerate` 폴백 + 정의 기반 `get_metrics` + `spec.alive`. `CollectorProtocol` 그대로 구현.
- [ ] 3.2 **1파 (RGT 순수, 위험 최소)**: SQS SNS Lambda DynamoDB MSK MQ ACM Backup DX EFS — 파일 삭제, 드라이런 0 diff.
- [ ] 3.3 **2파**: ElastiCache OpenSearch SageMaker ECS NAT VPN — NAT/VPN은 EC2 서버 측 태그 필터 `enumerate`를
      공유 헬퍼로(natgw가 이미 하는 방식).
- [ ] 3.4 **3파 (오버라이드 유지)**: EC2 ELB/TG RDS/Aurora/DocDB APIGW S3 CloudFront Route53 WAF — 스펙에 `enumerate`/
      `metrics` 오버라이드로 남기고 이유를 적는다. ELB의 `get_metrics(lb_arn=)`는 오버라이드 안에 봉인.
- [ ] 3.5 런 성능 비교 — `daily_stage`/`PERF_METRIC` 로그로 이관 전후 describe 호출 수·소요 시간. 태그 캐시
      적용률은 "범용 경로 100%"가 된다(AC 4).

## Phase 4 — 정리 (반나절)

- [ ] 4.1 `/new-collector` 체크리스트 → "스펙 파일 작성 규칙"(필드 설명, 오버라이드 시 이유 필수, 템플릿 이벤트 등록).
- [ ] 4.2 `docs/ALARM-RULES.md` §9(ARN→ID 매핑)를 스펙의 `identity`로 안내. `backend/common/CLAUDE.md` 온보딩 절 갱신.
- [ ] 4.3 `alarm_registry.py`에서 파생 코드만 남았는지 확인(목표 1,902 → ~400줄), 수집기 디렉터리 정리.

## 하지 않는 것 (기록)

- YAML 설정화, `ListMetrics` 자동 발견, 알람 의미 변경, 프런트엔드 변경.
- Phase 3에서 RGT가 안 되는 타입을 억지로 RGT로 옮기기 — `enumerate` 오버라이드가 정답이다.
