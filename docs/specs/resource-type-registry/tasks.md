# 리소스 타입 레지스트리 — 작업 계획

스트랭글러 순서다. 각 단계 끝에서 전체 테스트 + alarm-sync 드라이런 집합 비교가 게이트고, 어느 단계에서
멈춰도 저장소는 동작한다. 예상 규모는 순수 작업 시간이며, 라이브 검증·리뷰는 별도.

## Phase 0 — 확인 (반나절)

- [ ] 0.1 **RGT 리소스 타입 문자열 표** — 29개 타입 각각의 `ResourceTypeFilters` 값을 실계정(`tlsgks678_poc`,
      가능하면 `home-dev` 읽기 전용)에서 `GetResources`로 확인. 못 나열하는 타입은 `enumerate` 유지 대상으로 표시
      (설계 D4의 목록을 확정한다).
- [ ] 0.2 **현재 손 맵 스냅숏** — `_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`_DIMENSION_KEY_MAP`·`_METRIC_DISPLAY`·
      `HARDCODED_DEFAULTS`·`MONITORED_API_EVENTS`·`_API_MAP`(이벤트→타입)·`_RESOURCE_TYPE_TO_COLLECTOR`·`TAGGED_SERVICES`를
      JSON으로 저장(`backend/tests/fixtures/registry_snapshot_2026-09.json`). Phase 1~3의 동일성 테스트 기준.
- [ ] 0.3 **alarm-sync 드라이런 기준선** — dev 계정 전체 리소스에 대해 생성될 알람 이름·차원 집합을 덤프.
      이후 단계의 회귀 기준(R5).

## Phase 1 — 파생 (하루, 동작 변화 0)

- [ ] 1.1 `alarm_registry.py`에 `_derive_maps()` — 타입별 `_get_alarm_defs_raw`를 **모든 태그 변형**으로 호출해
      metric/namespace/dimension_key 집합을 모은다. 변형 열거는 각 조건부 함수 옆에 `VARIANTS = ({...}, {...})`로
      선언(Aurora 4조합, APIGW 3종, EC2 앱검사 on/off, TG ALB/NLB).
- [ ] 1.2 세 맵을 `_derive_maps()` 결과로 바꾸되 **이름은 유지** — 호출부(`resources.py` `alarm_manager.py`
      `dimension_builder.py`) 무변경.
- [ ] 1.3 스냅숏 테스트: 파생값 == 0.2 스냅숏. 통과 후 손 맵 리터럴 삭제.
- [ ] 1.4 `test_pbt_registry_completeness.py` 재정의 — "손 맵이 정의와 맞나"가 아니라 "VARIANTS가 조건 분기의
      모든 경로를 덮나"(분기 커버리지). 편집 지점 15 → 12.

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
