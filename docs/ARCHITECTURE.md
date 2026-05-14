# Architecture

This project is an AWS alarm management system with a Next.js frontend and a
serverless AWS backend.

## Runtime View

```text
Browser
  |
  | HTTPS
  v
AWS Amplify Hosting
  |
  | Next.js App Router SSR / route handlers
  v
API Gateway HTTP API
  |
  v
api_handler Lambda
  |
  +--> DynamoDB
  |     - CustomersTable
  |     - AccountsTable
  |     - ThresholdOverridesTable
  |     - JobStatusTable
  |
  +--> CloudWatch
  |     - describe/list alarms
  |     - put metric alarms
  |     - list metrics
  |
  +--> STS AssumeRole
  |     - target customer AWS accounts
  |
  +--> SQS FIFO
        - bulk monitoring jobs
```

## Main Components

| Component | Path | Responsibility |
| --- | --- | --- |
| Frontend app | `frontend/app` | Next.js pages, layouts, and route handlers. |
| Frontend data layer | `frontend/lib/server/data.ts` | Server-side API access, mock fallback, DTO shaping. |
| Client API layer | `frontend/lib/api-functions.ts` | Browser-side calls to Next route handlers or API Gateway. |
| API Lambda router | `backend/api_handler/lambda_handler.py` | Strips `/api` and stage prefixes, dispatches HTTP routes. |
| API route modules | `backend/api_handler/routes/*` | Endpoint handlers for resources, alarms, dashboard, accounts, customers, thresholds, jobs, and bulk operations. |
| Shared alarm engine | `backend/common/*` | Alarm naming, registry, builders, collectors, sync logic. |
| Scheduled monitor | `backend/daily_monitor/*` | Periodic alarm discovery and synchronization. |
| Remediation handler | `backend/remediation_handler/*` | Event-driven remediation hooks. |
| Bulk worker | `backend/sqs_worker/*` | Asynchronous SQS job processing. |
| Backend deploy stack | `infrastructure/backend/template.yaml` | Deployable AWS backend SAM/CloudFormation template. |
| Test stacks | `infrastructure/test-stacks/*` | Disposable validation stacks used for resource and integration testing. |

## Frontend Boundaries

The frontend has two data paths:

1. Server Components use `frontend/lib/server/data.ts`.
2. Client Components use `frontend/lib/api-functions.ts` or local Next route handlers under `frontend/app/api`.

Server Components must not allow routine backend failures to crash SSR pages.
Dashboard, list, and settings pages should log the error and render an empty or
zero-state fallback. Detail pages may use `notFound()` when the target resource
does not exist.

## Backend Boundaries

The API Lambda receives API Gateway HTTP API v2 events and routes by method and
path. It accepts both `/api/*` and stage-prefixed paths by normalizing them before
route matching.

All route handlers return:

```python
{"statusCode": 200, "body": json.dumps(data)}
```

Error responses must use:

```json
{"code": "ERROR_CODE", "message": "Human readable message"}
```

## Data Ownership

| Data | Owner | Storage |
| --- | --- | --- |
| Customers | Backend API | DynamoDB `CUSTOMERS_TABLE` |
| Accounts | Backend API | DynamoDB `ACCOUNTS_TABLE` |
| Threshold overrides | Backend API | DynamoDB `THRESHOLD_OVERRIDES_TABLE` |
| Bulk job status | Backend API / SQS worker | DynamoDB `JOB_STATUS_TABLE` |
| Resources | CloudWatch-derived | CloudWatch alarms and resource metadata |
| Alarms | CloudWatch-derived | CloudWatch metric alarms |
| Dashboard stats | Derived | CloudWatch plus account/customer metadata |

## Supported Resource Scope

The backend registry supports 29 AWS resource types. The current frontend
integration MVP intentionally exposes only 5 of them until those workflows are
complete end to end.

Backend authoritative code sources:

- Backend: `backend/common/__init__.py::SUPPORTED_RESOURCE_TYPES`
- Metric registry: `backend/common/alarm_registry.py`

Backend-supported types:

```text
EC2, RDS, ALB, NLB, TG, AuroraRDS, DocDB, ElastiCache, NAT,
Lambda, VPN, APIGW, ACM, Backup, MQ, CLB, OpenSearch,
SQS, ECS, MSK, DynamoDB, CloudFront, WAF,
Route53, DX, EFS, S3, SageMaker, SNS
```

Frontend active integration scope:

```text
EC2, RDS, S3, Lambda, ALB
```

Frontend authoritative code source:

- `frontend/lib/constants.ts::FRONTEND_INTEGRATION_RESOURCE_TYPES`

Do not expose additional resource types in frontend filters, settings, or
primary workflows until the corresponding backend API contract, frontend DTOs,
and tests are complete for that type.

Resource groups used by the UI:

| Group | Resource types |
| --- | --- |
| Compute | `EC2`, `Lambda`, `ECS`, `SageMaker` |
| Database | `RDS`, `AuroraRDS`, `DocDB`, `ElastiCache`, `DynamoDB` |
| Network | `ALB`, `NLB`, `CLB`, `TG`, `NAT`, `VPN`, `Route53`, `DX`, `CloudFront` |
| Storage | `S3`, `EFS`, `Backup` |
| Application/Messaging | `APIGW`, `SQS`, `MSK`, `SNS`, `MQ` |
| Security/Certificate/Search | `WAF`, `ACM`, `OpenSearch` |

## Contract Rule

API JSON is the contract between frontend and backend. API JSON and persisted
backend entities use `snake_case`. Frontend-only view models may use camelCase
only when the mapping is explicit and local to the frontend layer.

Any API field rename, deletion, or semantic change must update:

1. Backend route response.
2. Frontend TypeScript interface.
3. `docs/API-CONTRACT.md`.
4. `docs/DATA-MODEL.md` when entity fields change.
5. Contract tests.
6. Frontend normalization or fallback logic.

## Related Documents

- [API contract](API-CONTRACT.md)
- [API workflows](API-WORKFLOWS.md)
- [Data model](DATA-MODEL.md)
