# /new-collector resource onboarding checklist

Use this command when adding a backend-supported AWS resource type.

## Required Updates

1. Confirm CloudWatch metrics, namespace, dimensions, and CloudTrail events from AWS documentation.
2. Update API event mappings:
   - `backend/common/__init__.py::MONITORED_API_EVENTS`
   - `infrastructure/backend/template.yaml` CloudTrail event pattern
   - `backend/remediation_handler/lambda_handler.py::_API_MAP`
3. Register alarm defaults and resource type:
   - `backend/common/alarm_manager.py`
   - `backend/common/__init__.py::HARDCODED_DEFAULTS`
   - `backend/common/__init__.py::SUPPORTED_RESOURCE_TYPES`
4. Add or update dynamic metric namespace mappings.
5. Implement the collector under `backend/common/collectors/{type}_collector.py`.
6. Register the collector in `backend/daily_monitor/lambda_handler.py`.
7. Add tests under `backend/tests/`.
8. If the type is exposed in the frontend, update:
   - `frontend/lib/constants.ts`
   - `frontend/types`
   - `docs/API-CONTRACT.md`
   - `docs/DATA-MODEL.md`
   - `docs/API-WORKFLOWS.md`

## Verification

```bash
cd backend && pytest tests/ -x -q --tb=short
```

Do not expose a new resource type in frontend filters or settings until the
frontend API contract, DTO mapping, and tests are complete for that type.
