# 고객사 계정 온보딩 — 실행 가이드 (2026-09-09)

고객사 계정의 CloudWatch 알람을 우리 알림 파이프라인에 연결하는 절차.
**교차계정 배달은 아직 실측된 적이 없다** — 이 가이드의 4단계가 그 첫 검증이다.

이 문서는 `944787763707`(서울, 알람 **244개**)을 예로 쓴다. 다른 계정도 값만 바꾸면 같다.

> **2026-09-11 현황 점검:** 그 계정에는 아직 아무것도 배포돼 있지 않다(스택·역할 둘·전달 룰 전부 없음 —
> 이름 충돌 걱정 없이 깨끗하게 시작할 수 있다). 알람 244개는 **전부 서울**이고 다른 리전은 0이라
> **스택 하나면 끝난다**(아래 "여러 리전" 절은 이 계정에 해당 없음). 우리 쪽 준비는 끝나 있다:
> 템플릿 3곳 내용 일치(md5 `4052fc3d…`), S3 공개 접근 200, 원클릭 URL이 실재하는 dev 버스를 가리킨다.

---

## 0. 미리 알아둘 것

**무엇이 생기나 (고객사 계정)**

| 리소스 | 용도 | 되돌리기 |
|---|---|---|
| IAM 역할 `AlarmManagerMonitoringRole` | 중앙 계정이 AssumeRole로 리소스·알람 조회/관리 | 스택 삭제 |
| IAM 역할 `AlarmManagerMonitoringRole-AlertForward` | EventBridge가 중앙 버스로 이벤트를 보낼 때 쓰는 역할 | 스택 삭제 |
| EventBridge 룰 `alarm-manager-forward-to-central` | 알람 이벤트를 중앙 버스로 전달 | 스택 삭제 |

Lambda도 DB도 만들지 않는다. 전부 스택 삭제로 사라진다.

**무슨 일이 벌어지나**

- 그 계정 알람이 상태를 바꿀 때마다 이벤트가 우리 dev 파이프라인으로 들어온다.
  **실측(7일, 2026-09-11): 상태 전이 1,283건 = 하루 183건, 발화 에피소드로는 하루 92건.**
  추정이 아니라 그 계정의 실제 이력이다 — `docs/reports/ALARM-NOISE-944787763707-2026-09-11.md`.
- **채널을 등록하기 전까지 알림은 나가지 않는다.** 판정과 기록만 된다.
  발송까지 보려면 6단계에서 채널을 붙인다.
- 비용은 보내는 쪽(고객사) custom event 과금 — 월 약 5,500건 기준 **$0.0055**.

**소음이 한 알람에 몰려 있다.** 발화 641건 중 **451건(70%)이 알람 하나**
(`TG-AN2-HOME-DEV-INT-ALB-RE-41085 HTTPCode_Target_4XX_Count`)에서 나오고, 상위 5개가 89%다.
활동한 알람은 244개 중 30개뿐. 우리 파이프라인은 이걸 두 겹으로 잡는다 — flapping 격리(하루 3회 초과,
그 알람은 64회/일이라 즉시 걸린다)와 auto-pause. **다만 auto-pause 값은 아직 비어 있어 첫날은 격리만 작동한다.**
실측상 10분 유예를 넣으면 억제율 77%(하루 92건 → 21건)다 — 값을 넣을지는 온보딩 후 판단한다.

**리전이 중요하다.** IAM 역할은 글로벌이지만 EventBridge 룰은 리전 리소스다.
**알람이 있는 리전에 스택을 배포해야** 그 알람을 본다. `944787763707`은 서울(`ap-northeast-2`)이다.

---

## 1. 온보딩 스택 배포 (고객사 계정에서)

> ### ⚠ 자격증명부터 확인한다 — `home-dev` 프로필로는 못 한다
>
> 로컬 `home-dev`(`arn:aws:iam::944787763707:user/monitoring@megazone.com`)는 **읽기 전용**이다.
> `MonitorGroup` → `ReadOnlyAccess` + `EksManagementPolicy`뿐이라, 정책 시뮬레이션 결과 아래가 전부
> `implicitDeny`다:
>
> `cloudformation:CreateStack` · `iam:CreateRole` · `iam:PassRole` · `events:PutRule` ·
> `events:PutTargets` · `cloudwatch:PutMetricAlarm` · `cloudwatch:SetAlarmState`
>
> 즉 **1단계 배포도, 4단계 검증(알람 강제 발화)도** 이 프로필로는 AccessDenied다.
> 아래 CLI 예시의 `--profile home-dev`는 **관리자 권한이 있는 다른 자격증명으로 바꿔야 한다**
> (콘솔 로그인 + 원클릭이 가장 간단하다). 읽기 전용으로 할 수 있는 것은 조회·진단(5단계 ①③④)뿐이다.

### 원클릭 (권장)

고객사 계정으로 콘솔에 로그인한 상태에서 아래를 연다. 템플릿과 파라미터가 채워진 채 열린다.

```
https://console.aws.amazon.com/cloudformation/home?region=ap-northeast-2#/stacks/create/review?templateURL=https%3A%2F%2Falarm-manager-onboarding-949501913924.s3.amazonaws.com%2Fcustomer-onboarding.yaml&stackName=alarm-manager-onboarding&param_CentralAccountId=949501913924&param_CentralAlertBusArn=arn%3Aaws%3Aevents%3Aus-east-1%3A949501913924%3Aevent-bus%2Faws-monitoring-alert-dev
```

1. 리전이 **서울(ap-northeast-2)** 인지 확인 (URL에 들어 있지만 콘솔이 바꿔놓는 경우가 있다)
2. 하단 **"IAM 리소스 생성 승인"**(CAPABILITY_NAMED_IAM) 체크
3. **스택 생성**
4. 완료 후 **출력(Outputs)** 의 `RoleArn` 복사

### CLI

```bash
aws cloudformation deploy \
  --profile home-dev --region ap-northeast-2 \
  --template-file infrastructure/customer-onboarding/template.yaml \
  --stack-name alarm-manager-onboarding \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      CentralAccountId=949501913924 \
      CentralAlertBusArn=arn:aws:events:us-east-1:949501913924:event-bus/aws-monitoring-alert-dev

# RoleArn 확인
aws cloudformation describe-stacks \
  --profile home-dev --region ap-northeast-2 \
  --stack-name alarm-manager-onboarding \
  --query 'Stacks[0].Outputs' --output table
```

### 알람이 여러 리전에 있다면

리전마다 스택을 하나씩 만들되, **두 번째부터는 역할을 새로 만들지 않는다**(IAM은 글로벌이라 이름이 충돌한다).

```bash
aws cloudformation deploy \
  --profile home-dev --region us-east-1 \
  --template-file infrastructure/customer-onboarding/template.yaml \
  --stack-name alarm-manager-onboarding \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      CentralAccountId=949501913924 \
      CentralAlertBusArn=arn:aws:events:us-east-1:949501913924:event-bus/aws-monitoring-alert-dev \
      CreateSharedRoles=no \
      ExistingAlertForwardRoleArn=<1단계 출력의 AlertForwardRoleArn>
```

---

## 2. 앱에 계정 등록 (중앙 계정에서 — 내가 함)

화면: **Customers → 계정 등록**. 필요한 값 네 개.

| 필드 | 값 |
|---|---|
| `account_id` | `944787763707` |
| `role_arn` | 1단계 출력의 `RoleArn` |
| `name` | 아무 표시 이름 (예: `메가존 모니터링`) |
| `customer_id` | 기존 고객사 ID (예: `EMU-EM2`) 또는 새로 만든 것 |
| `regions` | `["ap-northeast-2"]` |

**등록이 곧 권한 부여다.** 저장하는 순간 중앙 이벤트 버스 정책에 그 계정을 허용하는 문장이
자동으로 추가된다(`Sid = acct-944787763707`). 응답의 `alert_forwarding` 값을 반드시 확인한다.

| 값 | 뜻 |
|---|---|
| `granted` | 정상 — 버스 정책에 들어갔다 |
| `grant_failed` | **이벤트가 안 들어온다.** 계정 ID 오타이거나 권한 문제. 로그 확인 |
| `self` | 우리 계정 자신 — 교차계정 정책 불필요 |
| `skipped` | 버스 이름 환경변수가 없다(설정 오류) |

---

## 3. 연결 확인 (AssumeRole 경로)

화면의 계정 목록에서 **연결 테스트**를 누른다. 또는:

```
POST /api/accounts/944787763707/test?customer_id=<고객사ID>
```

이건 **AssumeRole 경로만** 본다. 알람 이벤트 전달과는 별개다 — 여기서 성공해도 4단계는 따로 확인해야 한다.

---

## 4. 알람 이벤트 도달 확인 ★ 이게 진짜 검증

고객사 계정에서 알람 하나를 강제로 울린다. **기존 알람을 건드리기보다 임시 알람을 만드는 편이 안전하다.**

> 이 두 명령(`put-metric-alarm`·`set-alarm-state`)도 읽기 전용 자격증명으로는 안 된다(1단계 경고 참고).
> 배포에 쓴 것과 같은 관리자 자격증명으로 실행한다.

```bash
# 고객사 계정, 서울 리전
aws cloudwatch put-metric-alarm \
  --profile home-dev --region ap-northeast-2 \
  --alarm-name "[TEST] onboarding-check" \
  --namespace AWS/EC2 --metric-name CPUUtilization \
  --dimensions Name=InstanceId,Value=i-onboardingtest \
  --statistic Average --period 60 --evaluation-periods 1 \
  --threshold 80 --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching

aws cloudwatch set-alarm-state \
  --profile home-dev --region ap-northeast-2 \
  --alarm-name "[TEST] onboarding-check" \
  --state-value ALARM --state-reason "onboarding verification"
```

**1분 안에** 우리 화면 `/alerts`(알림 처리 내역)에 그 알람이 나타나야 한다.
API로 보려면:

```
GET /api/alert/events?days=1&limit=200
```

`resource_id`가 `i-onboardingtest`인 행이 있으면 **교차계정 배달 성공**이다.

확인 후 정리:

```bash
aws cloudwatch delete-alarms --profile home-dev --region ap-northeast-2 \
  --alarm-names "[TEST] onboarding-check"
```

---

## 5. 안 들어올 때 — 순서대로 짚는다

교차계정 전달은 **양쪽이 다 맞아야** 동작한다. 한쪽만 봐서는 원인을 못 찾는다.

**① 고객사 룰이 실패하고 있나** (고객사 계정, 서울)

```bash
aws cloudwatch get-metric-statistics \
  --profile home-dev --region ap-northeast-2 \
  --namespace AWS/Events --metric-name FailedInvocations \
  --dimensions Name=RuleName,Value=alarm-manager-forward-to-central \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 --statistics Sum
```

값이 있으면 **우리 버스가 거부한 것**이다 → ②로.
값이 0이고 `Invocations`도 0이면 룰이 이벤트를 못 본 것 → **리전이 맞는지** 확인.

**② 버스 정책에 그 계정이 있나** (중앙 계정)

```bash
aws events describe-event-bus --name aws-monitoring-alert-dev \
  --profile tlsgks678_poc --region us-east-1 --query Policy --output text
```

`acct-944787763707` Sid가 있어야 한다. 없으면 2단계의 `alert_forwarding`이 `granted`가 아니었다는 뜻이거나,
거의 동시에 다른 계정을 등록하다 덮어쓰인 것이다. **매시간 자동 점검**(`AlertForwardingReconcileRule`)이 빠진
Sid를 다시 붙이지만, 기다리지 말고 관리자 계정으로 정합성 점검을 바로 부른다 —
`POST /api/accounts/alert-forwarding/reconcile` (응답의 `added`에 그 Sid가 보여야 한다). 그래도 없으면
계정을 지웠다 다시 등록한다.

> **조건이 걸려 있다.** 정책은 `events:source = aws.cloudwatch`이고 detail-type이
> 알람 상태/구성 변경 2종일 때만 허용한다. 고객사 룰이 그보다 넓은 이벤트를 보내면 거부된다.

**③ 인제스터까지 왔나** (중앙 계정)

```bash
aws logs filter-log-events \
  --log-group-name /aws/lambda/aws-monitoring-engine-alert-ingestor-dev \
  --filter-pattern "944787763707" \
  --start-time $(( ($(date +%s) - 3600) * 1000 )) \
  --profile tlsgks678_poc --region us-east-1 --query 'length(events)'
```

**④ 아무 데도 안 쌓였나 — DLQ 확인**

```bash
aws sqs get-queue-attributes \
  --queue-url $(aws sqs get-queue-url --queue-name aws-monitoring-alert-ingest-dlq-dev \
      --profile tlsgks678_poc --region us-east-1 --query QueueUrl --output text) \
  --attribute-names ApproximateNumberOfMessagesVisible \
  --profile tlsgks678_poc --region us-east-1
```

여기 쌓였다면 이벤트는 도착했는데 인제스터가 처리에 실패한 것이다.

---

## 6. (선택) 알림까지 받기

여기까지는 판정·기록만 된다. 실제로 Slack을 받으려면 채널을 등록한다.

**Settings → 알림 채널 → 채널 추가**

- 고객사: 2단계에서 쓴 `customer_id`
- 유형: Slack
- Webhook URL: Slack Incoming Webhook
- 조건: 비워 두면 그 고객사의 모든 알림. 좁히려면 등급·리소스 타입·계정으로.

등록 후 4단계를 다시 하면 Slack에 메시지가 온다.

> 처음에는 **조건을 좁혀서** 시작하는 편이 낫다. 실측상 발화가 하루 92건이고 그중 70%가 알람 하나에서
> 나오는 계정이다. flapping 격리가 그 하나를 첫날 안에 잡지만(하루 3회 초과 기준, 그 알람은 64회/일),
> 격리가 걸리기 전 몇 건은 나간다. 예: 등급 `SEV-1`, `SEV-2`만.

---

## 7. 되돌리기

```bash
# 고객사 계정 — 리소스 전부 삭제
aws cloudformation delete-stack --profile home-dev --region ap-northeast-2 \
  --stack-name alarm-manager-onboarding
```

앱에서 계정을 삭제하면 버스 정책의 그 계정 문장도 자동으로 회수된다
(다른 고객사가 같은 계정을 쓰고 있으면 남긴다).

---

## 부록: 온보딩 후 첫 주에 볼 것

| 무엇 | 어디 |
|---|---|
| 하루 몇 건 들어오는가 | `/alerts` 화면의 요약, 또는 `scripts/alert_suppression_report.py --days 7` |
| 억제가 얼마나 되는가 | 같은 리포트의 억제율 — 이 값이 **자동 유예 기본값을 정하는 근거**다 |
| 이벤트가 새는가 | DLQ 알람(`[AlertIngestDLQ]`)이 Slack으로 온다. 비어 있어야 정상 |
| 인제스터가 버거운가 | `[AlertIngestor] 예약 동시성 초과` 알람 |

**Phase 0 실측은 온보딩을 기다릴 필요가 없다.** `scripts/analyze_alarm_history.py`는 `DescribeAlarms`·
`DescribeAlarmHistory`만 쓰는 **읽기 전용**이라 읽기 권한만 있으면 지금 돌아간다 — 실제로 `home-dev`
프로필로 돌려 `docs/reports/ALARM-NOISE-944787763707-2026-09-11.md`를 뽑았다(CloudWatch가 알람 이력을
2주 보관하므로 그 이상은 못 본다).

```bash
AWS_PROFILE=home-dev python scripts/analyze_alarm_history.py --days 7 --region ap-northeast-2
```

온보딩 **후에** 보는 것은 다른 질문이다 — "우리 정제가 실제로 얼마나 걸렀나"(`alert_suppression_report.py`).
실측 억제율 후보와 비교하면 정제 로직이 예측대로 도는지 알 수 있다.
