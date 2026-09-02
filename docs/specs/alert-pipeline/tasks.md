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

### 1.1 EventBridge 경로 검증 (선행 — design.md U5)

- [ ] 1.1.1 dev 계정 서울 리전에 테스트 알람 생성 → 상태 전이 발생
- [ ] 1.1.2 서울 기본 버스 → us-east-1 우리 버스 크로스 리전 포워딩 룰 구성
- [ ] 1.1.3 **이벤트가 실제로 도달하는지 확인** — 목적지 리전 제한 여부 판정
  - 실패 시: 리전별 우리 버스를 두는 대안으로 전환하고 design.md D1 갱신
- [ ] 1.1.4 알람 **생성/수정/삭제** 이벤트도 수신되는지 확인 (R1-4)
- [ ] 1.1.5 테스트 알람·룰 정리

### 1.2 인프라

- [ ] 1.2.1 우리 계정 커스텀 이벤트 버스 + 버스 정책(고객사 계정 허용) — CFN
- [ ] 1.2.2 고객사 온보딩 템플릿에 EventBridge 룰 + 전달 역할 추가
  - 온보딩 템플릿 3곳 동기화 (`infrastructure/customer-onboarding/` → `frontend/public/` → 공개 S3, `text/yaml`)
- [ ] 1.2.3 `EventHistoryTable` — PK/SK 설계, TTL, GSI(고객사·시간 조회용)
- [ ] 1.2.4 워커 IAM 및 배포 검증 (`/new-collector` IAM 체크 절차 준용 — 배포 후 `AccessDenied` grep)

### 1.3 수집·정규화

- [ ] 1.3.1 `common/alert_event.py` — 클라우드 중립 이벤트 스키마 정의 (R1-6)
  - [ ] 테스트: CloudWatch 이벤트 → 정규화 스키마 변환
- [ ] 1.3.2 정규화 Lambda — 이벤트 수신 → 스키마 변환 → 이력 기록
  - [ ] 테스트: 알 수 없는 형태의 이벤트를 버리지 않고 기록
- [ ] 1.3.3 `alarm_identity.identify_alarm()`으로 리소스 해석 (기존 모듈 재사용)
- [ ] 1.3.4 **정제 이전에** 원본 전량 기록 (R2-1)
  - [ ] 테스트: 억제된 이벤트도 억제 사유와 함께 기록됨 (R2-3)

### 1.4 정제 엔진

- [ ] 1.4.1 `common/alert_suppression.py` — 순수 함수로 판정 로직 구현
  - [ ] 테스트: dedup — 동일 fingerprint 반복 시 repeat_interval 이전엔 미발송
  - [ ] 테스트: SEV-1은 억제 제외 (R3-8)
- [ ] 1.4.2 Auto-pause — Step Functions Wait 기반
  - [ ] 테스트: 유예 중 OK 수신 시 미발송
  - [ ] 테스트: 유예 후에도 ALARM이면 발송
  - [ ] 테스트: severity별 유예 시간 적용 (R3-3)
- [ ] 1.4.3 Grouping — `group_wait` 내 도착 이벤트 병합
  - [ ] 테스트: group_by 축이 같은 이벤트가 1건으로 묶임
- [ ] 1.4.4 Silence / 정비창
  - [ ] 테스트: 정비 시간대 이벤트 억제, 종료 후 정상화
- [ ] 1.4.5 Flapping 식별 + 격리 + 리포트 (R3-7)
- [ ] 1.4.6 정제 설정을 DB에서 읽기 (R3-9 — 알람 무수정 변경)

### 1.5 측정

- [ ] 1.5.1 억제율·억제 사유별 건수 계측 (`perf_log` 규약 사용, R9-1·9-2)
- [ ] 1.5.2 `docs/OBSERVABILITY.md`에 조회 쿼리 추가

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
- [ ] 2.2.2 SSM Parameter Store SecureString 연동 — Webhook URL 등 자격증명 분리 (R6-8, design.md **D7**)
  - 표에는 `secret_ref` 경로만, 값은 `/alarm-manager/channels/{customer}/{channel}`
  - 라우터 Lambda에만 `ssm:GetParameter` 부여, 경로 접두사로 제한
  - [ ] 테스트: 채널 목록 응답에 자격증명 값이 포함되지 않음
    - `api_handler`에 `scan_all` 결과를 화이트리스트 없이 응답에 넣는 코드가 12곳 있다 —
      채널 표가 같은 관례를 따라도 유출되지 않아야 한다
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
