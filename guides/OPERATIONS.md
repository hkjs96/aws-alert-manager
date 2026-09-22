# Operations Guide

This guide describes the pre-deploy premortem checklist, and the repository paths
used for backend deployment and test infrastructure.

## 배포 전 사전 점검 (Premortem)

배포·마이그레이션·벌크 작업을 **실행하기 전에** 아래 여섯 항목에 답한다. 항목은 이 저장소에서
실제로 발생한 사고에서 역산한 것이며, 단위 테스트가 잡지 못하는 계층만 모았다.
답이 "모르겠다"인 항목이 있으면 배포하지 않고 먼저 확인한다.

1. **IAM — 새 권한이 같은 커밋에 있나?**
   새 AWS API 호출이나 새 DynamoDB 테이블/연산을 추가했다면 `infrastructure/backend/template.yaml`의
   해당 Role Policies를 같은 커밋에서 갱신했는지 확인한다 (DynamoDB는 테이블 ARN + `/index/*` 둘 다,
   CloudWatch 읽기는 `Resource: "*"`). 크로스어카운트 호출이면 **온보딩 템플릿 3곳을 동기화**한다:
   `infrastructure/customer-onboarding/template.yaml` → `frontend/public/customer-onboarding.yaml` →
   공개 S3 버킷 재업로드(`text/yaml`).
   *근거: 2026-08-31 라이브 검증에서 IAM 누락이 세 번 연속 배포 후에야 드러났다.*

2. **조용한 실패 — 이 변경이 실패하면 눈에 보이나?**
   코드가 권한 오류를 삼키고 폴백하면 기능은 "조용히 동작 안 함"으로 나타난다. 배포 후 첫 실행
   로그에서 `AccessDenied`를 grep할 계획을 세운다. API 경로라면 500이 UI에서 일반 메시지로
   은폐되지 않는지 확인한다 (AGENTS.md AP-16/AP-17 짝 규칙).

3. **리소스 변형 — 모든 변형에서 성립하나?**
   같은 타입이라도 메트릭 발행이 다르다: Aurora Serverless v2는 `FreeLocalStorage` 미발행(KI-006),
   Aurora 라이터 단독은 `AuroraReplicaLagMaximum` 미발행(KI-007), CWAgent 미설치는 Memory/Disk
   INSUFFICIENT_DATA(KI-004), Container Insights 미활성은 `ECS/ContainerInsights` 전체 미발행.
   변형별 분기가 필요하면 `resource_tags` 기반 조건부로 처리한다 (`docs/KNOWN-ISSUES.md`).

4. **영구 고착 — 되돌릴 수 있나?**
   알람 생성·재생성 경로가 태깅을 빠뜨리면 알람이 untagged로 남고, daily monitor의
   `cloudwatch:DeleteAlarms`가 `aws:ResourceTag/ManagedBy=AlarmManager` 조건부이므로 임계치 갱신·
   prune·orphan 정리가 **영구 AccessDenied로 고착**된다 (AP-18/AP-19). CFN 업데이트가 중간에
   실패했을 때의 상태도 함께 생각한다.

5. **비용 — 리소스 수에 곱해지나?**
   관리 계정 실측 베이스라인은 약 $0.35/월이다. CloudWatch 커스텀 메트릭/EMF는 **메트릭당 $0.30/월**
   이라 라우트·리소스 수만큼 곱해진다 (AP-24 — 구조화 로그 + Logs Insights를 쓴다).
   새 API 호출도 리소스 수 × 실행 주기로 곱해지는지 계산한다.

6. **태그/인벤토리 경계 — 계약이 깨지나?**
   `Monitoring` 태그가 **의도**, 인벤토리는 **관측**이다. 태그를 쓰지 않고 인벤토리만 바꾸는 경로는
   다음 reconcile에서 되돌아간다 (벌크 `/bulk/monitoring` SQS 경로가 이 함정을 가졌다).
   쓰기 경로가 태그를 갱신하는지 확인한다.

배포 후 검증은 `docs/AGENT-HARNESS-GUIDE.md`의 Evaluator Checklist를 따른다.

## Backend Deployment Stack

The deployable backend stack lives at:

```text
infrastructure/backend/template.yaml
```

Backend source packages are built from:

- `backend/common/`
- `backend/daily_monitor/`
- `backend/remediation_handler/`
- `backend/api_handler/`
- `backend/sqs_worker/`

Expected deployment artifacts:

- `common_layer.zip`
- `daily_monitor.zip`
- `remediation_handler.zip`
- `api_handler.zip`
- `sqs_worker.zip`

## Backend Lambda Auto Deploy

Claude PostToolUse hooks package and deploy backend Lambda code changes
automatically. When a Python file changes under one of these directories, the
hook builds the affected artifact, copies unchanged artifacts from the currently
deployed `CodeVersion`, uploads all artifacts to a new S3 prefix, and runs
CloudFormation deploy with `infrastructure/backend/template.yaml`.

| Changed path | Rebuilt artifact |
| --- | --- |
| `backend/common/**/*.py` | `common_layer.zip` |
| `backend/api_handler/**/*.py` | `api_handler.zip` |
| `backend/daily_monitor/**/*.py` | `daily_monitor.zip` |
| `backend/remediation_handler/**/*.py` | `remediation_handler.zip` |
| `backend/sqs_worker/**/*.py` | `sqs_worker.zip` |

Default deployment target:

```text
stack: aws-monitoring-engine-dev
bucket: bjs-deploy-bucket
profile: tlsgks678_poc
region: us-east-1
environment: development
```

Override with environment variables when needed:

```powershell
$env:ALARM_MANAGER_STACK = "aws-monitoring-engine-dev"
$env:ALARM_MANAGER_DEPLOY_BUCKET = "bjs-deploy-bucket"
$env:AWS_PROFILE = "tlsgks678_poc"
$env:AWS_REGION = "us-east-1"
$env:ALARM_MANAGER_ENVIRONMENT = "development"
```

Disable auto deploy for a local edit session:

```powershell
$env:ALARM_MANAGER_AUTO_DEPLOY = "0"
```

Manual trigger example (hook-style, stdin JSON):

```powershell
'{"tool_input":{"file_path":"backend/common/alarm_registry.py"}}' | python .claude\deploy-backend-stack.py
```

Manual CLI deploy (`scripts/deploy-backend-stack.py`, superset of the hook):

```powershell
python scripts/deploy-backend-stack.py                 # git diff 기반 변경 아티팩트만
python scripts/deploy-backend-stack.py --all-artifacts # 전체 아티팩트 재빌드
python scripts/deploy-backend-stack.py --changed-path backend/common/alarm_registry.py
python scripts/deploy-backend-stack.py --dry-run       # 배포 계획만 출력
python scripts/deploy-backend-stack.py --parameter AlertConsoleUrl=https://main.d2ssyfndl4orxp.amplifyapp.com/alerts
                                                       # 스택 파라미터 덮어쓰기(반복 가능, 나머지는 이전 값 유지)
```

The CLI also forwards auth parameters (`GOOGLE_CLIENT_ID`, `ALLOWED_EMAILS`,
`ALLOWED_EMAIL_DOMAINS`, `ADMIN_EMAILS`) when set as environment variables, and
redeploys the stack at the current `CodeVersion` when only
`infrastructure/backend/template.yaml` changed.

The hook writes rebuilt zip files under `dist/` and leaves CloudFormation
`CodeVersion` pointing at the new S3 prefix after deployment.

## Test Infrastructure

Disposable validation stacks live under:

```text
infrastructure/test-stacks/
```

These stacks are for integration, E2E, and resource validation work. Do not mix
them with the deployable backend stack.

## Alert Delivery to Slack (AWS Chatbot)

**Managed outside CloudFormation.** AWS Chatbot requires a one-time OAuth
authorization of the Slack workspace in the AWS console, which cannot be
automated, so the channel configuration is maintained by hand — like the
customer onboarding S3 bucket.

Current dev wiring (account `949501913924`):

| | |
| --- | --- |
| Workspace | `Project WS` (`T07U8210ZUN`) |
| Channel | `msu-monitoring-channel-poc` (`C0AKEPP49NF`) |
| Configuration | `arn:aws:chatbot::949501913924:chat-configuration/slack-channel/msu-monitoring-channel-poc` |
| Subscribed topics | `aws-monitoring-engine-alert-dev`, `aws-monitoring-engine-error-dev` |

The Chatbot API lives in `us-east-2` even though the topics are in `us-east-1`.

Add a topic (the list replaces, so repeat every ARN you want to keep):

```bash
aws chatbot update-slack-channel-configuration --region us-east-2 \
  --chat-configuration-arn "arn:aws:chatbot::949501913924:chat-configuration/slack-channel/msu-monitoring-channel-poc" \
  --slack-channel-id "C0AKEPP49NF" \
  --sns-topic-arns \
    "arn:aws:sns:us-east-1:949501913924:aws-monitoring-engine-alert-dev" \
    "arn:aws:sns:us-east-1:949501913924:aws-monitoring-engine-error-dev"
```

Chatbot creates and confirms the SNS subscription itself — do not subscribe a
Slack Incoming Webhook URL to a topic directly. Slack never answers the SNS
confirmation handshake, so such a subscription sits in `PendingConfirmation`
forever and delivers nothing.

Verify end to end by driving a real alarm rather than publishing a raw message
(Chatbot renders CloudWatch alarm payloads; arbitrary text may not appear):

```bash
aws cloudwatch set-alarm-state --alarm-name "<alarm>" --state-value ALARM \
  --state-reason "delivery test"
aws cloudwatch set-alarm-state --alarm-name "<alarm>" --state-value OK \
  --state-reason "test over"
# then confirm the action fired:
aws cloudwatch describe-alarm-history --alarm-name "<alarm>" --history-item-type Action
```

> `ErrorAlertTopic` carries the pipeline's **self-monitoring** alarms (ingestor
> errors and throttles, ingest DLQ, group worker errors, group execution
> failures) plus the remediation DLQ. It must never be routed through the alert
> pipeline itself — a failure there would take its own alarm down with it.

## Scheduled Runs (Daily Monitor)

| 스케줄 | 시각(UTC) | 페이로드 | 하는 일 |
|---|---|---|---|
| `daily-monitor-schedule-<env>` | 00:00 매일 | (없음) | 인벤토리 동기화 → 고아 정리 → 나열 → 알람 sync → 메트릭·임계치 알림, 런 히스토리 |
| `tag-reconcile-schedule-<env>` | 매시 30분 | `{"mode":"tag_reconcile"}` | 위에서 메트릭·임계치 알림·런 히스토리를 뺀 것 — 태그 ↔ 알람 ↔ 인벤토리 정합 |
| `metric-snapshot-schedule-<env>` | 일 15:00 | `{"mode":"metric_snapshot"}` | 주간 메트릭 통계 적재 |
| `threshold-recalibration-schedule-<env>` | 일 16:00 | `{"mode":"threshold_recalibration"}` | 임계치 재보정 제안(shadow) |

모두 EventBridge Scheduler → Orchestrator(계정 팬아웃, `mode` 전달) → Daily Monitor Worker.

> **시간 단위 태그 정합 런(2026-09-16)** — `tag-reconcile-schedule-<env>`가 매시 30분(UTC) Orchestrator에 `{"mode":"tag_reconcile"}`를 보내 계정마다 인벤토리 동기화 → 고아 정리 → 나열 → 알람 sync를 돈다. 메트릭·임계치 알림·런 히스토리는 없고 `PERF_METRIC reconcile_stage` 로그로 본다. 수동: `aws lambda invoke --function-name aws-monitoring-engine-daily-monitor-<env> --payload '{"mode":"tag_reconcile"}'`. 배경: `docs/specs/monitoring-tag-contract`.

## Frontend Deployment

Frontend deployment is infrastructure from an ownership perspective, but hosting
tools such as Amplify may require config files to remain at the repository root
or under `frontend/`. Frontend deployment notes belong under:

```text
infrastructure/frontend/
```
