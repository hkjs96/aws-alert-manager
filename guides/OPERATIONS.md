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

## API Handler Fast Deploy

When only API handler code changes, the Claude hook can package and deploy just
the API handler artifact:

```powershell
'{"tool_input":{"file_path":"backend/api_handler/lambda_handler.py"}}' | python .claude\deploy-api-handler.py
```

The hook packages `backend/api_handler`, uploads `dist/api_handler.zip`, copies
unchanged artifacts from the previous deployment version, then runs
CloudFormation deploy with `infrastructure/backend/template.yaml`.

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
