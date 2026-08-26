"""
공유 패치 헬퍼 — conftest.py 및 개별 테스트 파일에서 import하여 사용.

conftest.py는 pytest가 자동 로드하지만 직접 import할 수 없으므로,
재사용 가능한 헬퍼는 이 모듈로 분리한다.
"""

from contextlib import ExitStack
from unittest.mock import patch

_ALL_COLLECTORS = (
    "ec2", "rds", "elb", "docdb", "elasticache", "natgw", "lambda_fn",
    "vpn", "apigw", "acm", "backup", "mq", "clb", "opensearch",
    "sqs", "ecs", "msk", "dynamodb", "cloudfront", "waf",
    "route53", "dx", "efs", "s3", "sagemaker", "sns",
)


def patch_infra_stages():
    """lambda_handler의 0단계(orphan cleanup)와 1단계(alarm sync)를 mock.

    테스트가 2단계(메트릭 조회 + 알림 발송) 로직만 검증할 때 사용.
    ExitStack 컨텍스트 매니저로 반환하므로 ``with patch_infra_stages():`` 형태로 사용.
    """
    stack = ExitStack()
    stack.enter_context(
        patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[])
    )
    stack.enter_context(
        patch("daily_monitor.lambda_handler.sync_alarms_for_resource", return_value={})
    )
    return stack


def patch_all_collectors(**overrides):
    """모든 collector.collect_monitored_resources()를 mock.

    overrides에 ``{module}_resources=[...]`` 형태로 리소스 목록 지정 가능.
    명시되지 않은 collector는 빈 리스트([])를 반환.

    Example::

        with patch_all_collectors(ec2_resources=[my_ec2]):
            result = handler({}, MagicMock())
    """
    stack = ExitStack()
    for mod in _ALL_COLLECTORS:
        resources = overrides.get(f"{mod}_resources", [])
        stack.enter_context(
            patch(
                f"common.collectors.{mod}.collect_monitored_resources",
                return_value=resources,
            )
        )
    return stack


def alarm_config_fields(
    resource_type: str,
    cw_metric_name: str,
    resource_tags: dict | None = None,
) -> dict:
    """레지스트리 정의 기준으로 describe_alarms가 돌려줄 설정 필드를 만든다.

    실제 CloudWatch 응답에는 Statistic/Period/EvaluationPeriods/ComparisonOperator/
    TreatMissingData가 항상 들어 있다. 픽스처가 이를 빠뜨리면 alarm_sync가 설정
    드리프트로 오인해 멀쩡한 알람을 재생성 대상으로 잡는다.
    """
    from common.alarm_registry import _get_alarm_defs

    defs = _get_alarm_defs(resource_type, resource_tags or {})
    match = next(
        (d for d in defs if (d.get("metric_name") or d["metric"]) == cw_metric_name),
        None,
    )
    if match is None:
        return {}
    return {
        "Statistic": match["stat"],
        "Period": match["period"],
        "EvaluationPeriods": match["evaluation_periods"],
        "ComparisonOperator": match["comparison"],
        "TreatMissingData": match.get("treat_missing_data", "notBreaching"),
    }
