# Backend Python Guide

These rules apply to Python backend work under `backend/`.

## Paths

- Shared code: `backend/common/`
- API routes: `backend/api_handler/`
- Scheduled monitor: `backend/daily_monitor/`
- Remediation handler: `backend/remediation_handler/`
- SQS worker: `backend/sqs_worker/`
- Backend tests: `backend/tests/`
- Backend deploy template: `infrastructure/backend/template.yaml`

## Resource Onboarding

Full checklist (SSOT): `docs/RESOURCE-ONBOARDING.md` — read it before adding or
changing a resource type. Alarm naming/dimension rules: `docs/ALARM-RULES.md`.
Anti-pattern list: root `AGENTS.md` §5.

One spec per type; everything else is derived (`SUPPORTED_RESOURCE_TYPES`,
`MONITORED_API_EVENTS`, the alarm_registry maps, `TAGGED_SERVICES`, the daily_monitor
collector maps) — do not edit derived maps. The checklist above is the only place that
lists the edit points.

> **URL 식별자(중요):** 새 리소스의 `resource_id`가 ARN처럼 `/`·`:`를 포함해도
> **추가 작업은 필요 없다.** 프론트 `encodeResourceId`/백엔드 `_decode_resource_token`
> (`_path_id` 자동 적용)이 base64url 토큰으로 처리하며 **타입 무관**이다.
> 단, `resource_id`를 URL/API path에 raw로 넣는 코드를 새로 만들지 말 것
> (루트 `AGENTS.md` AP-6, `backend/AGENTS.md` §5).

## Test Command

```bash
cd backend && pytest tests/ -x -q --tb=short
```

Test files use `backend/tests/test_{module_name}.py`; property tests use
`backend/tests/test_pbt_{property_name}.py`.
