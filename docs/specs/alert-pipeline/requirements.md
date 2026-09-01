# Requirements — 알림 파이프라인 (수집 → 정제 → 인시던트 → 온콜 → 알림 → AIOps)

## Introduction

현재 이 시스템은 CloudWatch 알람을 **만들기만** 하고, 울린 뒤에 벌어지는 일을 전혀 다루지 않는다.
알람은 고객사 계정에 700개 단위로 생성되어 월 $71(리소스 200개 기준)의 비용이 발생하지만,
**발화해도 어디에도 도달하지 않는다**(§현재 상태 참조).

동시에 기존 관제 운영 실측(2026-09-01 대시보드)은 알림을 "보내는 것"만으로는 부족함을 보여준다:

| 지표 | 실측값 | 의미 |
|---|---|---|
| 일일 알람 총량 | **2,368건** (AWS 2,198) | 시간당 약 100건 |
| AWS High 등급 | **1,687건/일** | 전체의 71%. 시간당 70건 = 1분에 한 건 이상 |
| On-Call 수신율 (Critical) | 79% | 5건 중 1건이 미수신 |
| On-Call 수신율 (High) | **56%** | 절반 가까이가 흘러감 |
| 모니터링 SLA (5분 미만) | 84.1% | 나머지 16%는 5분 초과 |
| 장애 시 스파이크 | **20,000건대** (AWS Global LSE, AWS SSO Issue) | Slack 초당 1건 제한 시 5.5시간 소요 |

수신율 56%는 담당자의 태만이 아니라 **물리적으로 처리 불가능한 양**의 결과다.
따라서 이 기능의 1차 목표는 "알림을 잘 보내는 것"이 아니라 **보낼 가치가 있는 것만 보내는 것**이다.

### 현재 상태 — 알림이 도달하지 않는 3중 차단

`alarm_builder.py`가 모든 알람의 `AlarmActions`에 `SNS_TOPIC_ARN_ALERT`(우리 계정 us-east-1 토픽)를 넣지만:

1. **리전 불일치** — CloudWatch 알람 액션은 같은 리전 SNS만 허용. 고객사 서울 알람 → 우리 us-east-1 토픽 불가
2. **크로스 어카운트 미허가** — 토픽에 `AWS::SNS::TopicPolicy`가 없어 타 계정 CloudWatch의 발행 권한 없음
3. **구독자 0명** — 라이브 확인 결과 alert/remediation/lifecycle/error/global-alert 5개 토픽 모두 구독자 없음. 템플릿에 `AWS::SNS::Subscription` 자체가 없음

세 차단은 서로 독립이므로 하나를 고쳐도 알림은 가지 않는다.

### 현재 상태 — 채널 설정이 알람에 박혀 있어 드리프트

채널 주소를 알람 700개 각각에 적는 구조라 다음 문제가 있다:

| 경로 | AlarmActions 처리 | 결과 |
|---|---|---|
| 신규 생성 | `_get_sns_alert_arn()` 재조회 | ✅ 최신값 |
| 드리프트 재생성 | `_get_sns_alert_arn()` 재조회 | ✅ 최신값 |
| API 수정(PUT) | `alarm.get("AlarmActions", [])` — 기존값 복사 | ❌ 반영 안 됨 |
| 일일 sync 드리프트 감지 | `_CONFIG_FIELDS`에 AlarmActions 없음 | ❌ 영원히 미감지 |

또한 CloudWatch는 알람당 액션을 **최대 5개**로 제한하므로, 고객사별 다중 채널 요구를 구조적으로 수용할 수 없다.

## Glossary

- **Alarm_Event**: CloudWatch 알람의 상태 전이(및 생성/수정/삭제) 이벤트 원본
- **Incident**: 하나 이상의 Alarm_Event를 묶은 대응 단위. `triggered → acknowledged → resolved` 상태를 가진다
- **Suppression**: 알림을 보내지 않기로 하는 판단(dedup/auto-pause/inhibit/silence)
- **Grouping**: 여러 Alarm_Event를 하나의 Incident 또는 하나의 알림으로 묶는 것
- **Auto_Pause**: ALARM 수신 후 N분 대기하여 스스로 OK로 복귀하면 알리지 않는 정제 기법
- **Notification_Channel**: 고객사별 알림 목적지(Slack/Email/Webhook/PagerDuty 등) 1건
- **On_Call**: 인시던트를 받을 담당자를 시각 기준으로 결정하는 당번 체계
- **Escalation**: 무응답 시 다음 담당자로 넘기는 규칙
- **Runbook**: 특정 상황의 진단/조치 절차. L1(진단) / L2(승인 후 실행) / L3(자동 실행)로 구분
- **MTTA / MTTR**: triggered→acknowledged / triggered→resolved 소요 시간

---

## Requirements

### Requirement 1: 알람 이벤트 수집

**User Story:** As a 관제 운영자, I want 고객사 계정의 알람 발화가 우리 시스템에 도달하길 원한다, so that 알림·인시던트 처리를 시작할 수 있다.

#### Acceptance Criteria

1. WHEN 고객사 계정에서 CloudWatch 알람의 상태가 전이되면, THE 시스템 SHALL 해당 이벤트를 우리 계정에서 수신한다
2. THE 수집 경로 SHALL 알람 개수와 무관하게 동작한다 — 알람을 생성·수정·삭제해도 수집 설정을 변경하지 않는다
3. THE 수집 경로 SHALL 고객사 계정과 리전이 우리 스택과 달라도 동작한다
4. WHEN 알람이 생성·수정·삭제되면, THE 시스템 SHALL 그 이벤트도 수신하여 감사 목적으로 기록한다
5. IF 수집 경로가 일시적으로 실패하면, THEN THE 시스템 SHALL 이벤트를 유실하지 않고 재시도한다
6. THE 수집 스키마 SHALL 클라우드 중립적이어야 한다 — AWS 외 프로바이더 어댑터를 추가할 때 하위 계층을 변경하지 않는다

> **설계 주의:** 현재의 `AlarmActions` 방식은 요건 2를 구조적으로 만족할 수 없다(알람마다 주소를 박기 때문). design.md의 결정 D1 참조.

### Requirement 2: 이벤트 이력 보관

**User Story:** As a 시스템, I want 정제되기 전 원본 이벤트를 전량 보관하길 원한다, so that 나중에 정제 판단을 검증하고 AIOps 학습 데이터로 쓸 수 있다.

#### Acceptance Criteria

1. THE 시스템 SHALL 수신한 Alarm_Event를 **정제 이전에** 전량 기록한다
2. THE 기록 SHALL 고객사·계정·리전·리소스 타입·메트릭·severity·상태·타임스탬프를 포함한다
3. THE 기록 SHALL 억제된 이벤트도 억제 사유와 함께 남긴다
4. THE 기록 SHALL TTL로 보관 기간을 제한한다
5. WHEN 정제 규칙을 변경하면, THE 운영자 SHALL 과거 이벤트에 대해 그 규칙이 어떻게 동작했을지 소급 검증할 수 있다

### Requirement 3: 노이즈 정제

**User Story:** As a 온콜 담당자, I want 실제로 대응이 필요한 것만 받길 원한다, so that 수신율이 회복되고 중요한 알람을 놓치지 않는다.

#### Acceptance Criteria

1. WHEN 동일한 알람이 반복 발화하면, THE 시스템 SHALL 지정한 재알림 주기 이전에는 중복 알림을 보내지 않는다
2. WHEN ALARM 이벤트를 수신하면, THE 시스템 SHALL 설정된 유예 시간 동안 대기하고, 그 사이 OK로 복귀하면 알림을 보내지 않는다 (Auto_Pause)
3. THE Auto_Pause 유예 시간 SHALL 설정 가능해야 하며, severity별로 다르게 지정할 수 있어야 한다
4. WHEN 짧은 시간에 다수의 관련 알람이 발생하면, THE 시스템 SHALL 이를 묶어 하나의 알림으로 발송한다
5. WHEN 상위 리소스의 장애 알람이 활성 상태이면, THE 시스템 SHALL 그에 종속된 하위 리소스 알람을 억제한다 (Inhibition)
6. WHEN 운영자가 정비 시간대를 지정하면, THE 시스템 SHALL 해당 시간대의 알림을 억제한다 (Silence)
7. WHEN 특정 알람이 하루 기준치 이상 상태를 반복 토글하면, THE 시스템 SHALL 이를 flapping으로 식별하여 격리하고 리포트한다
8. THE 시스템 SHALL SEV-1 알람을 억제 대상에서 제외할 수 있어야 한다
9. THE 정제 설정 SHALL 알람을 수정하지 않고 변경 가능해야 한다

### Requirement 4: 인시던트 생명주기

**User Story:** As a 관제 운영자, I want 알람이 아니라 인시던트 단위로 대응하길 원한다, so that 누가 언제 확인했는지 추적하고 MTTA/MTTR을 측정할 수 있다.

#### Acceptance Criteria

1. WHEN 정제를 통과한 Alarm_Event가 발생하면, THE 시스템 SHALL Incident를 생성하거나 기존 Incident에 병합한다
2. THE Incident SHALL `triggered`, `acknowledged`, `resolved` 상태를 가진다
3. WHEN 담당자가 확인(ack)하면, THE 시스템 SHALL 확인 시각과 확인자를 기록하고 에스컬레이션을 중단한다
4. WHEN 원인 알람이 모두 OK로 복귀하면, THE 시스템 SHALL Incident를 자동으로 resolved 처리한다
5. THE 시스템 SHALL Incident별 MTTA(triggered→acknowledged)와 MTTR(triggered→resolved)을 산출한다
6. WHEN Incident가 acknowledged 상태로 지정 시간 이상 미해결이면, THE 시스템 SHALL 재알림한다
7. THE 시스템 SHALL Incident에 연결된 Alarm_Event 목록과 시간순 타임라인을 보존한다

### Requirement 5: 온콜 및 에스컬레이션

**User Story:** As a 관제 팀장, I want 시간대별 당번이 자동으로 결정되고 무응답 시 다음 사람에게 넘어가길 원한다, so that 새벽 인시던트가 방치되지 않는다.

> ⚠️ **미결정:** 온콜의 축이 "우리 관제팀 단일 로테이션"인지 "고객사별 개별 온콜"인지 확정되지 않았다.
> 후자면 멀티테넌트 온콜을 직접 구현해야 하며 범위가 크게 늘어난다. design.md 미결정 사항 U1 참조.

#### Acceptance Criteria

1. THE 시스템 SHALL 시각을 입력받아 현재 당번을 결정할 수 있다
2. THE 온콜 스케줄 SHALL 로테이션(주기적 교대)을 지원한다
3. THE 시스템 SHALL 특정 기간에 대한 임시 대체(오버라이드)를 지원한다
4. WHEN Incident가 생성되면, THE 시스템 SHALL 1차 담당자에게 지연 없이 통보한다
5. WHEN 1차 담당자가 지정 시간 내에 ack하지 않으면, THE 시스템 SHALL 다음 단계로 에스컬레이션한다
6. THE 에스컬레이션 정책 SHALL 단계별 대상과 대기 시간을 지정할 수 있다
7. WHEN 마지막 단계까지 무응답이면, THE 시스템 SHALL 이를 기록하고 리포트한다

### Requirement 6: 고객사별 다중 알림 채널

**User Story:** As a 고객사 담당자, I want 우리 조직의 알림을 원하는 채널들로 받길 원한다, so that 팀별·상황별로 적절한 곳에 알림이 간다.

#### Acceptance Criteria

1. THE 시스템 SHALL 고객사별로 복수의 Notification_Channel을 등록할 수 있다
2. THE Notification_Channel SHALL 최소한 Slack, Email, 범용 Webhook 유형을 지원한다
3. THE 각 채널 SHALL 조건(필터)을 가질 수 있으며, 조건에 맞는 알림만 수신한다
4. THE 조건 SHALL 최소한 severity를 기준으로 지정할 수 있다
5. WHEN 채널을 추가·변경·삭제하면, THE 시스템 SHALL **어떤 알람도 수정하지 않고** 즉시 반영한다
6. WHEN 알람을 생성·수정·삭제하면, THE 채널 설정 SHALL 영향받지 않는다
7. WHEN 채널 발송이 실패하면, THE 시스템 SHALL 재시도하고 최종 실패를 기록한다
8. THE 시스템 SHALL 채널 자격증명(Webhook URL 등)을 평문으로 노출하지 않는다
9. THE 시스템 SHALL 알람 폭풍 시 채널별 발송 속도 제한을 준수한다

> ⚠️ **미결정:** 채널 등록 주체(우리가 대행 vs 고객사 직접). 후자는 고객사 로그인·권한 체계가 선행되어야 한다. U2 참조.

### Requirement 7: 분석 정보 제공

**User Story:** As a 온콜 담당자, I want 알림에 "평소 대비 어떤지, 최근 무슨 변경이 있었는지"가 함께 오길 원한다, so that 접속해서 확인하는 단계를 건너뛸 수 있다.

#### Acceptance Criteria

1. WHEN 알림을 발송하면, THE 시스템 SHALL 해당 메트릭의 최근 기준값(평소 p99·최대)을 함께 제공한다
2. THE 시스템 SHALL 해당 리소스에 최근 발생한 변경 이벤트(CloudTrail)를 함께 제공한다
3. THE 시스템 SHALL 동시에 발생한 관련 알람을 함께 제공한다
4. THE 시스템 SHALL 해당 알람의 과거 발화 패턴(빈도·평균 지속시간)을 함께 제공한다
5. WHEN 임계치가 최근 변경되었으면, THE 시스템 SHALL 변경 사실과 시점을 함께 제공한다
6. THE 분석 정보 SHALL 근거를 제시할 수 있어야 한다 — 판단 근거를 설명할 수 없는 방식은 사용하지 않는다
7. THE AI 기반 요약 SHALL 선택적이어야 하며, 없어도 1~5는 동작한다

### Requirement 8: 조치 정보 및 실행

**User Story:** As a 온콜 담당자, I want 무엇을 해야 하는지 안내받고, 안전한 것은 자동으로 실행되길 원한다, so that 대응 시간이 단축된다.

#### Acceptance Criteria

1. THE 시스템 SHALL 알람 유형별 Runbook을 연결할 수 있다
2. WHEN Incident가 생성되면, THE 시스템 SHALL 읽기 전용 진단(L1)을 자동 실행하고 결과를 Incident에 첨부한다
3. THE L1 진단 SHALL 대상 리소스의 상태를 변경하지 않는다
4. THE 시스템 SHALL 승인 후 실행되는 조치(L2)를 제공할 수 있다
5. WHEN L2 조치를 실행하면, THE 시스템 SHALL 실행자·시각·결과를 기록한다
6. IF 자동 조치(L3)를 활성화하면, THEN THE 시스템 SHALL 대상·조건·범위를 명시적으로 제한하고 전체 이력을 남긴다
7. THE 조치 기능 SHALL 기존 `remediation_handler`(거버넌스용 리소스 정지)와 분리된 개념으로 구현한다

### Requirement 9: 측정과 리포트

**User Story:** As a 관제 팀장, I want 노이즈가 실제로 줄었는지 숫자로 보길 원한다, so that 정제 설정을 근거 있게 조정할 수 있다.

#### Acceptance Criteria

1. THE 시스템 SHALL 수신 이벤트 수 대비 발송 알림 수(억제율)를 산출한다
2. THE 시스템 SHALL 억제 사유별 건수를 산출한다
3. THE 시스템 SHALL severity별 MTTA·MTTR을 산출한다
4. THE 시스템 SHALL 발화 빈도 상위 알람·리소스·메트릭을 산출한다
5. THE 시스템 SHALL 채널별 발송 성공·실패 건수를 산출한다

### Requirement 10: 비용 제약

**User Story:** As a 서비스 소유자, I want 이 기능이 기존 운영비 규모를 크게 벗어나지 않길 원한다, so that 도입 판단이 비용에 막히지 않는다.

#### Acceptance Criteria

1. THE 시스템 SHALL 상시 구동 컴퓨트(항상 켜진 서버·컨테이너) 없이 동작한다
2. THE 시스템 SHALL 알람 이벤트당 CloudWatch 커스텀 메트릭을 발행하지 않는다 (AGENTS.md AP-24)
3. THE AI 분석 SHALL 인시던트 단위가 아니라 패턴 단위로 호출하여 호출 수를 제한한다
4. THE 시스템 전체 추가 비용 SHALL 실측 트래픽 기준 월 $50 이내여야 한다
