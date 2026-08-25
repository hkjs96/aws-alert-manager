# 알람 엔진 개선 로드맵

> 기준 커밋 `104aa61` (2026-08-25) · 방법론: 페르소나 5종 독립 리뷰 + 통합
> P1 옵저버빌리티 아키텍트 · P2 디텍션 엔지니어 · P3 시스템 성능 · P4 Next.js 성능 · P5 통합(수석 아키텍트)

## 요약 — 세 가지 결정

1. **알람 식별: 이름 파싱을 버리고 태그 + 메타데이터로.**
   정본은 AlarmDescription JSON, 조회 인덱스는 CloudWatch 알람 태그. 이름은 MARK 호환
   표시 전용으로 강등. 부산물로 daily run의 describe_alarms 콜 약 -99%.
2. **임계치: Anomaly Detection이 아니라 주기적 재보정 잡.**
   28일 p99 × 마진을 주 1회 계산해 오버라이드 테이블에 기록. 추가 비용 월 $1 미만
   (AD 전면 전환은 월 +$400~1,000). 근거를 숫자로 설명 가능, 롤백은 오버라이드 삭제뿐.
3. **런타임: Go/Rust 비권고 — arm64 전환 + 배치화가 정답.**
   런타임의 99%가 AWS API 대기(I/O-bound). Graviton은 코드 무변경 -20% 비용.
   콜 수 3,800 → 140으로 줄이는 배치화가 본질적 개선.

리뷰 중 **운영 영향 잠복 버그 7건**이 추가 발견되어 Phase 0로 분리했다.

---

## Phase 0 — 즉시 수정 (버그, ~1주)

| # | 결함 | 영향 | 위치 | 공수 |
|---|------|------|------|------|
| 1 | EC2 컬렉터 `describe_instances` 페이지네이션 누락 | 1페이지 초과 인스턴스 침묵 누락(알람 미생성·고아 오판) | `collectors/ec2.py:48` | S |
| 2 | `describe_alarms` 응답에 없는 `Tags` 필드를 읽음 | Severity 항상 SEV-5, 대시보드 critical_count 항상 0 | `daily_monitor:452,567,1017`, `cw_helper.py:150` | S |
| 3 | `_recreate_alarm_by_name`이 삭제 선행 후 정의 미발견 시 반환 | metric_key 어긋나는 순간 **알람 유실** | `alarm_builder.py:446-463` | S |
| 4 | 재생성 경로 2곳 `resource_tags` 누락 | ACM/APIGW 알람 이름 분열 → sync 영구 실패·중복 누적 | `alarm_builder.py:385,548` | S |
| 5 | 디스크 알람 재생성 라벨 불일치 | `"[EC2] name unknown > 80"` 이름 생성 | `alarm_builder.py:491` | S |
| 6 | sqs_worker가 만료되는 STS 자격증명을 `lru_cache` 무기한 캐시 | warm 컨테이너 장기 생존 시 ExpiredToken | `sqs_worker:103-116` | S |
| 7 | FE `/api/debug-env` 무인증 환경 구성 노출 | 공격 표면 정보 | `app/api/debug-env/route.ts` | S |

같은 주에 함께: Worker 타임아웃 300→900s, **arm64(Graviton) 전환**, FE `auth()`/데이터 함수
`React cache()` dedupe, `/api/me` loaded 플래그, `next/font` 전환, ToastProvider `useMemo`,
측정 베이스라인(run 단계별 소요 필드 + AWS/Usage CallCount) 수집 시작.

---

## P1 — 알람 아이덴티티: 이름에서 태그로

검증 결과 이름 역파싱 정규식은 3벌이 아니라 **프로덕션 5벌**(daily_monitor, cw_helper,
routes/alarms·dashboard·resources). 현재 이름이 표시·정체성·임계치 3역을 겸해, 임계치 변경
= 이름 변경 = 정체성 변경이 된다.

**목표 구조**
- **정본 = AlarmDescription JSON v2** (`schema_version`, `metric_key`, `resource_id`(Full ARN),
  `resource_type`, `mount_path`) — put_metric_alarm과 원자적, 태깅 실패에도 정체성 보존.
- **인덱스 = CW 알람 태그** (`ResourceId`/`ResourceType`/`MetricKey`/`Severity`) — 리소스→알람
  역조회를 Resource Groups Tagging API `GetResources` 1콜로. 태그 유실은 daily가 JSON으로 자가치유.
- **이름 = 순수 표시** — MARK 포맷은 바이트 단위 동결, `test_pbt_alarm_naming*` 4종을 표시 계약
  테스트로 존치, 이름 파싱 리터럴이 `alarm_naming.py` 밖에 있으면 실패하는 CI 가드 추가.

**마이그레이션 (무중단, 2~3주 + 관측 2주)**
M1 쓰기 경로 확장 + 고객사 IAM `tag:GetResources`(온보딩 템플릿 3곳 동기화) → M2 백필 잡
(dry-run·멱등, 결정 불가 알람은 삭제 금지·리포트만) → M3 듀얼 리드(태그 우선, 프리픽스 폴백
+ 히트율 계측, 0% 2주 지속 시 제거) → M4 정규식 5벌 제거.

**성능 부산물**: 리소스 200·알람 1,000 기준 describe_alarms ~1,500-2,000콜/런 →
프리페치+그룹핑 최종형 **~20콜(-99%)**. "타입 전체 알람을 리소스마다 재수신"하는 준제곱 패턴 소멸.

---

## P2 — 임계치: 트래픽 기반 재보정

**발견된 갭**: `ThresholdOverridesTable`이 알람 엔진에 연결돼 있지 않음(UI 표시용 routes만 소비).
(b)안 채택 시 resolver 체인 연결이 선행 작업.

| 접근 | 월 비용(리소스 1,000×알람 5) | 설명가능성 | 롤백 | 판정 |
|------|------|------|------|------|
| (a) CW Anomaly Detection | $900~1,500 (+80~200%) | 낮음(ML 밴드 설명 불가) | 어려움 | 3단계 한정 |
| **(b) 주기적 재보정 잡** | **$500.09 (+$0.09)** | 높음("28일 p99×1.2") | 오버라이드 삭제→자동 복원 | **추천** |
| (c) Fleet(metric-insights) 결합 | 현행 동등 | (b)와 동일 산식 | (b)와 동일 | 보완 관계 |

- **메트릭 분류 전제**: 가용성 이진(StatusCheckFailed, HealthyHostCount, TunnelState…)·오류=0
  계열은 재보정 금지. 1순위 순수 트래픽(RequestCount — 현재 전 리소스 10,000 고정), 2순위 지연,
  3순위 CPU(클램프 필수). 5XX 카운트는 백분위보다 에러율 메트릭 매스가 정도.
- **우선순위**: 수동(태그·고객사 설정)은 자동보다 항상 우선. 고객사별 옵트인으로 점진 적용.
- **가드 5중**: 데이터 충분성 → 절대 클램프 → 변화율 상한 25% → 히스테리시스 5%
  (sync가 0.001 차이에도 재생성) → SEV-2 이상 원천 제외.
- **도입**: 테이블-엔진 연결(1주) → Shadow 2주(노이즈 감소 사전 추정) → PoC 4주(EC2 CPU,
  ALB RequestCount, TargetResponseTime; 성공 기준 알람 이벤트 ≥30% 감소 + 인시던트 백테스트 미탐 0).
- **초안 정정**: Metric Insights 알람은 알람 수가 아니라 **분석 메트릭 수** 과금 —
  Fleet의 실익은 비용이 아니라 sync 부하·커버리지 지연 제거. `docs/specs/metric-insights-hybrid` 반영 필요.

---

## P3 — 백엔드 처리속도: 콜 수가 전부다

현재 구조에서 **리소스 200개가 사실상 한계선**(190~380초, Worker 타임아웃 300s 근접).

| daily run (N=200, 알람 1,000) | 현재 | 개선 후 | 수단 |
|---|---|---|---|
| 태그 조회 (N+1) | ~892 | ~8 | RGT GetResources 일괄 |
| 알람 조회 | ~622 | ~12 | 런당 1회 전체 조회 + 메모리 인덱스 |
| 메트릭 조회 | ~600 | 2~6 | GetMetricData 500쿼리/콜 |
| DynamoDB | ~1,615 | ~70 | batch_writer + Scan→GSI Query |
| 기타 | ~75 | ~45 | — |
| **합계** | **≈3,800** | **≈140** | -96% |
| **소요** | 190~380s | 15~30s | 병렬화 후 코어 2~4s |

- **순서**: 알람 캐시가 병렬화의 전제(DescribeAlarms 9 TPS — 현 구조로 병렬화하면 즉시 스로틀).
- **병렬화는 마지막**: 컬렉터 단위 + 리소스 단위 sync만. 계정 간 병렬 금지(`setup_default_session`
  전역). 워커 8~12, PutMetricAlarm 3 TPS 백오프. **256MB=0.14 vCPU라 512~1024MB 상향**
  (75 GB-s → 20 GB-s로 비용 오히려 감소).
- **Go/Rust**: 배치화 후 잔여 CPU 작업 = 정규식 ~1,200회 + JSON 역직렬화 수 MB = 수십 ms.
  전환은 곧 **PBT 테스트 자산 100여 개의 폐기**. api_handler 콜드스타트가 실측 문제면
  메모리 상향 → Python SnapStart → Provisioned Concurrency 순.
- **구조 변경 비권고**: 팬아웃 세분화·Step Functions 실익 없음. 벌크 "Configure Alarms"만
  기존 SQS 경로 재사용(3 TPS상 어차피 큐잉 필요).
- **수용 기준**: run 285s→≤30s, 일 API 콜 3.8k→≤200, 알람 생성·삭제 diff 0건.

---

## P4 — 프론트엔드: 중복 제거 먼저, 공유 캐시는 조건부

최대 병목은 "캐시 부재"가 아니라 **같은 요청 안에서 같은 일을 반복**하는 것.

- **P0 (전부 S, 리스크 0)**: `auth()`가 하드 로드당 5회 + 토큰 만료 직후 구글 리프레시 왕복
  블로킹 → `React cache()`로 요청당 1회. `/api/me` loaded 플래그(선언만 되고 미사용) 활용.
  debug-env 삭제. `next/font` 전환(render-blocking @import 제거).
- **P1**: 루트 레이아웃 `await fetchAlarms()`가 셸 첫 바이트 블로킹 → 배지를 async 자식
  + Suspense로 스트리밍(현 대시보드 Suspense는 위에서 await해 죽은 코드). GlobalFilterBar
  서버 props화. 필터 O(n×m)→Map/Set 인덱싱, 검색 디바운스+useDeferredValue,
  AlarmConfigTable 렌더 본문 사이드이펙트 제거(React 19 동시성 재실행 위험).
- **P2**: AlarmTable 이중 정렬 정리, 모달 next/dynamic, CreateAlarmModal 순차 POST→
  Promise.allSettled(대기 1/5), RecentAlarmsTable 상한. 가상화는 100행 상한이라 불필요.
- **크로스-리퀘스트 캐시 보류**: Next Data Cache는 사용자 간 공유 — Authorization 헤더 실린
  fetch에 켜면 응답 누수 위험, 예정된 AuthZ 유저별 스코핑과 정면 충돌. 스코핑 확정 후 전역
  데이터에 한해 태그+TTL 병행 도입(무효화는 프록시 중앙 관문 revalidateTag, Amplify 전파는 canary 실측).
- **정리**: Enable/DisableModal의 setTimeout 가짜 성공 피드백 → 벌크 기능 전까지 "미구현" 안내.
  `frontend/AGENTS.md`의 "React Query" 등 stale 서술 수정.

---

## P5 — 통합: 충돌 조정과 실행 순서

**페르소나 간 조정**
- **P3 알람 캐시 vs P1 태그 식별**: 수렴 관계. 지금 `alarm_index` 추상화로 런 스코프
  프리페치+인덱스(키=이름 파싱) 도입 → P1 완료 후 키 소스만 JSON/태그로 교체.
- **RGT GetResources 두 용도**: daily run은 전체 프리페치, 단건 경로(remediation·sqs_worker)는
  리소스당 2콜 고정. 같은 유틸 공유.
- **IAM 템플릿 1회 원칙**: P1 `tag:GetResources` + P2 `cloudwatch:GetMetricData`를 한 번의
  온보딩 템플릿 업데이트로 묶음(공개 S3 버킷 포함 3곳 수동 동기화라 두 번 안 건드림).
- **히스테리시스 선행**: sync의 0.001 드리프트 비교에 5% 히스테리시스를 재보정 도입 전에 먼저 반영.
- **P4 공유 캐시 ↔ AuthZ**: AuthZ 스코핑을 먼저 끝내고 조건부 도입.

**실행 순서**

| Phase | 내용 | 기간 |
|---|---|---|
| 0 | 버그 7건 + 타임아웃 900s + arm64 + FE 퀵윈 + 측정 베이스라인 | ~1주 |
| 1 | 알람 런 캐시 → GetMetricData 배치 → DDB batch_writer/GSI → RGT 태그 일괄화 + FE 스트리밍/인덱싱 | 1~2주 |
| 2 | 아이덴티티 마이그레이션 M1~M4 (IAM 템플릿에 P2 권한 동봉) + Severity 정상화 | 2~3주 + 관측 2주 |
| 3 | Threshold Calibrator: 테이블 연결 → Shadow → PoC. Fleet 결합은 PoC 후 결정 | 1+2+4주 |
| 4 | 병렬화 + 메모리 상향 · AuthZ 후 FE 조건부 캐시 · 벌크는 SQS 경로 | 이후 |

**의도적으로 하지 않는 것**: Go/Rust 재작성 · 팬아웃 세분화/Step Functions ·
Anomaly Detection 전면 전환 · 테이블 가상화.

---

*P1~P4 상세 보고서(파일:라인 근거 전체)는 리뷰 세션 로그에 보존. 페르소나 구성은 프로젝트 메모리 기록.*
