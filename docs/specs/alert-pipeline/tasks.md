# Tasks — 알림 파이프라인

> 요구사항 `requirements.md`, 설계 `design.md`.
> 각 Phase는 다음 Phase를 막지 않도록 구성한다. 특히 **Phase 1의 이벤트 이력**은
> Phase 4(AIOps)의 전제조건이므로 뒤로 미루면 그만큼 학습 데이터 수집이 늦어진다.

---

## Phase 0 — 실측 (배포 없음, 반나절)

> **왜 먼저인가:** High 1,687건/일이 무엇 때문인지 모르면 auto-pause를 몇 분으로 잡을지,
> 무엇을 억제할지 정할 수 없다. `DescribeAlarmHistory`는 일반 CloudWatch API(무료 구간)라
> 아무것도 배포하지 않고 오늘 돌릴 수 있다.

- [x] 0.1 알람 이력 분석 스크립트 (`scripts/analyze_alarm_history.py`) — 구현 완료, 실행 대기
  - [x] 0.1.1 `DescribeAlarmHistory`로 지정 기간의 상태 전이 전량 수집 (계정·리전 파라미터화, 페이지네이션, `--role-arn` 크로스 어카운트)
  - [x] 0.1.2 **ALARM 지속시간 분포 산출** — "N분 유예 시 억제되는 비율" 표 (1/2/3/5/10/15분)
    - → **Auto-pause 기본값을 이 숫자로 결정한다** (design.md D4)
    - `recommend_pause()`: 억제율은 유예에 단조 증가하므로 최대값을 고르면 항상 가장 긴 후보가 나온다.
      유예 = 탐지 지연이므로 **최대 효과의 90%에 도달하는 가장 짧은 유예**를 택한다
  - [x] 0.1.3 알람별·리소스별·메트릭별 발화 횟수 상위 N — 상위 5/10/20개 집중도
  - [x] 0.1.4 시간대 분포 (UTC/KST 병기 + 막대)
  - [x] 0.1.5 flapping 후보 식별 — 하루 `FLAPPING_PER_DAY`회 이상
  - [x] 0.1.6 결과를 `docs/reports/ALARM-NOISE-{date}.md`로 출력
  - 테스트: `backend/tests/test_alarm_history_analysis.py` (32건 — 경계값·미해소·창 시작 시 이미 ALARM 등)
- [ ] 0.1.7 **실제 계정에서 실행** ← 다음 단계. 실 알람이 있는 계정 필요 (dev는 발화 이력이 거의 없음)
  - `AWS_PROFILE=... python scripts/analyze_alarm_history.py --days 7 --region ap-northeast-2`
  - 크로스 어카운트: `--role-arn arn:aws:iam::{고객사}:role/AlarmManagerMonitoringRole`
- [ ] 0.2 결과 리뷰 후 Phase 1 파라미터 확정 (auto-pause 유예, group_by 축, repeat_interval)

## Phase 1 — 수집 + 이력 + 기본 정제

### 1.1 EventBridge 경로 검증 (선행 — design.md U5) — ✅ 2026-09-02 완료

프로브: `scripts/probe_eventbridge_forwarding.py` (생성→발화→확인→정리 전 과정 자동, 재실행 가능)

- [x] 1.1.1 dev 계정 서울 리전에 테스트 알람 생성 → `set_alarm_state`로 즉시 전이
- [x] 1.1.2 서울 기본 버스 → us-east-1 커스텀 버스 크로스 리전 포워딩 룰 + 전달 역할 구성
- [x] 1.1.3 **이벤트 도달 확인** — ap-northeast-2 → us-east-1 도달함. **목적지 리전 제한 없음 → D1 유지**
- [x] 1.1.4 알람 생성/수정/삭제 이벤트도 수신됨 — `CloudWatch Alarm Configuration Change` (R1-4 충족)
- [x] 1.1.5 정리 — 알람·룰·버스·큐·IAM 역할 전부 삭제 확인(잔여 0)
- [ ] 1.1.6 **크로스 어카운트 검증** — 위 프로브는 동일 계정 내 크로스 리전만 확인했다.
  계정 간 전달(목적지 버스 리소스 정책 + 발신 측 역할)은 1.2.1~1.2.2에서 실측한다

### 1.2 인프라

- [x] 1.2.1 우리 계정 커스텀 이벤트 버스 + 버스 정책(고객사 계정 허용) — CFN
  - `AlertEventBus` + `AlertEventBusPolicy`(파라미터 `AlertBusSourceAccounts`, 비면 단일 계정 모드)
  - `AlertIngestDLQ` — 인제스터가 재시도까지 실패한 이벤트 (비어 있어야 정상)
  - 룰 2개: 커스텀 버스(크로스 어카운트) + 기본 버스(단일 계정 모드)
  - [ ] **후속:** 고객사 계정 등록 시 버스 정책을 자동 갱신 — 현재는 파라미터 수동 관리
- [ ] 1.2.2 고객사 온보딩 템플릿에 EventBridge 룰 + 전달 역할 추가
  - 온보딩 템플릿 3곳 동기화 (`infrastructure/customer-onboarding/` → `frontend/public/` → 공개 S3, `text/yaml`)
- [x] 1.2.3 `EventHistoryTable` — PK `series_id` / SK `event_key`, GSI `customer_day-index`, TTL 90일 (design.md **D8**)
- [x] 1.2.4 인제스터 IAM (`EventHistoryTable` PutItem+**Query** + `AccountsTable` Scan)
  - ⚠️ Query를 빠뜨려 dedup이 **조용히 동작하지 않았다** (2026-09-07 실측에서 발견).
    조회 실패를 fail-open으로 흘려보내는 설계라 로그를 보기 전엔 드러나지 않는다 —
    새 AWS 호출을 추가하면 **같은 커밋에서** 권한을 확인하라는 규칙(`/new-collector` IAM 체크)의 실제 사례

### 1.3 수집·정규화

- [x] 1.3.1 `common/alert_event.py` — 클라우드 중립 이벤트 스키마 정의 (R1-6)
  - [x] 테스트: CloudWatch 이벤트 → 정규화 스키마 변환 (22건, `test_alert_event.py`)
  - 파서는 어떤 입력에도 예외를 던지지 않고 `parse_error` + `raw`로 남긴다 (R2-1)
- [x] 1.3.2 정규화 Lambda `backend/alert_ingestor/` — 이벤트 수신 → 스키마 변환 → 이력 기록
  - [x] 테스트: 알 수 없는 형태의 이벤트를 버리지 않고 기록 (10건, `test_alert_ingestor.py`)
  - 적재 실패는 예외를 올린다 — EventBridge 재시도·DLQ가 안전망이므로 삼키면 안 된다
  - 계정→고객사 매핑은 컨테이너 수명 동안 캐시 (이벤트마다 스캔하지 않는다)
- [x] 1.3.3 `alarm_identity.identify_alarm()`으로 리소스 해석 (기존 모듈 재사용)
- [x] 1.3.4 **정제 이전에** 원본 전량 기록 (R2-1)
  - [x] 테스트: `suppressed=False`로 기록됨. 억제 사유 필드는 정제 엔진(1.4) 도입 시 채워진다 (R2-3)

### 1.4 정제 엔진

- [x] 1.4.1 `common/alert_suppression.py` — 순수 함수로 판정 로직 구현 (37건)
  - [x] 테스트: dedup — 동일 fingerprint 반복 시 repeat_interval 이전엔 미발송
  - [x] 테스트: SEV-1은 억제 제외 (R3-8) — **다른 모든 억제보다 앞선다**는 순서를 조합별로 고정
  - 판정 기준 시각은 **이벤트 발생 시각**이다(벽시계 아님) — 재시도로 늦게 처리돼도 결과가
    같고, 과거 이벤트를 새 규칙으로 재현할 수 있다(R2-5)
  - 지문은 `series_id` — 알람 이름은 임계치가 바뀌면 달라져 중복 판정이 초기화된다
- [x] 1.4.1b **Shadow 연결** — 인제스터가 판정을 기록만 하고 실행하지 않는다
  - [x] 라이브 실증(2026-09-07): 발화→NOTIFY, 해소→cleared 억제, 재발화→**dedup 억제** 확인
  - 발송자(2.2)가 붙기 전에 실제 트래픽으로 억제율(R9-1)을 측정하고 규칙을 검증한다
  - DEFER는 타이머가 없어 실행 불가 → 억제로 세지 않는다(과대 집계 방지)
- [x] 1.4.2 **상태 테이블** `AlertStateTable` (design.md **D9**, review-2026-09-07 B1) — 계획 `plan-state-grouping.md` §A — ✅ 2026-09-07 배포 (v20260907T065829)
  - [x] 받아들임 기준(라이브): **25번 토글 → 발화 NOTIFY 1건** — 실측 NOTIFY 1 · dedup 1 · flapping 23, 해소 알림 1, 상태 version 50, 충돌 0, AccessDenied 0
  - `common/alert_state.py` 순수 모듈 (`inputs_from_state` / `apply_event` / `unchanged` / `state_item`) — 멱등, PBT 3건(각 200 예시)
  - 상태 먼저, 이력 나중 — 재시도에 안전한 순서. 이력 Query(Limit=20)와 그 IAM은 제거, 상태 GetItem/PutItem 추가
  - `is_flapping` / `already_notified`를 상태에서 채워 `decide()`에 전달 — flapping 격리·해소 알림이 실제로 동작
  - 갱신은 `version` 조건부(PutItem) — 충돌 시 재판정(최대 3회) → dedup, 소진 시 fail-open NOTIFY `state_contention`
  - 상태 조회·갱신 실패는 fail-open이되 `PERF_METRIC state_ok=false`로 드러난다 (IAM 누락을 숨기지 않기 위해)
  - flapping 기본: 창 1일 · 3회 · 격리 1h (`ALERT_FLAPPING_QUARANTINE_SEC` / `ALERT_FLAPPING_WINDOW_DAYS`)
  - [x] 테스트: 억제 항목이 아무리 쌓여도 dedup 창이 유지됨 (핸들러 + 조건식 해석 가짜 테이블로 25번 토글)
  - [x] 테스트: 조건부 갱신 실패 시 재판정 → dedup / 소진 → fail-open / 상태→이력 순서
- [x] 1.4.3 Grouping — **타이머보다 먼저** (design.md **D10**, review S2) — 계획 `plan-state-grouping.md` §B — ✅ 2026-09-07 배포 (v20260907T074711)
  - [x] 받아들임 기준(라이브): 알람 250개 × (ALARM, OK) = 500건 → **실행 6개**(163초에 걸친 유입, 30초 창마다 1개), 500건 전부 `group_id`·`final_action`, 실행 전부 SUCCEEDED, 오류·경합 0
    - "1분 500건 → 실행 1개"는 CloudWatch `SetAlarmState` 한도(~3 TPS)로 라이브 재현 불가 — 핸들러 단위 테스트(500건 → 실행 1개)가 커버. 실행 수는 **이벤트 수가 아니라 시간 창 수**에 비례한다는 것이 라이브로 확인된 사실
  - **구성원 자격은 적재 시 이력의 `group_id`로 정한다** — 시간 창이 아니다. 창 방식은 "닫힌 직후 도착한 늦은 이벤트"가 어느 창에도 안 잡히거나 두 창에 잡힌다. `group_id-index`(sparse GSI)로 워커가 정확히 읽는다
  - 그룹은 **닫고 → Grace 5초 → 조회**한다 — 닫히기 전에 group_id를 받은 이벤트가 적재를 마칠 시간
  - 새 Lambda `alert_group_worker` (close/collect/finalize, 예약 동시성 20) + Step Functions Standard `aws-monitoring-alert-group-{env}` (전이 ~9/그룹)
  - 실행 이름 = 그룹 ID = `g-{sha1(그룹키)[:16]}-{연 시각}` — 결정적. 연 쪽이 죽어도 다음 이벤트가 같은 이름으로 재시작(멱등). 같은 초 재개방은 +1초 스탬프로 충돌 회피
  - 첫 이벤트만 실행을 연다(grp# 조건부 PutItem). 후속 이벤트는 이력에 group_id만. SUPPRESS는 그룹을 열지 않는다
  - 자기감시: 워커 Errors 알람 + 상태 머신 ExecutionsFailed 알람 → `ErrorAlertTopic`
  - ⚠️ 배포 주의: 기존 테이블에 GSI를 추가하면 CFN은 **백필 전에** 완료를 반환한다(확인 시점 `CREATING`). 큰 테이블이면 배포 직후 몇 분간 워커 조회가 실패할 수 있다 — 상태 머신 Retry(5/10/20초)로 일부 흡수, 그 이상은 재실행 필요
  - [x] 테스트: group_by 축이 같은 이벤트가 1건으로 묶임 / 경합·죽은 개방자 재시작·ExecutionAlreadyExists·fail-open·재개방
  - [x] 테스트: 폭풍(500건)에서 실행 수 = 1 (조건식 해석 가짜 테이블 + 가짜 Step Functions)
- [x] 1.4.3b Auto-pause **실행** — 그룹 실행 안의 Wait (판정 로직은 1.4.1에 있음) — 메커니즘 배포, **유예 값은 아직 비어 있음**
  - 실행: Wait(group_wait) → close → Grace → collect(DEFER 있으면 pause_sec) → Wait(pause) → finalize(fp# 상태로 해소 여부 판단) → **final_action write-back**
  - 유예 값은 Phase 0 실측 후 `ALERT_AUTO_PAUSE_SEC` 설정 (1.4.6까지는 환경변수). 값이 없어 라이브에서는 DEFER 경로가 돌지 않음
  - [x] 테스트: 유예 중 OK 수신 시 미발송 (`suppress/auto_pause`)
  - [x] 테스트: 유예 후에도 ALARM이면 발송 (`notify/auto_pause_expired`) + fp#에 알렸음 기록
  - [x] 테스트: write-back 후 억제율 집계에 DEFER 결과가 반영됨 → 리포트 `effective()`가 `final_action` 우선 (`test_alert_suppression_report.py`)
- [x] 1.4.4 Silence / 정비창 — 판정 + **저장소·API** — ✅ 2026-09-07 배포 (v20260907T085417)
  - [x] 테스트: 정비 시간대 억제, 종료 후 정상화, 스코프 매칭
  - [x] `AlertPolicyTable`에 저장, 인제스터가 60초 캐시로 읽는다 — **여기서 처음으로 실제 적용된다**
        (그전까지 `policy.silences`는 항상 비어 있어 정비 시간대에도 알림이 나갔다)
  - [x] API `GET/POST /alert/silences`, `DELETE /alert/silences/{id}` — 고객사 미지정(전역)은 관리자 전용
  - [x] 상한 30일 — 끝나지 않는 정비창은 알림을 영원히 지운다
  - [x] 판정은 **이벤트 발생 시각** 기준 — 재시도로 늦게 처리돼도 그때 정비 중이었으면 억제 (R2-5)
  - [ ] 관리 UI → Phase 2 채널 설정 화면과 함께 (같은 "알림 설정" 영역)
- [x] 1.4.5 Flapping 판정 함수 (`is_flapping`) — 실측 스크립트와 같은 기준식
  - [x] 격리 상태 저장·해제 → 1.4.2 상태 테이블의 `recent_episodes`/`quarantined_until` (라이브: 3번째 발화부터 격리)
- [x] 1.4.6 정제 설정을 DB에서 읽기 (R3-9) — ✅ 2026-09-07 배포 (v20260907T085417)
  - `common/alert_config.py` — 우선순위 **DB > 환경변수 > 코드 기본값**, 있는 필드만 덮어쓰는 부분 저장
  - 인제스터와 그룹 워커가 **같은 로더**를 쓴다 — 유예 값이 두 곳에서 갈리면 그룹이 엉뚱한 시간을 기다린다
  - 범위 밖 값은 **로더가 클램프**(런타임 계속 동작) / **API가 거절**(사람에게 알림) — 역할이 다르다
  - 읽기 실패는 환경변수로 폴백하고 `PERF_METRIC config_ok=false`로 드러난다. 그동안 정비창은 비므로
    억제가 **덜** 되지 실수로 더 되지 않는다
  - API `GET/PUT /alert/policy` — 변경은 관리자 전용, 60초 안에 반영

### 1.5 측정

- [x] 1.5.1 억제율·억제 사유별 건수 계측 (`perf_log` 규약 사용, R9-1·9-2) — ✅ 2026-09-07
  - `alert_ingest` 계측이 실제 처리 시간을 잰다(이전엔 0 고정). 적재 실패도 `ok=false`로 남긴다
  - **`scripts/alert_suppression_report.py`** — 이력 테이블(`customer_day-index`) 집계 → `docs/reports/ALERT-SUPPRESSION-{date}.md`.
    최종값 규칙 **`final_action` > `suppressed` > `auto_pause`(pending) > notify** — 그룹 워커의 write-back이 이긴다.
    발화 억제율(분모: 확정된 발화)·사유별·등급별·고객사별·시끄러운 시계열 top 15·그룹 통계·auto-pause 이득·데이터 품질
  - 1.4.4 완료로 정제 규칙 5종이 모두 배선됐다 — 억제율이 더 이상 구조적 하한이 아니다
    (리포트 "해석 주의"의 silence 문구는 정비창을 실제로 등록한 뒤 갱신)
- [x] 1.5.2 `docs/OBSERVABILITY.md`에 조회 쿼리 추가 — §7 판정·사유 분포, §8 처리 시간·실패 신호(state_ok/group_ok/ok), §9 그룹 통계

### 1.6 검토 반영 — `review-2026-09-07.md` — ✅ 2026-09-07 배포 (v20260907T035356)

- [x] 1.6.1 DLQ `ApproximateNumberOfMessagesVisible ≥ 1` + 인제스터 `Errors`/`Throttles` 알람 → **`ErrorAlertTopic` 직결** (Q1)
  - 우리 파이프라인을 태우지 않는다 — 자기 감시는 감시 대상에 의존하면 안 된다
  - ⚠️ **`ErrorAlertTopic` 구독이 0건** — 알람은 울리지만 받는 사람이 없다. 이메일/Slack 구독은
    확인 절차가 있는 수동 운영 작업이라 여기 묶지 않았다. 구독 전까지 이 알람들은 콘솔에서만 보인다
- [x] 1.6.2 인제스터 `ReservedConcurrentExecutions: 50` (S1) — 라이브 확인
- [x] 1.6.3 미관리 알람 `series_id` 폴백 — `resource_id` 비면 알람 ARN, 그것도 없으면 이름 (B2)
  - [x] 테스트: 해석 실패 알람 둘의 키가 다름 / 해석 성공 키는 불변
  - [x] 라이브: 미관리 알람이 `…#arn:aws:cloudwatch:…:alarm:NAME#metric` 아래 기록, 예전 키(`##`) 0건
- [x] 1.6.4 계정→고객사 캐시 5분 TTL (Q2) — 스캔 실패 시 **이전 매핑 유지**, TTL 뒤 재시도
  - [x] 테스트: TTL 경과 후 새 계정이 매핑됨 / 실패 시 이전 매핑 유지·즉시 재시도 안 함
- [x] 1.6.5 `raw` 64KB 상한 + `raw_truncated` 플래그 — 자르지 않고 `configuration`부터 덜어낸다 (Q3)
  - [x] 테스트: 상한 초과 시 식별 필드 보존 + `json.loads` 성공 (2단계 축소, 비-dict 방어)
- [x] 1.6.6 Phase 0 스크립트 `--days` 14 클램프 (B3)
  - 검토안의 "실효 창 = 응답 최초 항목"은 **채택하지 않았다** — 조용한 기간을 분모에서 빼면 반대로
    과대 산출된다. 분모는 min(요청, 14일)로 고정하고 리포트에 클램프 사실을 표시한다
  - [x] 테스트: 30일 요청 시 14일로 계산, 14일간 45회 발화가 flapping(≥3/일)으로 잡힘

### Phase 2 진입 조건 (review §5)

- [x] 1.4.2 상태 테이블 · 1.4.3 grouping · 1.4.3b 타이머 — 위
- [x] 이력 put에 `attribute_not_exists(event_key)` 조건 — ✅ 2026-09-08. 재전달은 예외 없이 `duplicate=true`로
      끝난다(예외면 EventBridge가 또 재시도). 첫 기록과 워커의 `final_action` write-back이 보존된다
- [x] `AlarmDescription` 메타데이터에 `severity` — ✅ 2026-09-08. 빌더가 태그와 같은 규칙으로 채우고
      `identify_alarm().severity` → 인제스터가 레지스트리보다 우선. 옛 형식은 폴백. `docs/ALARM-RULES.md` §13-4 보완
- [x] 라이브 검증(2026-09-08, v20260908T014154): 설명에 SEV-1 박은 알람 → 이력 severity SEV-1, 기본 알람 → SEV-3(레지스트리);
      같은 이벤트 2회 호출 → 2차 `duplicate=true`·행 1개·미리 심은 `final_action` 보존
- [x] P2 보완(review-personas F1·F2·F3, 2026-09-08): UI 등급 지정·변경 경로가 설명도 함께 쓰고
      (`set_description_severity`), 설명의 등급은 SEV-1~5만 인정하며, 옛 알람은 일일 동기화가 재생성 없이
      제자리에서 설명을 채운다. 미결 F8(재생성 시 태그 리셋)은 제품 결정

**→ Phase 2 진입 조건 충족.** 남은 선행 결정: U2(채널 등록 주체)·U3(필터 범위) — design.md §5

## Phase 2 — 인시던트 + 고객사별 다중 채널

### 2.1 인시던트

- [ ] 2.1.1 `IncidentTable` 설계 — 상태, 연결 이벤트, 타임라인
- [ ] 2.1.2 Step Functions 인시던트 생명주기 정의 (생성 → 통보 → ack 대기 → 해소)
  - [ ] 테스트: 원인 알람 전부 OK → 자동 resolved (R4-4)
  - [ ] 테스트: ack 시 에스컬레이션 중단 (R4-3)
  - [ ] 테스트: ack 후 미해결 지정 시간 초과 → 재알림 (R4-6)
- [ ] 2.1.3 ack 수신 경로 (웹 링크 우선, Slack 버튼은 2.2 이후)
- [ ] 2.1.4 MTTA·MTTR 산출 (R4-5)

### 2.2 채널

> **선행 결정 필요:** U2(등록 주체), U3(조건 범위) — design.md §5

- [ ] 2.2.1 `NotificationChannelTable` 설계 (고객사 × 채널 × 조건)
- [ ] 2.2.2 자격증명은 표에 함께 저장 (design.md **D7** — 별도 시크릿 저장소 없음)
  - [ ] **응답 필드 화이트리스트** — 목록·상세 어디에도 자격증명을 넣지 않는다 (R6-8)
    - `api_handler`에 `scan_all` 결과를 화이트리스트 없이 응답에 넣는 코드가 12곳 있다.
      채널 API는 그 관례를 따르지 말 것
  - [ ] 테스트: 채널 목록·상세 응답에 자격증명 값이 포함되지 않음
  - [ ] 테스트: 수정 API가 값을 받기만 하고 되돌려주지 않음
- [ ] 2.2.3 라우터 Lambda — 조건 매칭 → 채널별 발송
  - [ ] 테스트: 조건에 맞는 채널만 선택됨
  - [ ] 테스트: 채널 추가/삭제가 알람을 수정하지 않고 반영됨 (R6-5)
  - [ ] 테스트: 한 채널 실패가 다른 채널 발송을 막지 않음
- [ ] 2.2.4 어댑터 — Slack / Email(SNS) / 범용 Webhook
- [ ] 2.2.5 **채널별 속도 제한 + 폭풍 시 묶음 발송** (R6-9)
  - [ ] 테스트: Slack 초당 1건 제한 준수, 초과분은 요약으로 병합
- [ ] 2.2.6 재시도 + 최종 실패 기록 (R6-7)
- [ ] 2.2.7 설정 UI — `frontend/components/settings/NotificationSection.tsx`
  - 기존 `AccountSection` / `CustomerSection` / `ThresholdSection` 패턴 준용

### 2.3 정리

- [ ] 2.3.1 기존 알람의 `AlarmActions` 정리 (도달 불가 ARN 제거) — 드리프트 경로로 점진 반영
- [ ] 2.3.2 `sns_notifier` 기반 daily 2단계 알림과의 통합 여부 판단

## Phase 3 — 온콜 + 에스컬레이션

> **선행 결정 필요:** U1(온콜의 축). 답에 따라 3.1을 직접 구현하거나 외부 도구로 대체한다.
> `AWS SSM Incident Manager`는 신규 고객 차단으로 사용 불가(design.md §3).

- [ ] 3.0 U1 결정 — 우리 팀 단일 로테이션 vs 고객사별 온콜
  - [ ] 단일이면: GoAlert 등 외부 도구 검토 (멀티테넌트 지원 여부 확인)
  - [ ] 고객사별이면: 직접 구현 범위 산정
- [ ] 3.1 온콜 스케줄 — 로테이션 + 오버라이드 (R5-1~3)
- [ ] 3.2 에스컬레이션 정책 — 단계별 대상·대기시간 (R5-6)
  - [ ] 테스트: 1차 무응답 → 2차 통보
  - [ ] 테스트: 마지막 단계 무응답 기록 (R5-7)
- [ ] 3.3 Step Functions 에스컬레이션 상태 추가
- [ ] 3.4 MTTA/MTTR 리포트 + severity별 수신율 대시보드 (R9-3)

## Phase 4 — AIOps

> Phase 1의 이벤트 이력이 3~6개월 쌓인 뒤 4c·4d가 의미를 갖는다.
> **4a는 Phase 1과 병행 가능** — 재료(MetricHistory·Inventory·CloudTrail)가 이미 있다.

### 4a. 규칙 기반 분석 (AI 불필요)

- [ ] 4a.1 `common/incident_context.py` — 사실 수집기
  - [ ] 4a.1.1 평소 기준값 — `MetricHistoryTable` 28일 p99·최대 대비 현재값 (R7-1)
  - [ ] 4a.1.2 최근 변경 — CloudTrail 이벤트 조회 (R7-2)
  - [ ] 4a.1.3 동시 발생 알람 — 관계 태그 + 시간 윈도우 (R7-3)
  - [ ] 4a.1.4 과거 발화 패턴 — `EventHistoryTable` 빈도·평균 지속시간 (R7-4)
  - [ ] 4a.1.5 임계치 변경 이력 — `threshold_at_time` 비교 (R7-5)
- [ ] 4a.2 알림 본문에 컨텍스트 첨부
- [ ] 4a.3 Inhibition 규칙 자동 생성 — 리소스 관계 태그 기반 (design.md D4)

### 4b. L1 진단 자동 실행

- [ ] 4b.1 Runbook 레지스트리 — 알람 유형 → runbook 매핑 (R8-1)
- [ ] 4b.2 SSM Automation 연동 (읽기 전용 문서만 허용)
  - [ ] 테스트: L1 실행이 리소스 상태를 변경하지 않음 (R8-3)
- [ ] 4b.3 진단 결과를 인시던트 타임라인에 첨부 (R8-2)

### 4c. AI 요약

- [ ] 4c.1 **패턴 서명 기반 캐싱** — `(리소스타입 × 메트릭 × severity)` 단위 호출 (R10-3, design.md D5)
  - [ ] 테스트: 동일 패턴 재발 시 AI 미호출
- [ ] 4c.2 프롬프트 캐싱 적용 (시스템 프롬프트·runbook 지식 고정 prefix)
- [ ] 4c.3 추정 원인 + 권장 조치 생성. **AI 없이도 4a가 동작해야 함** (R7-7)
- [ ] 4c.4 호출 수·비용 계측

### 4d. L2 / L3 조치

- [ ] 4d.1 L2 원클릭 — 승인 → 실행 → 실행자·시각·결과 기록 (R8-4·8-5)
- [ ] 4d.2 L3 자동 조치 — 대상·조건·범위 명시적 제한 + 전체 이력 (R8-6)
  - **별도 판단 필요.** 고객사 리소스를 무인 변경하므로 권한·감사·롤백 설계 선행
- [ ] 4d.3 기존 `remediation_handler`와 코드·네이밍 분리 유지 (R8-7)

---

## 착수 전 확인 사항

| # | 결정 필요 | 막는 것 |
|---|---|---|
| U5 | 크로스 리전 EventBridge 목적지 제한 | Phase 1 전체 (태스크 1.1에서 실측) |
| U2 | 채널 등록 주체 | Phase 2.2 |
| U3 | 조건(필터) 범위 | Phase 2.2 |
| U1 | 온콜의 축 | Phase 3 전체 |
| U4 | 멀티클라우드 범위 | 설계 반영은 Phase 1(스키마), 구현은 후순위 |

**즉시 착수 가능:** Phase 0 (실측) — 결정 사항과 무관하며 배포도 필요 없다.
