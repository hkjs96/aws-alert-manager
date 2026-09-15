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

Full checklist: `/new-collector` command (`.claude/commands/new-collector.md`).
Alarm naming/dimension rules: `docs/ALARM-RULES.md`.

When adding a resource type (one spec per type — everything else is derived; docs/specs/resource-type-registry):

1. Confirm CloudWatch metrics, namespaces, dimensions, and CloudTrail events from AWS documentation.
2. Write the spec `backend/common/resource_types/<type>.py`: alarm definitions, `lifecycle`, `rgt_filters`,
   `identity` (ARN -> TagName) when the tag cache can enumerate the type, `display`/`defaults`, and `notes` for
   every deviation. Import it in `resource_types/__init__.py` (import order = type order).
   `SUPPORTED_RESOURCE_TYPES`, `MONITORED_API_EVENTS`, the alarm_registry maps, `TAGGED_SERVICES` and the
   daily_monitor collector maps are derived from the spec — do not edit them.
3. Add the collector module under `backend/common/collectors/` on `GenericCollector`: a client factory,
   `_enumerate` (describe fallback), `_alive` (describe-based existence check), optionally `identities=`/`metrics=`
   overrides with the reason in the spec `notes`. Metrics come from the alarm definitions by default.
4. Add the CloudTrail ID extractor to `backend/remediation_handler/lambda_handler.py::_EXTRACTORS` (import fails
   loudly if it disagrees with the spec lifecycle).
5. Update `infrastructure/backend/template.yaml` CloudTrail EventPattern (a test pins it to the registry).
6. Add tests under `backend/tests/` — equivalence of the tag-cache path and the describe path, and the
   generic metrics query set (see `tests/test_generic_collector.py`).
7. Only `dimension_builder.py` still needs a hand-written branch when a type has compound dimensions.

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
