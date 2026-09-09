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
account was granted `events:PutEvents` on the central alert event bus (restricted to
CloudWatch alarm events by an `events:source` / `events:detail-type` condition):

| Value | Meaning |
| --- | --- |
| `granted` | Bus policy updated; the account's forwarding rule can now deliver alarm events |
| `self` | The central account itself; its events arrive on the default bus, no grant needed |
| `skipped` | No alert bus configured for this deployment |
| `grant_failed` | Registration succeeded but the bus grant did not; alarm events will not arrive until it is fixed. A non-existent `account_id` lands here: the bus policy rejects an unknown principal. |

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

## GET /api/alert/incidents

Query: `customer_id`(선택), `status`(선택), `limit`(기본 50, 최대 200).

```json
{
  "incidents": [
    { "incident_id": "inc-...", "customer_id": "EMU-EM2", "severity": "SEV-2",
      "status": "acknowledged", "title": "[EC2] i-1 CPU > 80%",
      "triggered_at": "...", "acknowledged_at": "...", "acknowledged_by": "oncall@mz.co.kr",
      "members": ["111#i-1#CPU"], "timeline": [{"at": "...", "kind": "alarm", "detail": "..."}],
      "mtta_sec": 180, "event_count": 4, "is_open": true }
  ],
  "summary": { "total": 2, "by_status": {"acknowledged": 1, "resolved": 1},
               "acknowledged_count": 2, "resolved_count": 1,
               "mtta_sec_avg": 180.0, "mttr_sec_avg": 600.0 },
  "truncated": false, "limit": 50
}
```

`summary`는 필터 적용 후·건수 제한 전 값이다. MTTA/MTTR 평균은 각각 확인·해소된 건만 분모에 넣는다.

## GET /api/alert/incidents/{id}

Response `200`: 위 항목 하나(타임라인 포함). `404 NOT_FOUND`.

## POST /api/alert/incidents/{id}/ack

확인 처리 (R4-3). **확인자는 로그인 신원에서 온다** — 본문으로 받지 않는다.
이미 확인된 건은 `200`으로 현재 상태를 그대로 돌려준다(첫 확인자·시각 유지).
사람이 버튼을 두 번 눌렀다고 오류를 볼 이유는 없고, 덮어쓰면 MTTA가 거짓이 된다.

저장은 읽은 `version`일 때만 들어간다(낙관적 잠금). 라우터가 같은 순간 발화를 합치고 있으면 다시
읽어 그 위에 확인을 얹는다(최대 3회). 계속 겹치면 `409 CONFLICT` — 잠시 후 다시 누르면 된다.
응답의 `version`은 저장된 버전이다.

Errors: `404 NOT_FOUND`, `409 ALREADY_RESOLVED`, `409 CONFLICT`, `503 STORAGE_ERROR`

## GET /api/alert/channel-types

채널 유형 카탈로그. 설정 화면은 이 응답으로 폼을 그린다 — 어댑터를 추가하면 화면이 따라온다.

```json
{
  "types": [
    { "type": "slack", "label": "Slack", "rate_limit_per_sec": 1.0,
      "fields": [{ "name": "webhook_url", "label": "Webhook URL",
                   "required": true, "secret": true, "max_len": 1024 }] }
  ],
  "match_fields": ["severity", "resource_type", "account_id"],
  "severities": ["SEV-1", "SEV-2", "SEV-3", "SEV-4", "SEV-5"]
}
```

값이 아니라 **필드의 모양만** 준다. 저장된 자격증명은 여기에도 나오지 않는다.

## GET /api/alert/channels

Query: `customer_id` (선택). 주면 그 고객사 채널 **+ 전역 채널**을 함께 준다 — 전역 채널도
그 고객사에 적용되기 때문이다. 없으면 전부.

## POST /api/alert/channels

```json
{
  "name": "운영팀 슬랙", "type": "slack", "customer_id": "EMU-EM2",
  "config": { "webhook_url": "https://hooks.slack.com/services/..." },
  "match": { "severity": ["SEV-1", "SEV-2"], "resource_type": ["RDS"] },
  "enabled": true
}
```

- `customer_id`를 비우면 **전역 채널**(모든 고객사의 알림)이며 **관리자 전용**이다.
  전역 정비창과 같은 폭발 반경이라 같은 기준을 적용한다.
- `match`는 축마다 목록이고 **비면 전부**다. 축끼리 AND, 축 안의 값끼리 OR.
  모르는 축과 모르는 `config` 항목은 400 — 조용히 버리면 "RDS만"이라 믿는데 전부 받는다.
- 고객사당 최대 50개.

Response `201`: 채널 표현. **`config`의 자격증명 필드는 값 대신 `"(설정됨)"`이 나간다.**

## PUT /api/alert/channels/{id}

Query: `customer_id`. 자격증명을 **보내지 않거나 `"(설정됨)"` 그대로 보내면 저장된 값이
유지된다** — 화면은 값을 모르므로, 이름만 고쳤는데 발송이 멈추면 안 된다. 새 값을 보내면 교체.

## DELETE /api/alert/channels/{id}

Query: `customer_id`. Response `204`.

Errors (채널 공통): `400 VALIDATION_ERROR`, `400 LIMIT_EXCEEDED`, `403 FORBIDDEN`,
`404 NOT_FOUND`, `503 STORAGE_ERROR`

## GET /api/alert/events

알람마다 알림을 보냈는지, 보내지 않았다면 왜인지. 화면은 이 응답의 라벨을 그대로 쓴다 —
사유 문구의 정본은 백엔드(`common/alert_verdict.py`)다.

Query:

| Name | Type | Default | Notes |
| --- | --- | --- | --- |
| `days` | int | 1 | 1–14로 잘린다 |
| `customer_id` | string | - | 없으면 등록된 고객사 전부 + 매핑 없는 파티션 |
| `resource_id` | string | - | |
| `action` | string | - | `notify` / `suppress` / `pending` |
| `limit` | int | 100 | 1–500 |

Response `200`:

```json
{
  "events": [
    {
      "occurred_at": "2026-09-08T08:01:00Z",
      "series_id": "111122223333#i-1#CPUUtilization",
      "alarm_name": "[EC2] web CPUUtilization > 80% (TagName: i-1)",
      "resource_id": "i-1", "resource_type": "EC2", "metric_key": "CPUUtilization",
      "severity": "SEV-3", "state": "ALARM", "previous_state": "OK", "kind": "firing",
      "action": "suppress", "action_label": "억제",
      "reason": "dedup", "reason_label": "중복 병합",
      "explanation": "같은 알람을 최근에 이미 알렸습니다. ...",
      "suppressed": true, "finalized": false,
      "quarantined_until": "2026-09-08T12:00:00Z"
    }
  ],
  "summary": {
    "total": 5, "notify": 1, "suppress": 4, "pending": 0, "config": 0,
    "suppression_rate": 0.8
  },
  "days": 1, "truncated": false, "limit": 100
}
```

- `action`은 최종 판정이다: 그룹 실행이 확정한 `final_action`이 적재 시점 판정을 이기고,
  유예(auto_pause) 중이라 아직 확정되지 않은 건은 `pending`이다.
- `summary`는 필터 적용 후·건수 제한 전 값이다. `truncated`가 `true`여도 요약은 전체를 센다.
- `suppression_rate`의 분모는 확정된 건(`notify + suppress`)이며 `pending`은 제외한다.
- `quarantined_until`은 진동 격리된 건에만 있다.

Errors: `400 VALIDATION_ERROR`, `503 STORAGE_ERROR`, `503 NOT_CONFIGURED`

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
