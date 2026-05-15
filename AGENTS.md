# Agent Rules

This file is the shared rulebook for any AI agent working in this repository,
including Codex, Claude, Gemini, and similar tools.

## Read First

Before making non-trivial changes, read the relevant files:

- `docs/ARCHITECTURE.md`
- `docs/API-CONTRACT.md`
- `docs/DATA-MODEL.md`
- `docs/API-WORKFLOWS.md`
- `docs/INFRASTRUCTURE.md`
- `guides/OPERATIONS.md`

For frontend work, also read:

- `frontend/CLAUDE.md`
- `frontend/lib/constants.ts`

For backend alarm engine work, also read:

- `backend/common/CLAUDE.md`
- `backend/common/alarm_registry.py`
- `backend/common/alarm_builder.py`

## Core Rules

- Keep changes scoped to the requested behavior.
- Do not revert unrelated user or agent changes.
- Keep commits small and behaviorally coherent.
- Prefer existing local patterns over new abstractions.
- Do not hide backend contract problems with frontend mock fallbacks.
- Run focused tests for the changed area before finishing.

## Frontend-Backend Contract

API JSON is a project-level contract. Any change to request payloads, response
fields, entity fields, or field semantics must update all related artifacts in
the same change:

1. Backend route handler request/response handling.
2. Frontend TypeScript interfaces in `frontend/types`.
3. API documentation in `docs/API-CONTRACT.md`.
4. Entity documentation in `docs/DATA-MODEL.md` when model fields change.
5. Workflow documentation in `docs/API-WORKFLOWS.md` when call flows change.
6. Contract tests or route tests.
7. Frontend normalization/fallback logic in `frontend/lib/server/data.ts` or
   `frontend/lib/api-functions.ts`.

Rules:

- API JSON and backend persistence fields use `snake_case`.
- Frontend-only view DTOs may use camelCase only with explicit mapping.
- Do not introduce alternate names for the same concept.
- Do not use legacy fallback fields.
- Server-rendered frontend pages must not turn routine backend API failures into
  Amplify/Next.js 500 pages. List and dashboard pages render safe empty or
  zero-state fallback data and log the backend failure.

## Resource Inventory Rule

`/api/resources` must represent AWS resource inventory with alarm state overlaid
onto it. CloudWatch alarms are not the source of truth for resource existence.

Required model:

- AWS resource discovery is the source of truth for active resources.
- DynamoDB is an inventory cache and operational metadata store.
- CloudWatch alarms are an overlay for `monitoring`, `alarm_count`, and alarm
  severity counts.
- AWS resources without alarms must still appear in `/api/resources`.
- DynamoDB records missing from AWS discovery should become `stale` or
  `missing`, not be deleted immediately.
- Alarms without a matching AWS resource are orphan alarm candidates.

## Repository Boundaries

- Backend application code lives under `backend/`.
- Deployable backend infrastructure lives under `infrastructure/backend/`.
- Disposable validation or experiment stacks live under
  `infrastructure/test-stacks/`.
- Frontend deployment documentation and frontend infra notes live under
  `infrastructure/frontend/`.
- Tool-required frontend deployment files may remain at the repository root or
  under `frontend/` when the hosting tool requires that location.

## Backend Deployment Rule

Backend Lambda code changes are not complete until the deployed stack uses the
new artifact version.

For Python changes under these paths, package and deploy the matching artifact:

- `backend/common/**/*.py` -> `common_layer.zip`
- `backend/api_handler/**/*.py` -> `api_handler.zip`
- `backend/daily_monitor/**/*.py` -> `daily_monitor.zip`
- `backend/remediation_handler/**/*.py` -> `remediation_handler.zip`
- `backend/sqs_worker/**/*.py` -> `sqs_worker.zip`

The standard deploy flow is:

1. Build changed zip artifact(s).
2. Upload to the deploy S3 bucket under a new `CodeVersion` prefix.
3. Copy unchanged artifacts from the previously deployed `CodeVersion`.
4. Deploy `infrastructure/backend/template.yaml`.
5. Confirm CloudFormation `UPDATE_COMPLETE`.
6. Confirm affected Lambda functions reference the expected artifact or layer.

The Claude/Codex hook in `.claude/deploy-backend-stack.py` automates this when
enabled. See `guides/OPERATIONS.md`.

## Verification

Use focused verification first:

- Backend: run relevant `pytest` tests from `backend/`.
- Frontend: run `npx tsc --noEmit` from `frontend/`.
- Contract changes: update and run route/API tests plus affected frontend tests.
- Infrastructure changes: run CloudFormation validation and confirm deployed
  stack status when deployment is requested.

Record any command that could not be run and why.
