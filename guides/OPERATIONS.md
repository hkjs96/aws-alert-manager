# Operations Guide

This guide describes the repository paths used for backend deployment and test
infrastructure.

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

## Frontend Deployment

Frontend deployment is infrastructure from an ownership perspective, but hosting
tools such as Amplify may require config files to remain at the repository root
or under `frontend/`. Frontend deployment notes belong under:

```text
infrastructure/frontend/
```
