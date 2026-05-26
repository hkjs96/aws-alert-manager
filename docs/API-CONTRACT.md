# API Contract

API JSON is the stable contract between the Next.js frontend and the API Lambda.
All API fields use `snake_case` unless explicitly documented as a frontend-only
DTO.

## Common Conventions

Base URL examples:

- Amplify frontend routes call `/api/*` route handlers or API Gateway.
- API Gateway accepts `/api/*` and stage-prefixed paths.

Success responses:

```json
{"field": "value"}
```

Paginated list responses:

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 25
}
```

Error responses:

```json
{
  "code": "ERROR_CODE",
  "message": "Human readable message"
}
```

Frontend server pages must not depend on undocumented fields.

## Supported Resource Types

The backend API registry supports these 29 resource types:

```text
EC2, RDS, ALB, NLB, TG, AuroraRDS, DocDB, ElastiCache, NAT,
Lambda, VPN, APIGW, ACM, Backup, MQ, CLB, OpenSearch,
SQS, ECS, MSK, DynamoDB, CloudFront, WAF,
Route53, DX, EFS, S3, SageMaker, SNS
```

`Resource.type`, alarm `type`, threshold `{type}` path parameters, and bulk
`resource_type` must use one of these values unless the backend and frontend
constants are extended together.

The current frontend integration MVP exposes only:

```text
EC2, RDS, S3, Lambda, ALB
```

The full backend type list may appear in backend code and tests, but frontend
filters/settings should use `FRONTEND_INTEGRATION_RESOURCE_TYPES` until the
remaining resource workflows are explicitly enabled.

## GET /api/health

Response `200`:

```json
{"status": "ok"}
```

## GET /api/dashboard/stats

Query:

| Name | Type | Required |
| --- | --- | --- |
| `customer_id` | string | no |
| `account_id` | string | no |

Response `200`:

```json
{
  "monitored_count": 0,
  "active_alarms": 0,
  "unmonitored_count": 0,
  "account_count": 0
}
```

Forbidden legacy fields:

- `total_resources`
- `unmonitored_resources`
- `connected_accounts`

## GET /api/dashboard/recent-alarms

Query:

| Name | Type | Required | Default |
| --- | --- | --- | --- |
| `page` | number | no | `1` |
| `page_size` | number | no | `10`, max `50` |

Response `200`:

```json
{
  "items": [
    {
      "timestamp": "2026-05-14T00:00:00+00:00",
      "alarm_name": "alarm name",
      "resource": "resource-id",
      "type": "EC2",
      "metric": "CPUUtilization",
      "state": "ALARM",
      "threshold": 80,
      "severity": "SEV-5"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 10
}
```

## GET /api/resources

Query:

| Name | Type | Required |
| --- | --- | --- |
| `page` | number | no |
| `page_size` | number | no |
| `resource_type` | supported resource type | no |
| `search` | string | no |

Response `200`:

```json
{
  "items": [
    {
      "id": "i-123",
      "name": "i-123",
      "type": "EC2",
      "account": "123456789012",
      "region": "ap-northeast-2",
      "monitoring": true,
      "alarms": {"critical": 0, "warning": 0},
      "alarm_count": 0,
      "inventory_source": "aws",
      "persisted": true,
      "status": "active"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 25
}
```

## POST /api/resources/sync

Triggers a full discovery of AWS resources and updates the `ResourceInventory` table.

Response `200`:

```json
{
  "discovered": 10,
  "updated": 10,
  "removed": 0,
  "message": "10 resources synchronized"
}
```

## GET /api/resources/{idOrName}

`{idOrName}` may be the stable resource ID such as an EC2 instance ID, or the
display name returned by `GET /api/resources`. Frontend navigation should use
the stable `id` field.

Response `200`:

```json
{
  "id": "i-123",
  "name": "i-123",
  "type": "EC2",
  "account": "123456789012",
  "region": "ap-northeast-2",
  "monitoring": true,
  "alarms": {"critical": 1, "warning": 0},
  "alarm_count": 1,
  "inventory_source": "aws",
  "persisted": true,
  "status": "active"
}
```

Errors:

- `400 MISSING_PARAM`
- `404 NOT_FOUND`
- `500 CW_ERROR`

## GET /api/resources/{id}/alarms

Response `200`:

```json
[
  {
    "alarm_name": "alarm name",
    "metric_name": "CPUUtilization",
    "namespace": "AWS/EC2",
    "threshold": 80,
    "comparison": "GreaterThanThreshold",
    "state": "OK",
    "severity": "SEV-5",
    "monitoring": true,
    "mount_path": "/",
    "period": 300,
    "evaluation_periods": 1,
    "datapoints_to_alarm": 1,
    "treat_missing_data": "notBreaching",
    "statistic": "Average"
  }
]
```

Alarm missing-data policy:

- `treat_missing_data` is always a backend-normalized API field in alarm
  responses.
- Default policy is `notBreaching`.
- `backend/common/alarm_builder.py` applies the default when an alarm registry
  definition does not declare `treat_missing_data`.
- `backend/common/alarm_registry.py` should declare only metric-specific
  exceptions such as `breaching` or `missing`.
- Frontend code must not infer CloudWatch missing-data behavior from the
  registry field being absent. It must consume the API response field or a
  shared normalized contract.

## POST /api/resources/{id}/alarms

Request:

```json
{
  "metric_name": "CPUUtilization",
  "threshold": 80,
  "mount_path": "/",
  "severity": "SEV-5"
}
```

Response `201`:

```json
{
  "alarm_name": "alarm name",
  "metric_name": "CPUUtilization",
  "mount_path": "/"
}
```

Errors:

- `400 MISSING_PARAM`
- `404 NOT_FOUND`
- `404 NO_METRIC`
- `500 CW_ERROR`

## GET /api/resources/{id}/disk-paths

Response `200`:

```json
["/", "/data"]
```

## GET /api/resources/{id}/metrics

Response `200`:

```json
[
  {
    "namespace": "AWS/EC2",
    "metric_name": "CPUUtilization",
    "unit": "%",
    "direction": ">",
    "needs_mount_path": false
  }
]
```

## GET /api/alarms

Query:

| Name | Type | Required |
| --- | --- | --- |
| `page` | number | no |
| `page_size` | number | no |
| `state` | `ALARM`, `OK`, `INSUFFICIENT_DATA` | no |

Response `200`:

```json
{
  "items": [
    {
      "id": "alarm name",
      "alarm_name": "alarm name",
      "arn": "arn:aws:cloudwatch:...",
      "account": "123456789012",
      "resource": "i-123",
      "type": "EC2",
      "metric": "CPUUtilization",
      "mount_path": null,
      "state": "ALARM",
      "threshold": 80,
      "severity": "SEV-5",
      "time": "2026-05-14T00:00:00+00:00",
      "value": null
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 25
}
```

## GET /api/alarms/summary

Response `200`:

```json
{
  "total": 1,
  "by_state": {
    "ALARM": 1,
    "OK": 0,
    "INSUFFICIENT_DATA": 0
  },
  "alarm_count": 1,
  "ok_count": 0,
  "insufficient_count": 0
}
```

Frontend summary cards must use `total`, `alarm_count`, `ok_count`, and
`insufficient_count`.

## GET /api/customers

Response `200`:

```json
[
  {
    "customer_id": "EMU-EM2",
    "name": "EMU-EM2",
    "provider": "aws",
    "account_count": 1,
    "created_at": "2026-05-14T00:00:00+00:00"
  }
]
```

## POST /api/customers

Request:

```json
{
  "name": "Customer Name",
  "code": "CUSTOMER-ID",
  "provider": "aws"
}
```

Response `201`: Customer entity.

Errors:

- `400 INVALID_JSON`
- `400 VALIDATION_ERROR`
- `409 DUPLICATE`
- `500 DB_ERROR`

## DELETE /api/customers/{id}

Response `204` with empty body.

## GET /api/accounts

Query:

| Name | Type | Required |
| --- | --- | --- |
| `customer_id` | string | no |

Response `200`:

```json
[
  {
    "customer_id": "EMU-EM2",
    "account_id": "123456789012",
    "name": "production",
    "role_arn": "arn:aws:iam::123456789012:role/RoleName",
    "regions": ["ap-northeast-2"],
    "connection_status": "untested",
    "last_tested_at": "2026-05-14T00:00:00+00:00",
    "created_at": "2026-05-14T00:00:00+00:00"
  }
]
```

## POST /api/accounts

Request:

```json
{
  "account_id": "123456789012",
  "role_arn": "arn:aws:iam::123456789012:role/RoleName",
  "name": "production",
  "customer_id": "EMU-EM2",
  "regions": ["ap-northeast-2"]
}
```

Response `201`: Account entity.

## DELETE /api/accounts/{id}

Query:

| Name | Type | Required |
| --- | --- | --- |
| `customer_id` | string | yes |

Response `204` with empty body.

## POST /api/accounts/{id}/test

Query:

| Name | Type | Required |
| --- | --- | --- |
| `customer_id` | string | yes |

Response `200`:

```json
{
  "account_id": "123456789012",
  "status": "connected"
}
```

Failed connection response is also `200` with:

```json
{
  "account_id": "123456789012",
  "status": "failed",
  "error": "AWS error message"
}
```

## GET /api/thresholds/{type}

`{type}` must be a supported resource type.

Query:

| Name | Type | Required |
| --- | --- | --- |
| `customer_id` | string | no |

Response `200`:

```json
[
  {
    "metric_key": "CPU",
    "system_default": 80,
    "customer_override": null,
    "unit": "%",
    "direction": ">"
  }
]
```

## PUT /api/thresholds/{type}

`{type}` must be a supported resource type.

Request:

```json
{
  "customer_id": "EMU-EM2",
  "overrides": [
    {
      "metric_key": "CPU",
      "customer_override": 90
    }
  ]
}
```

Use `customer_override: null` to delete an override.

Response `200`:

```json
{
  "saved": 1,
  "resource_type": "EC2",
  "customer_id": "EMU-EM2"
}
```

## POST /api/bulk/monitoring

Current backend request shape:

```json
{
  "resource_ids": ["i-123"],
  "resource_type": "EC2",
  "monitoring": true,
  "role_arn": "arn:aws:iam::123456789012:role/RoleName",
  "resource_tags": {
    "i-123": {"Monitoring": "on"}
  }
}
```

Response `202`:

```json
{
  "job_id": "job-abc123",
  "total": 1,
  "status": "pending"
}
```

Note: `frontend/types/api.ts::BulkMonitoringRequest` currently exposes an older
shape with `action`, `thresholds`, and `custom_metrics`. This is a known
contract gap and must be resolved before relying on bulk monitoring from the UI.

## GET /api/jobs/{id}

Response `200`:

```json
{
  "job_id": "job-abc123",
  "status": "pending",
  "total_count": 1,
  "completed_count": 0,
  "failed_count": 0,
  "results": []
}
```

Errors:

- `400 BAD_REQUEST`
- `404 NOT_FOUND`
- `500 INTERNAL_ERROR`

## GET /api/monitor-runs

Returns recent DailyMonitor execution records. This is the audit trail for the
daily inventory sync and alarm reconciliation run; bulk jobs continue to use
`/api/jobs/{id}`.

Query:

- `limit`: optional, default `50`, max `100`

Response `200`:

```json
{
  "items": [
    {
      "scope": "daily_monitor",
      "started_at": "2026-05-26T00:00:00Z",
      "finished_at": "2026-05-26T00:00:12Z",
      "run_id": "daily-monitor#self#request-id",
      "account_id": "self",
      "status": "success",
      "trigger": "manual",
      "duration_ms": 12000,
      "summary": {
        "processed": 5,
        "alerts": 0,
        "alarms_created": 1,
        "alarms_updated": 0,
        "alarms_ok": 4,
        "inventory_discovered": 5,
        "inventory_synced": 5
      }
    }
  ],
  "count": 1,
  "limit": 50,
  "next_key": null
}
```

Errors:

- `500 DDB_ERROR`
