"""common.resource_discovery 디스커버리 함수 단위 테스트.

LB(ALB/NLB), TargetGroup, ElastiCache 인벤토리 디스커버리 검증.
"""

from unittest.mock import MagicMock

from common.resource_discovery import (
    _discover_load_balancers,
    _discover_target_groups,
    _discover_elasticache,
)


def _session_returning(client) -> MagicMock:
    session = MagicMock()
    session.client.return_value = client
    return session


def _paginated(client, pages):
    paginator = MagicMock()
    paginator.paginate.return_value = pages
    client.get_paginator.return_value = paginator


# ──────────────────────────────────────────────
# _discover_load_balancers: ALB + NLB, gateway 제외
# ──────────────────────────────────────────────


def test_discover_load_balancers_includes_alb_and_nlb_excludes_gateway():
    elbv2 = MagicMock()
    _paginated(elbv2, [{"LoadBalancers": [
        {"LoadBalancerArn": "arn:alb", "LoadBalancerName": "alb", "Type": "application"},
        {"LoadBalancerArn": "arn:nlb", "LoadBalancerName": "nlb", "Type": "network"},
        {"LoadBalancerArn": "arn:gw", "LoadBalancerName": "gw", "Type": "gateway"},
    ]}])
    elbv2.describe_tags.return_value = {"TagDescriptions": [{"Tags": [{"Key": "Monitoring", "Value": "on"}]}]}

    out = _discover_load_balancers(_session_returning(elbv2), "123", "us-east-1", "cust")

    by_type = {r["type"]: r for r in out}
    assert set(by_type) == {"ALB", "NLB"}  # gateway 제외
    assert by_type["NLB"]["resource_id"] == "arn:nlb"
    assert by_type["ALB"]["monitoring"] is True


# ──────────────────────────────────────────────
# _discover_target_groups
# ──────────────────────────────────────────────


def test_discover_target_groups():
    elbv2 = MagicMock()
    _paginated(elbv2, [{"TargetGroups": [
        {"TargetGroupArn": "arn:tg", "TargetGroupName": "tg"},
    ]}])
    elbv2.describe_tags.return_value = {"TagDescriptions": [{"Tags": []}]}

    out = _discover_target_groups(_session_returning(elbv2), "123", "us-east-1", "cust")

    assert len(out) == 1
    assert out[0]["type"] == "TG"
    assert out[0]["resource_id"] == "arn:tg"
    assert out[0]["monitoring"] is False


# ──────────────────────────────────────────────
# _discover_elasticache: redis만, ARN 기반 태그
# ──────────────────────────────────────────────


def test_discover_elasticache_redis_only_with_tags():
    ec = MagicMock()
    _paginated(ec, [{"CacheClusters": [
        {"CacheClusterId": "redis-1", "Engine": "redis", "ARN": "arn:redis-1"},
        {"CacheClusterId": "mc-1", "Engine": "memcached", "ARN": "arn:mc-1"},
    ]}])
    ec.list_tags_for_resource.return_value = {"TagList": [{"Key": "Monitoring", "Value": "on"}]}

    out = _discover_elasticache(_session_returning(ec), "123", "us-east-1", "cust")

    assert len(out) == 1  # memcached 제외
    assert out[0]["type"] == "ElastiCache"
    assert out[0]["resource_id"] == "redis-1"
    assert out[0]["monitoring"] is True
    ec.list_tags_for_resource.assert_called_once_with(ResourceName="arn:redis-1")
