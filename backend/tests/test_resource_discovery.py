"""common.resource_discovery 디스커버리 함수 단위 테스트.

LB(ALB/NLB), TargetGroup, ElastiCache 인벤토리 디스커버리 검증.
"""

from unittest.mock import MagicMock

from common.resource_discovery import (
    _discover_load_balancers,
    _discover_target_groups,
    _discover_elasticache,
    _discover_nat,
    _discover_docdb,
    _discover_clb,
    _discover_sqs,
    _discover_dynamodb,
    _discover_efs,
    _discover_opensearch,
    _discover_ecs,
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


def test_discover_elasticache_redis_and_valkey_excludes_memcached():
    ec = MagicMock()
    _paginated(ec, [{"CacheClusters": [
        {"CacheClusterId": "redis-1", "Engine": "redis", "ARN": "arn:redis-1"},
        {"CacheClusterId": "valkey-1", "Engine": "valkey", "ARN": "arn:valkey-1"},
        {"CacheClusterId": "mc-1", "Engine": "memcached", "ARN": "arn:mc-1"},
    ]}])
    ec.list_tags_for_resource.return_value = {"TagList": [{"Key": "Monitoring", "Value": "on"}]}

    out = _discover_elasticache(_session_returning(ec), "123", "us-east-1", "cust")

    # Redis + Valkey 수집, Memcached 제외
    assert sorted(r["resource_id"] for r in out) == ["redis-1", "valkey-1"]
    assert all(r["type"] == "ElastiCache" for r in out)
    assert all(r["monitoring"] is True for r in out)


# ──────────────────────────────────────────────
# _discover_nat: deleting/deleted 제외, 응답 태그 사용
# ──────────────────────────────────────────────


def test_discover_nat_excludes_deleting():
    ec2 = MagicMock()
    _paginated(ec2, [{"NatGateways": [
        {"NatGatewayId": "nat-1", "State": "available",
         "Tags": [{"Key": "Monitoring", "Value": "on"}, {"Key": "Name", "Value": "my-nat"}]},
        {"NatGatewayId": "nat-2", "State": "deleting", "Tags": []},
    ]}])

    out = _discover_nat(_session_returning(ec2), "123", "us-east-1", "cust")

    assert len(out) == 1  # deleting 제외
    assert out[0]["type"] == "NAT"
    assert out[0]["resource_id"] == "nat-1"
    assert out[0]["name"] == "my-nat"
    assert out[0]["monitoring"] is True


# ──────────────────────────────────────────────
# ARN 캐처: 기존 타입도 arn 필드를 채운다 (토글용)
# ──────────────────────────────────────────────


def test_discover_elasticache_includes_arn():
    ec = MagicMock()
    _paginated(ec, [{"CacheClusters": [
        {"CacheClusterId": "redis-1", "Engine": "redis", "ARN": "arn:redis-1"},
    ]}])
    ec.list_tags_for_resource.return_value = {"TagList": []}

    out = _discover_elasticache(_session_returning(ec), "123", "us-east-1", "cust")

    assert out[0]["arn"] == "arn:redis-1"


def test_discover_nat_constructs_arn():
    ec2 = MagicMock()
    _paginated(ec2, [{"NatGateways": [
        {"NatGatewayId": "nat-1", "State": "available", "Tags": []},
    ]}])

    out = _discover_nat(_session_returning(ec2), "123456789012", "ap-northeast-2", "cust")

    assert out[0]["arn"] == "arn:aws:ec2:ap-northeast-2:123456789012:natgateway/nat-1"


# ──────────────────────────────────────────────
# Batch 1 신규 디스커버리: DocDB/CLB/SQS/DynamoDB/EFS/OpenSearch/ECS
# ──────────────────────────────────────────────


def test_discover_docdb_filters_engine_and_captures_arn():
    rds = MagicMock()
    _paginated(rds, [{"DBInstances": [
        {"DBInstanceIdentifier": "docdb-1", "Engine": "docdb",
         "DBInstanceArn": "arn:docdb-1", "DBInstanceStatus": "available"},
        {"DBInstanceIdentifier": "mysql-1", "Engine": "mysql",
         "DBInstanceArn": "arn:mysql-1", "DBInstanceStatus": "available"},
        {"DBInstanceIdentifier": "docdb-del", "Engine": "docdb",
         "DBInstanceArn": "arn:del", "DBInstanceStatus": "deleting"},
    ]}])
    rds.list_tags_for_resource.return_value = {"TagList": [{"Key": "Monitoring", "Value": "on"}]}

    out = _discover_docdb(_session_returning(rds), "123", "us-east-1", "cust")

    assert [r["resource_id"] for r in out] == ["docdb-1"]  # mysql/deleting 제외
    assert out[0]["type"] == "DocDB"
    assert out[0]["arn"] == "arn:docdb-1"
    assert out[0]["monitoring"] is True


def test_discover_clb_constructs_arn():
    elb = MagicMock()
    _paginated(elb, [{"LoadBalancerDescriptions": [{"LoadBalancerName": "clb-1"}]}])
    elb.describe_tags.return_value = {
        "TagDescriptions": [{"Tags": [{"Key": "Monitoring", "Value": "off"}]}]
    }

    out = _discover_clb(_session_returning(elb), "123456789012", "ap-northeast-2", "cust")

    assert len(out) == 1
    assert out[0]["type"] == "CLB"
    assert out[0]["resource_id"] == "clb-1"
    assert out[0]["arn"] == (
        "arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:loadbalancer/clb-1"
    )
    assert out[0]["monitoring"] is False


def test_discover_sqs_extracts_name_and_constructs_arn():
    sqs = MagicMock()
    _paginated(sqs, [{"QueueUrls": [
        "https://sqs.ap-northeast-2.amazonaws.com/123456789012/my-queue",
    ]}])
    sqs.list_queue_tags.return_value = {"Tags": {"Monitoring": "on"}}

    out = _discover_sqs(_session_returning(sqs), "123456789012", "ap-northeast-2", "cust")

    assert out[0]["resource_id"] == "my-queue"
    assert out[0]["type"] == "SQS"
    assert out[0]["arn"] == "arn:aws:sqs:ap-northeast-2:123456789012:my-queue"
    assert out[0]["monitoring"] is True


def test_discover_dynamodb_uses_table_arn():
    ddb = MagicMock()
    _paginated(ddb, [{"TableNames": ["orders"]}])
    ddb.describe_table.return_value = {
        "Table": {"TableArn": "arn:aws:dynamodb:us-east-1:123:table/orders"}
    }
    ddb.list_tags_of_resource.return_value = {"Tags": [{"Key": "Monitoring", "Value": "on"}]}

    out = _discover_dynamodb(_session_returning(ddb), "123", "us-east-1", "cust")

    assert out[0]["resource_id"] == "orders"
    assert out[0]["type"] == "DynamoDB"
    assert out[0]["arn"] == "arn:aws:dynamodb:us-east-1:123:table/orders"
    assert out[0]["monitoring"] is True


def test_discover_efs_prefers_response_arn():
    efs = MagicMock()
    _paginated(efs, [{"FileSystems": [
        {"FileSystemId": "fs-1", "FileSystemArn": "arn:aws:efs:fs-1",
         "Tags": [{"Key": "Monitoring", "Value": "on"}, {"Key": "Name", "Value": "data"}]},
    ]}])

    out = _discover_efs(_session_returning(efs), "123", "us-east-1", "cust")

    assert out[0]["resource_id"] == "fs-1"
    assert out[0]["type"] == "EFS"
    assert out[0]["arn"] == "arn:aws:efs:fs-1"
    assert out[0]["name"] == "data"
    assert out[0]["monitoring"] is True


def test_discover_opensearch_captures_arn_and_client_id():
    client = MagicMock()
    client.list_domain_names.return_value = {"DomainNames": [{"DomainName": "logs"}]}
    client.describe_domains.return_value = {"DomainStatusList": [
        {"DomainName": "logs", "ARN": "arn:aws:es:us-east-1:123:domain/logs"},
    ]}
    client.list_tags.return_value = {"TagList": [{"Key": "Monitoring", "Value": "on"}]}

    out = _discover_opensearch(_session_returning(client), "123", "us-east-1", "cust")

    assert out[0]["resource_id"] == "logs"
    assert out[0]["type"] == "OpenSearch"
    assert out[0]["arn"] == "arn:aws:es:us-east-1:123:domain/logs"
    assert out[0]["tags"]["_client_id"] == "123"
    assert out[0]["monitoring"] is True


def test_discover_ecs_captures_service_arn_and_cluster():
    ecs = MagicMock()

    cluster_pag = MagicMock()
    cluster_pag.paginate.return_value = [
        {"clusterArns": ["arn:aws:ecs:us-east-1:123:cluster/prod"]}
    ]
    svc_pag = MagicMock()
    svc_pag.paginate.return_value = [
        {"serviceArns": ["arn:aws:ecs:us-east-1:123:service/prod/web"]}
    ]
    ecs.get_paginator.side_effect = (
        lambda op: cluster_pag if op == "list_clusters" else svc_pag
    )
    ecs.describe_services.return_value = {"services": [
        {"serviceArn": "arn:aws:ecs:us-east-1:123:service/prod/web",
         "serviceName": "web", "launchType": "FARGATE"},
    ]}
    ecs.list_tags_for_resource.return_value = {"tags": [{"key": "Monitoring", "value": "on"}]}

    out = _discover_ecs(_session_returning(ecs), "123", "us-east-1", "cust")

    assert out[0]["resource_id"] == "web"
    assert out[0]["type"] == "ECS"
    assert out[0]["arn"] == "arn:aws:ecs:us-east-1:123:service/prod/web"
    assert out[0]["tags"]["_cluster_name"] == "prod"
    assert out[0]["monitoring"] is True
