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

- [ ] 2.1 `common/resource_types/__init__.py` — `ResourceTypeSpec`(frozen dataclass), `AlarmDef`, `Lifecycle`,
      `Identity`, `register/get/all_specs/types`. 중복 등록 즉시 실패. `notification_adapters.py`와 같은 모양.
- [ ] 2.2 `LegacyCollectorSpec` — 기존 수집기 모듈을 감싸 `enumerate`/`metrics`/`alive`에 그대로 연결하는 어댑터.
      29개 타입을 **한 번에** 레지스트리에 올린다(알람·생명주기는 아직 옛 위치를 참조).
- [ ] 2.3 파생 뷰 전환 — `SUPPORTED_RESOURCE_TYPES`·`_RESOURCE_TYPE_TO_COLLECTOR`·`_COLLECTOR_MODULES`·
      `TAGGED_SERVICES`·`MONITORED_API_EVENTS`·`_API_MAP`을 `all_specs()`에서 계산. 스냅숏 테스트로 동일성 증명.
- [ ] 2.4 알람 정의 이관 — `_X_ALARMS` 리스트와 조건부 함수를 타입별 스펙 파일로 이동, `_get_alarm_defs_raw`의
      29분기 `elif`를 `get(type).alarms(tags)` 한 줄로. `_METRIC_DISPLAY`·`HARDCODED_DEFAULTS` 항목을 `AlarmDef.display`/
      `.default`로 이동. 여분 23개 임계치 키는 `extra_threshold_keys=(("CPU", "옛 태그 키 호환"), …)`로 **이유 필수**.
- [ ] 2.5 생명주기 이관 — `_API_MAP`의 66개 항목을 타입별 `lifecycle`로. ALB/NLB/CLB는 ELB 스펙의 alias,
      DocDB는 RDS 이벤트 + 엔진 판별(현행 유지, 스펙에 명시).
- [ ] 2.6 **템플릿 정합 테스트**(R8) — `template.yaml`의 CloudTrail EventPattern `detail.eventName` 집합 ==
      `{l.event for s in all_specs() for l in s.lifecycle}`. `test_severity_consistency.py`와 같은 정적 검사.
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
