# API Workflows

This document describes the main frontend-to-backend flows. It is intentionally
written from the runtime boundary perspective, not from implementation details.

## Dashboard Page Load

```text
Browser
  -> Amplify Next.js SSR
  -> app/layout.tsx
  -> fetchAlarms()
  -> API Gateway GET /api/alarms?page_size=100
  -> api_handler Lambda
  -> CloudWatch list alarms / STS AssumeRole

Browser
  -> Amplify Next.js SSR
  -> app/dashboard/page.tsx
  -> Promise.all([
       GET /api/dashboard/stats,
       GET /api/alarms?page_size=100,
       GET /api/customers,
       GET /api/accounts
     ])
  -> DashboardContent client component
```

Failure policy:

- Alarm API failure must not crash the layout.
- Dashboard API failure must render zero stats and empty lists.
- Server logs must include the failed fetch context.

## Resources Page Load

```text
Browser
  -> Amplify Next.js SSR
  -> app/resources/page.tsx
  -> Promise.all([
       GET /api/resources?page_size=100,
       GET /api/customers,
       GET /api/accounts
     ])
  -> ResourcesContent client component
```

Failure policy:

- Render an empty resource list when API calls fail.
- Keep customer/account filters empty when metadata cannot load.
- Resource type filters currently use the frontend integration MVP list:
  `EC2`, `RDS`, `S3`, `Lambda`, `ALB`.
- The backend registry supports more types, but those are not exposed in primary
  frontend workflows until the end-to-end integration is complete.

## Resource Detail Load

```text
Browser
  -> Amplify Next.js SSR
  -> app/resources/[id]/page.tsx
  -> GET /api/resources/{id}
  -> GET /api/resources/{id}/alarms
  -> ResourceDetailClient
```

Failure policy:

- If the resource cannot be found, use `notFound()`.
- If secondary alarm config data fails, render the resource with empty alarm
  config rows.

## Alarms Page Load

```text
Browser
  -> Amplify Next.js SSR
  -> app/alarms/page.tsx
  -> Promise.all([
       GET /api/alarms?page_size=100,
       GET /api/alarms/summary,
       GET /api/customers,
       GET /api/accounts
     ])
  -> AlarmsContent client component
```

Failure policy:

- Render an empty alarm table and zero summary if the alarm API fails.
- Backend `AccessDenied` from CloudWatch or STS is a backend operational issue,
  not a frontend SSR failure.

## Customer Management Load

```text
Browser
  -> Amplify Next.js SSR
  -> app/customers/page.tsx
  -> Promise.all([
       GET /api/customers,
       GET /api/accounts
     ])
  -> CustomerSection / AccountSection
```

Failure policy:

- Render empty customer and account sections when DynamoDB reads fail.

## Settings Threshold Load

```text
Browser
  -> Settings page
  -> ThresholdSection client component
  -> GET /api/thresholds/{resource_type}?customer_id={customer_id}
  -> api_handler Lambda
  -> common alarm registry + ThresholdOverridesTable
```

Save flow:

```text
ThresholdSection
  -> PUT /api/thresholds/{resource_type}
  -> body: {customer_id, overrides}
  -> ThresholdOverridesTable upsert/delete
```

Threshold tabs currently use the frontend integration MVP list (`EC2`, `RDS`,
`S3`, `Lambda`, `ALB`). When expanding beyond that list, update the frontend
constant, API contract tests, and per-type metric UI together.

## Alarm Creation

```text
CreateAlarmModal
  -> POST /api/resources/{resource_id}/alarms
  -> api_handler Lambda
  -> CloudWatch list existing alarms
  -> CloudWatch list metrics / resolve dimensions
  -> CloudWatch put_metric_alarm
```

Failure policy:

- Missing required fields return `400`.
- Missing CloudWatch metric or resource returns `404`.
- CloudWatch API failures return `500` with `{code, message}`.
- Missing-data behavior is backend-normalized. The frontend must read
  `treat_missing_data` from API responses or shared contract metadata, not from
  raw registry field presence.

## Bulk Monitoring

```text
ResourcesContent bulk action
  -> POST /api/bulk/monitoring
  -> create JobStatusTable item
  -> enqueue one SQS message per resource
  -> response 202 {job_id, total, status}

Client or worker
  -> GET /api/jobs/{job_id}
  -> JobStatusTable item
```

Failure policy:

- If every SQS enqueue fails, return `500`.
- Partial enqueue failure currently returns `202`; job processing must account
  for missing work items.

## Environment Variables

Frontend server-side data reads API base URLs in this order:

1. `API_GATEWAY_URL`
2. `NEXT_PUBLIC_API_BASE_URL`
3. `API_BASE_URL`

Client-side calls use `NEXT_PUBLIC_API_BASE_URL` or local Next route handlers.

Production Amplify currently exposes `NEXT_PUBLIC_API_BASE_URL`. Do not set
empty URL values in `.env.production`; empty values can override deployment
environment variables.
