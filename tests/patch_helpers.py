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
