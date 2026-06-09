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
    _discover_apigw,
    _discover_acm,
    _discover_backup,
    _discover_mq,
    _discover_msk,
    _discover_waf,
    _discover_dx,
    _discover_sagemaker,
    _discover_sns,
    _discover_vpn,
    _discover_cloudfront,
    _discover_route53,
)


def _session_returning(client) -> MagicMock:
    session = MagicMock()
    session.client.return_value = client
    return session


def _session_with(mapping: dict) -> MagicMock:
    """서비스명 → 클라이언트 매핑 세션 (여러 클라이언트를 쓰는 타입용, 예: APIGW)."""
    session = MagicMock()
    session.client.side_effect = lambda svc, *a, **k: mapping[svc]
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


# ──────────────────────────────────────────────
# Batch 2 신규 디스커버리
# ──────────────────────────────────────────────


def test_discover_apigw_rest_and_v2():
    rest = MagicMock()
    _paginated(rest, [{"items": [{"id": "r1", "name": "rest-api"}]}])
    rest.get_tags.return_value = {"tags": {"Monitoring": "on"}}
    v2 = MagicMock()
    _paginated(v2, [{"Items": [
        {"ApiId": "h1", "Name": "http-api", "ProtocolType": "HTTP", "Tags": {"Monitoring": "off"}},
    ]}])

    out = _discover_apigw(_session_with({"apigateway": rest, "apigatewayv2": v2}),
                          "123", "us-east-1", "cust")

    by_id = {r["resource_id"]: r for r in out}
    assert by_id["rest-api"]["arn"] == "arn:aws:apigateway:us-east-1::/restapis/r1"
    assert by_id["rest-api"]["monitoring"] is True
    assert by_id["rest-api"]["tags"]["_api_type"] == "REST"
    assert by_id["h1"]["arn"] == "arn:aws:apigateway:us-east-1::/apis/h1"
    assert by_id["h1"]["monitoring"] is False
    assert by_id["h1"]["tags"]["_api_type"] == "HTTP"


def test_discover_acm_full_collection_monitoring_on():
    acm = MagicMock()
    _paginated(acm, [{"CertificateSummaryList": [
        {"CertificateArn": "arn:acm:c1", "DomainName": "ex.com"},
    ]}])
    acm.describe_certificate.return_value = {"Certificate": {"DomainName": "ex.com"}}

    out = _discover_acm(_session_returning(acm), "123", "us-east-1", "cust")

    assert out[0]["type"] == "ACM"
    assert out[0]["resource_id"] == "arn:acm:c1"
    assert out[0]["arn"] == "arn:acm:c1"
    assert out[0]["name"] == "ex.com"
    assert out[0]["monitoring"] is True


def test_discover_backup_vault_arn():
    backup = MagicMock()
    _paginated(backup, [{"BackupVaultList": [
        {"BackupVaultName": "v1", "BackupVaultArn": "arn:backup:v1"},
    ]}])
    backup.list_tags.return_value = {"Tags": {"Monitoring": "on"}}

    out = _discover_backup(_session_returning(backup), "123", "us-east-1", "cust")

    assert out[0]["type"] == "Backup"
    assert out[0]["resource_id"] == "v1"
    assert out[0]["arn"] == "arn:backup:v1"
    assert out[0]["monitoring"] is True


def test_discover_mq_broker_level():
    mq = MagicMock()
    _paginated(mq, [{"BrokerSummaries": [{"BrokerId": "b-1", "BrokerName": "broker1"}]}])
    mq.describe_broker.return_value = {"BrokerArn": "arn:mq:broker1", "Tags": {"Monitoring": "on"}}

    out = _discover_mq(_session_returning(mq), "123", "us-east-1", "cust")

    assert out[0]["type"] == "MQ"
    assert out[0]["resource_id"] == "broker1"
    assert out[0]["arn"] == "arn:mq:broker1"
    assert out[0]["monitoring"] is True


def test_discover_msk_cluster_arn():
    kafka = MagicMock()
    _paginated(kafka, [{"ClusterInfoList": [
        {"ClusterName": "msk1", "ClusterArn": "arn:kafka:msk1", "Tags": {"Monitoring": "on"}},
    ]}])

    out = _discover_msk(_session_returning(kafka), "123", "us-east-1", "cust")

    assert out[0]["type"] == "MSK"
    assert out[0]["resource_id"] == "msk1"
    assert out[0]["arn"] == "arn:kafka:msk1"


def test_discover_waf_regional():
    waf = MagicMock()
    waf.list_web_acls.return_value = {"WebACLs": [{"Name": "acl1", "ARN": "arn:waf:acl1"}]}
    waf.list_tags_for_resource.return_value = {
        "TagInfoForResource": {"TagList": [{"Key": "Monitoring", "Value": "on"}]}
    }

    out = _discover_waf(_session_returning(waf), "123", "us-east-1", "cust")

    assert out[0]["type"] == "WAF"
    assert out[0]["resource_id"] == "acl1"
    assert out[0]["arn"] == "arn:waf:acl1"
    assert out[0]["tags"]["_waf_rule"] == "ALL"
    assert out[0]["monitoring"] is True


def test_discover_dx_available_only():
    dx = MagicMock()
    dx.describe_connections.return_value = {"connections": [
        {"connectionId": "dxcon-1", "connectionState": "available"},
        {"connectionId": "dxcon-2", "connectionState": "down"},
    ]}
    dx.describe_tags.return_value = {"resourceTags": [
        {"tags": [{"key": "Monitoring", "value": "on"}]},
    ]}

    out = _discover_dx(_session_returning(dx), "123", "ap-northeast-2", "cust")

    assert [r["resource_id"] for r in out] == ["dxcon-1"]
    assert out[0]["arn"] == "arn:aws:directconnect:ap-northeast-2:123:dxcon/dxcon-1"
    assert out[0]["monitoring"] is True


def test_discover_sagemaker_endpoint():
    sm = MagicMock()
    _paginated(sm, [{"Endpoints": [{"EndpointName": "ep1", "EndpointArn": "arn:sm:ep1"}]}])
    sm.list_tags.return_value = {"Tags": [{"Key": "Monitoring", "Value": "on"}]}

    out = _discover_sagemaker(_session_returning(sm), "123", "us-east-1", "cust")

    assert out[0]["type"] == "SageMaker"
    assert out[0]["resource_id"] == "ep1"
    assert out[0]["arn"] == "arn:sm:ep1"


def test_discover_sns_topic_name_from_arn():
    sns = MagicMock()
    _paginated(sns, [{"Topics": [{"TopicArn": "arn:aws:sns:us-east-1:123:my-topic"}]}])
    sns.list_tags_for_resource.return_value = {"Tags": [{"Key": "Monitoring", "Value": "on"}]}

    out = _discover_sns(_session_returning(sns), "123", "us-east-1", "cust")

    assert out[0]["resource_id"] == "my-topic"
    assert out[0]["arn"] == "arn:aws:sns:us-east-1:123:my-topic"
    assert out[0]["monitoring"] is True


def test_discover_vpn_excludes_deleted():
    ec2 = MagicMock()
    ec2.describe_vpn_connections.return_value = {"VpnConnections": [
        {"VpnConnectionId": "vpn-1", "State": "available",
         "Tags": [{"Key": "Monitoring", "Value": "on"}]},
        {"VpnConnectionId": "vpn-2", "State": "deleted", "Tags": []},
    ]}

    out = _discover_vpn(_session_returning(ec2), "123456789012", "ap-northeast-2", "cust")

    assert [r["resource_id"] for r in out] == ["vpn-1"]
    assert out[0]["arn"] == "arn:aws:ec2:ap-northeast-2:123456789012:vpn-connection/vpn-1"
    assert out[0]["monitoring"] is True


def test_discover_cloudfront_global():
    cf = MagicMock()
    _paginated(cf, [{"DistributionList": {"Items": [{"Id": "E123", "ARN": "arn:cf:E123"}]}}])
    cf.list_tags_for_resource.return_value = {"Tags": {"Items": [{"Key": "Monitoring", "Value": "on"}]}}

    out = _discover_cloudfront(_session_returning(cf), "123", "cust")

    assert out[0]["type"] == "CloudFront"
    assert out[0]["resource_id"] == "E123"
    assert out[0]["arn"] == "arn:cf:E123"
    assert out[0]["region"] == "us-east-1"
    assert out[0]["monitoring"] is True


def test_discover_route53_global():
    r53 = MagicMock()
    _paginated(r53, [{"HealthChecks": [{"Id": "hc-1"}]}])
    r53.list_tags_for_resource.return_value = {
        "ResourceTagSet": {"Tags": [{"Key": "Monitoring", "Value": "on"}]}
    }

    out = _discover_route53(_session_returning(r53), "123", "cust")

    assert out[0]["type"] == "Route53"
    assert out[0]["resource_id"] == "hc-1"
    assert out[0]["arn"] == "arn:aws:route53:::healthcheck/hc-1"
    assert out[0]["region"] == "us-east-1"
    assert out[0]["monitoring"] is True
