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

When adding a resource type:

1. Confirm CloudWatch metrics, namespaces, dimensions, and CloudTrail events from AWS documentation.
2. Update `backend/common/__init__.py::SUPPORTED_RESOURCE_TYPES`.
3. Update registry and dimension logic in `backend/common/alarm_registry.py` and `backend/common/dimension_builder.py`.
4. Add or update collectors under `backend/common/collectors/`.
5. Register scheduled collection in `backend/daily_monitor/lambda_handler.py`.
6. Register remediation events in `backend/remediation_handler/lambda_handler.py`.
7. Update `infrastructure/backend/template.yaml` if CloudTrail event patterns change.
8. Add tests under `backend/tests/`.

## Test Command

```bash
cd backend && pytest tests/ -x -q --tb=short
```

Test files use `backend/tests/test_{module_name}.py`; property tests use
`backend/tests/test_pbt_{property_name}.py`.
