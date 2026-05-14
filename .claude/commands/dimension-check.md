# /dimension-check

Use this command after changing alarm dimensions or metric registry logic.

Read the recent changes in:

- `backend/common/alarm_registry.py`
- `backend/common/dimension_builder.py`

Verify:

1. Metric dimensions match AWS documentation.
2. LB-level metrics and TargetGroup-level metrics are not mixed.
3. Global service dimensions and regions are correct.
4. Compound dimensions are handled for ECS, WAF, S3, SageMaker, and related resources.
5. `treat_missing_data` is intentional for Route53, DX, MSK, and similar metrics.
