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

`severity` is optional (default `SEV-5`) and must be one of `SEV-1`..`SEV-5`.
The value is written to both the alarm's `Severity` tag and the description
metadata; the alert pipeline reads the description. The same validation applies
to `configs[].severity` on the alarm update route.

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
- `400 INVALID_BODY` — malformed JSON, or `severity` outside `SEV-1`..`SEV-5`
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

Response `201`: Account entity, plus `alert_forwarding` describing whether the
account was granted `events:PutEvents` on the central alert event bus:

| Value | Meaning |
| --- | --- |
| `granted` | Bus policy updated; the account's forwarding rule can now deliver alarm events |
| `self` | The central account itself; its events arrive on the default bus, no grant needed |
| `skipped` | No alert bus configured for this deployment |
| `grant_failed` | Registration succeeded but the bus grant did not; alarm events will not arrive until it is fixed |

## DELETE /api/accounts/{id}

Query:

| Name | Type | Required |
| --- | --- | --- |
| `customer_id` | string | yes |

Response `204` with empty body. When no other customer still references the
account, its `events:PutEvents` grant on the alert event bus is removed.

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

## GET /api/alert/policy

Alert suppression policy actually in effect (env defaults merged with the stored record).

Response `200`:

```json
{
  "policy": {
    "auto_pause_sec": {},
    "repeat_interval_sec": 900,
    "exempt_severities": ["SEV-1"],
    "flapping_window_days": 1.0,
    "flapping_per_day": 3,
    "flapping_quarantine_sec": 3600,
    "group_wait_sec": 30
  },
  "source": "env",
  "updated_at": "",
  "updated_by": ""
}
```

`source` is `db` once a record exists, `env` otherwise.

## PUT /api/alert/policy

**Admin only** when `ADMIN_EMAILS` is configured — a bad policy can suppress every alert.
Omitted fields keep their current value.

Request:

```json
{
  "repeat_interval_sec": 900,
  "auto_pause_sec": { "SEV-3": 300 }
}
```

Ranges (outside → `400 VALIDATION_ERROR`):

| Field | Range |
| --- | --- |
| `repeat_interval_sec` | 0 – 86400 |
| `auto_pause_sec[*]` | 0 – 3600 |
| `flapping_quarantine_sec` | 0 – 86400 |
| `flapping_per_day` | 1 – 1000 |
| `flapping_window_days` | 0.0417 – 30 |
| `group_wait_sec` | 0 – 300 |

Response `200`: `{ "policy": { ... }, "updated_at": "2026-09-07T09:00:00Z" }`

Changes reach the ingestor within 60 seconds (config cache TTL).

## GET /api/alert/silences

Query:

| Name | Type | Required | Notes |
| --- | --- | --- | --- |
| `include_expired` | boolean | no | Default `false`. |

Response `200`:

```json
{
  "silences": [
    {
      "id": "20260907T090000-1a2b3c4d",
      "starts_at": "2026-09-07T09:00:00Z",
      "ends_at": "2026-09-07T11:00:00Z",
      "customer_id": "EMU-EM2",
      "resource_type": "",
      "reason": "DB patching",
      "created_by": "ops@example.com",
      "created_at": "2026-09-07T08:55:00Z",
      "active": true,
      "expired": false
    }
  ],
  "active": 1
}
```

## POST /api/alert/silences

Suppresses matching alerts for a window. Empty `customer_id` or `resource_type` means "all",
and a silence with no `customer_id` is global — **admin only**.

Request:

```json
{
  "starts_at": "2026-09-07T09:00:00Z",
  "ends_at": "2026-09-07T11:00:00Z",
  "customer_id": "EMU-EM2",
  "resource_type": "RDS",
  "reason": "DB patching"
}
```

`starts_at` defaults to now. `ends_at` is required, must be in the future, and the window may not
exceed 30 days — a silence that never ends deletes alerts forever.

Response `201`: the created silence (same shape as the list entry).

## DELETE /api/alert/silences/{id}

Admin only for global silences. Response `200`: `{ "id": "...", "deleted": true, "was_active": true }`.

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
