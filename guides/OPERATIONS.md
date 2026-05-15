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

Manual trigger example:

```powershell
'{"tool_input":{"file_path":"backend/common/alarm_registry.py"}}' | python .claude\deploy-backend-stack.py
```

The hook writes rebuilt zip files under `dist/` and leaves CloudFormation
`CodeVersion` pointing at the new S3 prefix after deployment.

## Test Infrastructure

Disposable validation stacks live under:

```text
infrastructure/test-stacks/
```

These stacks are for integration, E2E, and resource validation work. Do not mix
them with the deployable backend stack.

## Frontend Deployment

Frontend deployment is infrastructure from an ownership perspective, but hosting
tools such as Amplify may require config files to remain at the repository root
or under `frontend/`. Frontend deployment notes belong under:

```text
infrastructure/frontend/
```
