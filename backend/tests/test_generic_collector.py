"""
범용 수집기(P3) — 태그 캐시 나열 경로와 describe 폴백이 같은 결과를 내고, get_metrics가 옛 타입별 코드와 같은 쿼리를 낸다.

오라클 둘:
- `tests/fixtures/collector_metrics_snapshot_2026-09.json` — 이관 전 타입별 `get_metrics`가 내던 (namespace, metric, dims, key, stat).
- 같은 가짜 리소스를 RGT 페이지(태그 캐시)와 서비스 describe 응답 양쪽에 넣고 두 경로의 ResourceInfo 목록이 같은지.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from common import ResourceInfo
from common.collectors import base as cb
from common.collectors.generic import GenericCollector, is_monitored
from common.resource_types import base as R
from common.tag_cache import TagCache, arn_matches_filter, cached_matching, set_active_tag_cache

ORACLE = json.loads(
    (Path(__file__).parent / "fixtures" / "collector_metrics_snapshot_2026-09.json").read_text(encoding="utf-8"))

ACCOUNT = "123456789012"
REGION = "us-east-1"

# P3 1파·2파 — 이 모듈들이 GenericCollector 위에 있다.
WAVE1 = ["sqs", "sns", "lambda_fn", "dynamodb", "msk", "mq", "acm", "backup", "dx", "efs"]
WAVE2 = ["elasticache", "opensearch", "sagemaker", "ecs", "natgw", "vpn"]
WAVE3A = ["clb", "waf", "route53", "apigw", "s3"]          # 3파 중 메트릭이 정의로 표현되는 다섯
GENERIC = WAVE1 + WAVE2 + WAVE3A
# 3파 오버라이드 — 나열은 describe(_enumerate), 메트릭은 타입 고유(_metrics). 이유는 모듈 문서와 스펙 notes.
OVERRIDE = ["ec2", "rds", "elb", "docdb", "cloudfront"]


def _mod(name):
    return importlib.import_module(f"common.collectors.{name}")


def _rgt_client(entries):
    """(arn, tags) 목록 → GetResources 페이지를 돌려주는 가짜 RGT 클라이언트."""
    page = {"ResourceTagMappingList": [
        {"ResourceARN": arn, "Tags": [{"Key": k, "Value": v} for k, v in tags.items()]} for arn, tags in entries
    ]}
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [page]
    return client


def _activate_cache(entries) -> TagCache:
    cache = TagCache()
    assert cache.prime(_rgt_client(entries))
    set_active_tag_cache(cache)
    return cache


@pytest.fixture(autouse=True)
def _no_active_cache():
    set_active_tag_cache(None)
    yield
    set_active_tag_cache(None)


def _paginated(client, pages):
    client.get_paginator.return_value.paginate.return_value = pages


def _kv(tags):
    return [{"Key": k, "Value": v} for k, v in tags.items()]


# ────────────────────────────────── 태그 캐시: 나열 소스


class TestTagCacheMatching:
    def test_arn_filter_shapes(self):
        assert arn_matches_filter(f"arn:aws:sqs:{REGION}:{ACCOUNT}:q", "sqs")
        assert arn_matches_filter(f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:fn", "lambda:function")
        assert not arn_matches_filter(f"arn:aws:lambda:{REGION}:{ACCOUNT}:event-source-mapping:x", "lambda:function")
        assert arn_matches_filter(f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/t", "dynamodb:table")
        assert not arn_matches_filter(f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/t", "dynamodb:stream")
        assert arn_matches_filter(f"arn:aws:mq:{REGION}:{ACCOUNT}:broker:n:b-1", "mq:broker")
        assert arn_matches_filter(f"arn:aws:kafka:{REGION}:{ACCOUNT}:cluster/n/uuid", "kafka:cluster")
        assert arn_matches_filter("arn:aws:s3:::bucket", "s3")
        assert not arn_matches_filter(f"arn:aws:sns:{REGION}:{ACCOUNT}:t", "sqs")
        assert not arn_matches_filter("not-an-arn", "sqs")

    def test_inactive_cache_returns_none_not_empty(self):
        assert cached_matching(("sqs",)) is None
        cache = TagCache()
        set_active_tag_cache(cache)
        assert cached_matching(("sqs",)) is None          # 프라임 안 됨 → 폴백 신호

    def test_unprimed_service_returns_none(self):
        cache = TagCache()
        assert cache.prime(_rgt_client([(f"arn:aws:sqs:{REGION}:{ACCOUNT}:q", {"Monitoring": "on"})]),
                           services=["sqs"])
        assert cache.matching(("sqs",)) == [(f"arn:aws:sqs:{REGION}:{ACCOUNT}:q", {"Monitoring": "on"})]
        assert cache.matching(("kafka:cluster",)) is None  # kafka는 프라임 안 됨 — 빈 결과를 "0개"로 오판하지 않는다

    def test_matching_filters_by_type_and_monitoring_tag(self):
        cache = _activate_cache([
            (f"arn:aws:sqs:{REGION}:{ACCOUNT}:q-on", {"Monitoring": "on"}),
            (f"arn:aws:sqs:{REGION}:{ACCOUNT}:q-ON", {"Monitoring": "ON", "x": "y"}),
            (f"arn:aws:sqs:{REGION}:{ACCOUNT}:q-off", {"Monitoring": "off"}),
            (f"arn:aws:sqs:{REGION}:{ACCOUNT}:q-none", {"Team": "a"}),
            (f"arn:aws:sns:{REGION}:{ACCOUNT}:t-on", {"Monitoring": "on"}),
        ])
        got = cached_matching(("sqs",))
        assert [arn.rsplit(":", 1)[-1] for arn, _ in got] == ["q-on", "q-ON"]
        assert got[1][1] == {"Monitoring": "ON", "x": "y"}
        assert cache.stats["matched"] == 2
        got[0][1]["Monitoring"] = "mutated"                 # 복사본을 준다
        assert cached_matching(("sqs",))[0][1]["Monitoring"] == "on"

    def test_multiple_filters_union(self):
        _activate_cache([
            (f"arn:aws:apigateway:{REGION}::/restapis/abc", {"Monitoring": "on"}),
            (f"arn:aws:apigateway:{REGION}::/apis/def", {"Monitoring": "on"}),
        ])
        got = cached_matching(("apigateway:restapis", "apigateway:apis"))
        assert got is not None and len(got) == 2


# ────────────────────────────────── 레지스트리: identity


class TestIdentity:
    def test_wave1_types_with_identity_are_primed(self):
        assert set(R.rgt_enumerated_types()) == {"SQS", "SNS", "Lambda", "DynamoDB", "MSK", "Backup", "EFS"}
        for t in R.rgt_enumerated_types():
            assert R.get(t).rgt_prime, t

    def test_identity_requires_rgt_prime(self):
        with pytest.raises(ValueError, match="identity without rgt_prime"):
            R.register(R.ResourceTypeSpec(type="Zed", label="x", collector="sqs", rgt_filters=("zed:thing",),
                                          rgt_prime=False, identity=R.arn_tail(":"), notes="시연", lifecycle=()))

    @pytest.mark.parametrize("rtype, arn, expected", [
        ("SQS", f"arn:aws:sqs:{REGION}:{ACCOUNT}:orders-dlq", "orders-dlq"),
        ("SNS", f"arn:aws:sns:{REGION}:{ACCOUNT}:alerts", "alerts"),
        ("Lambda", f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:api-handler", "api-handler"),
        ("DynamoDB", f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/Customers", "Customers"),
        ("MSK", f"arn:aws:kafka:{REGION}:{ACCOUNT}:cluster/prod-kafka/0d5a-1b2c", "prod-kafka"),
        ("Backup", f"arn:aws:backup:{REGION}:{ACCOUNT}:backup-vault:Default", "Default"),
        ("EFS", f"arn:aws:elasticfilesystem:{REGION}:{ACCOUNT}:file-system/fs-0abc", "fs-0abc"),
    ])
    def test_identity_maps_arn_to_the_tagname_the_old_collector_used(self, rtype, arn, expected):
        assert R.get(rtype).identity(arn) == expected

    def test_arn_helpers(self):
        assert R.arn_resource(f"arn:aws:mq:{REGION}:{ACCOUNT}:broker:n:b-1") == "broker:n:b-1"
        assert R.arn_resource("garbage") == "garbage"
        assert R.arn_tail("/").__name__ == "arn_tail('/')"

    @pytest.mark.parametrize("name", GENERIC)
    def test_generic_modules_bind_the_protocol_and_say_why_when_not_rgt(self, name):
        mod = _mod(name)
        assert isinstance(mod.COLLECTOR, GenericCollector)
        assert mod.collect_monitored_resources == mod.COLLECTOR.collect_monitored_resources
        assert mod.get_metrics == mod.COLLECTOR.get_metrics
        assert mod.resolve_alive_ids == mod.COLLECTOR.resolve_alive_ids
        spec = mod.COLLECTOR.spec
        if not mod.COLLECTOR.rgt_capable:
            assert "identity 없음" in spec.notes, spec.type
        elif spec.identity is None:
            assert "_identities" in spec.notes, spec.type   # 모듈이 ARN→TagName을 맡는 이유

    @pytest.mark.parametrize("name", OVERRIDE)
    def test_override_modules_keep_their_own_metrics_and_say_why(self, name):
        mod = _mod(name)
        assert isinstance(mod.COLLECTOR, GenericCollector)
        assert not mod.COLLECTOR.rgt_capable and not mod.COLLECTOR.metrics_from_definitions
        assert "identity 없음" in mod.COLLECTOR.spec.notes
        assert "오버라이드" in mod.COLLECTOR.spec.notes and "오버라이드" in mod.__doc__
        assert mod.get_metrics == mod.COLLECTOR.get_metrics

    def test_every_collector_module_is_on_the_generic_collector(self):
        assert set(GENERIC + OVERRIDE) == set(R.collector_modules())

    def test_multi_type_enumeration_carries_the_type_per_item(self):
        """rds·elb는 스펙 하나가 아니라 타입 여럿을 낸다 — 항목의 세 번째 원소."""
        spec = R.get("SQS")
        col = GenericCollector(spec, alive=lambda n: n,
                               enumerate=lambda: [("a", {"Monitoring": "on"}), ("b", {"Monitoring": "on"}, "Other"),
                                                  ("c", {"Monitoring": "off"}, "Other")])
        got = col.collect_monitored_resources()
        assert [(r["id"], r["type"]) for r in got] == [("a", "SQS"), ("b", "Other")]

    def test_metrics_override_receives_extra_arguments_and_definitions_path_refuses_them(self):
        seen = {}
        col = GenericCollector(R.get("TG"), alive=lambda n: n, enumerate=lambda: [],
                               metrics=lambda rid, tags, lb_arn=None: seen.setdefault("call", (rid, tags, lb_arn)) and {"x": 1.0})
        assert col.get_metrics("tg", {"_lb_type": "network"}, lb_arn="lb") == {"x": 1.0}
        assert seen["call"] == ("tg", {"_lb_type": "network"}, "lb")
        with pytest.raises(TypeError, match="no extra arguments"):
            _mod("sqs").get_metrics("q", {}, lb_arn="lb")

    def test_rgt_enumeration_roster(self):
        """어느 타입이 태그 캐시로 나열되는지 — 설계(D4)의 16개 중 실제로는 9개. 나머지 이유는 스펙 notes."""
        via_rgt = {_mod(n).COLLECTOR.spec.type for n in GENERIC if _mod(n).COLLECTOR.rgt_capable}
        assert via_rgt == {"SQS", "SNS", "Lambda", "DynamoDB", "MSK", "Backup", "EFS", "MQ", "OpenSearch", "SageMaker",
                           "CLB", "WAF"}
        assert all(_mod(n).COLLECTOR.metrics_from_definitions for n in GENERIC)


# ────────────────────────────────── 나열: RGT 경로 == describe 폴백


def _sqs_describe(client, items):
    _paginated(client, [{"QueueUrls": [f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}/{n}" for n, _ in items]}])
    by_url = {f"https://sqs.{REGION}.amazonaws.com/{ACCOUNT}/{n}": t for n, t in items}
    client.list_queue_tags.side_effect = lambda QueueUrl: {"Tags": by_url[QueueUrl]}


def _sns_describe(client, items):
    arns = {n: f"arn:aws:sns:{REGION}:{ACCOUNT}:{n}" for n, _ in items}
    _paginated(client, [{"Topics": [{"TopicArn": arns[n]} for n, _ in items]}])
    by_arn = {arns[n]: t for n, t in items}
    client.list_tags_for_resource.side_effect = lambda ResourceArn: {"Tags": _kv(by_arn[ResourceArn])}


def _lambda_describe(client, items):
    arns = {n: f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{n}" for n, _ in items}
    _paginated(client, [{"Functions": [{"FunctionName": n, "FunctionArn": arns[n]} for n, _ in items]}])
    by_arn = {arns[n]: t for n, t in items}
    client.list_tags.side_effect = lambda Resource: {"Tags": by_arn[Resource]}


def _dynamodb_describe(client, items):
    arns = {n: f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{n}" for n, _ in items}
    _paginated(client, [{"TableNames": [n for n, _ in items]}])
    client.describe_table.side_effect = lambda TableName: {"Table": {"TableArn": arns[TableName]}}
    by_arn = {arns[n]: t for n, t in items}
    client.list_tags_of_resource.side_effect = lambda ResourceArn: {"Tags": _kv(by_arn[ResourceArn])}


def _msk_describe(client, items):
    _paginated(client, [{"ClusterInfoList": [{"ClusterName": n, "Tags": t} for n, t in items]}])


def _backup_describe(client, items):
    arns = {n: f"arn:aws:backup:{REGION}:{ACCOUNT}:backup-vault:{n}" for n, _ in items}
    _paginated(client, [{"BackupVaultList": [{"BackupVaultName": n, "BackupVaultArn": arns[n]} for n, _ in items]}])
    by_arn = {arns[n]: t for n, t in items}
    client.list_tags.side_effect = lambda ResourceArn: {"Tags": by_arn[ResourceArn]}


def _efs_describe(client, items):
    _paginated(client, [{"FileSystems": [{"FileSystemId": n, "Tags": _kv(t)} for n, t in items]}])


ITEMS = [("r-on", {"Monitoring": "on", "Env": "prod"}), ("r-off", {"Monitoring": "off"}), ("r-plain", {"Team": "x"})]

PURE_RGT = {
    "sqs": ("_get_sqs_client", "arn:aws:sqs:{r}:{a}:{n}", _sqs_describe),
    "sns": ("_get_sns_client", "arn:aws:sns:{r}:{a}:{n}", _sns_describe),
    "lambda_fn": ("_get_lambda_client", "arn:aws:lambda:{r}:{a}:function:{n}", _lambda_describe),
    "dynamodb": ("_get_dynamodb_client", "arn:aws:dynamodb:{r}:{a}:table/{n}", _dynamodb_describe),
    "msk": ("_get_kafka_client", "arn:aws:kafka:{r}:{a}:cluster/{n}/0d5a-1b2c", _msk_describe),
    "backup": ("_get_backup_client", "arn:aws:backup:{r}:{a}:backup-vault:{n}", _backup_describe),
    "efs": ("_get_efs_client", "arn:aws:elasticfilesystem:{r}:{a}:file-system/{n}", _efs_describe),
}


class TestEnumerationEquivalence:
    @pytest.mark.parametrize("name", list(PURE_RGT))
    def test_rgt_path_equals_describe_path_and_makes_no_service_calls(self, name):
        mod = _mod(name)
        client_attr, arn_fmt, describe = PURE_RGT[name]
        expected = [ResourceInfo(id="r-on", type=mod.COLLECTOR.spec.type,
                                 tags={"Monitoring": "on", "Env": "prod"}, region=REGION)]

        # describe 폴백 (캐시 없음)
        client = MagicMock()
        describe(client, ITEMS)
        with patch.object(mod, client_attr, return_value=client):
            via_describe = mod.collect_monitored_resources()
        assert mod.COLLECTOR.last_source == "enumerate"
        assert via_describe == expected

        # RGT 경로 (캐시 활성) — 서비스 클라이언트를 만들지도 않는다
        _activate_cache([(arn_fmt.format(r=REGION, a=ACCOUNT, n=n), t) for n, t in ITEMS])
        untouched = MagicMock(side_effect=AssertionError("service client must not be used on the RGT path"))
        with patch.object(mod, client_attr, untouched):
            via_rgt = mod.collect_monitored_resources()
        assert mod.COLLECTOR.last_source == "rgt"
        assert via_rgt == via_describe

    def test_mq_rgt_path_splits_instances_like_the_describe_path(self):
        mod = _mod("mq")
        brokers = [("b-1", "broker-ha", {"Monitoring": "on"}, "ACTIVE_STANDBY_MULTI_AZ"),
                   ("b-2", "broker-single", {"Monitoring": "on", "Tier": "t2"}, "SINGLE_INSTANCE"),
                   ("b-3", "broker-off", {"Monitoring": "off"}, "SINGLE_INSTANCE")]
        client = MagicMock()
        _paginated(client, [{"BrokerSummaries": [{"BrokerId": i, "BrokerName": n} for i, n, _t, _m in brokers]}])
        by_id = {i: (t, m) for i, _n, t, m in brokers}
        client.describe_broker.side_effect = lambda BrokerId: {"Tags": by_id[BrokerId][0], "DeploymentMode": by_id[BrokerId][1]}

        with patch.object(mod, "_get_mq_client", return_value=client):
            via_describe = mod.collect_monitored_resources()
        assert [r["id"] for r in via_describe] == ["broker-ha-1", "broker-ha-2", "broker-single-1"]
        assert all(r["tags"]["Name"] == r["id"].rsplit("-", 1)[0] for r in via_describe)

        _activate_cache([(f"arn:aws:mq:{REGION}:{ACCOUNT}:broker:{n}:{i}", t) for i, n, t, _m in brokers])
        client.reset_mock()
        with patch.object(mod, "_get_mq_client", return_value=client):
            via_rgt = mod.collect_monitored_resources()
        assert mod.COLLECTOR.last_source == "rgt"
        assert via_rgt == via_describe
        # 배포 모드만 물었다 — Monitoring=on 브로커 2개, 태그 조회는 캐시가 대신했다
        assert client.describe_broker.call_count == 2
        client.get_paginator.assert_not_called()

    def test_acm_ignores_the_cache_because_it_collects_untagged_certificates(self):
        from datetime import datetime, timedelta, timezone
        mod = _mod("acm")
        _activate_cache([(f"arn:aws:acm:{REGION}:{ACCOUNT}:certificate/tagged", {"Monitoring": "on"})])
        client = MagicMock()
        _paginated(client, [{"CertificateSummaryList": [{"CertificateArn": f"arn:aws:acm:{REGION}:{ACCOUNT}:certificate/untagged"}]}])
        client.describe_certificate.return_value = {"Certificate": {
            "DomainName": "shop.example.com", "NotAfter": datetime.now(timezone.utc) + timedelta(days=30)}}
        with patch.object(mod, "_get_acm_client", return_value=client):
            got = mod.collect_monitored_resources()
        assert mod.COLLECTOR.last_source == "enumerate"
        assert got == [ResourceInfo(id=f"arn:aws:acm:{REGION}:{ACCOUNT}:certificate/untagged", type="ACM",
                                    tags={"Monitoring": "on", "Name": "shop.example.com"}, region=REGION)]

    def test_dx_keeps_describe_for_the_state_filter_but_reads_tags_from_the_cache(self):
        mod = _mod("dx")
        arn_ok = f"arn:aws:directconnect:{REGION}:{ACCOUNT}:dxcon/dxcon-ok"
        arn_down = f"arn:aws:directconnect:{REGION}:{ACCOUNT}:dxcon/dxcon-down"
        cache = _activate_cache([(arn_ok, {"Monitoring": "on"}), (arn_down, {"Monitoring": "on"})])
        client = MagicMock()
        client.describe_connections.return_value = {"connections": [
            {"connectionId": "dxcon-ok", "connectionState": "available", "ownerAccount": ACCOUNT, "region": REGION},
            {"connectionId": "dxcon-down", "connectionState": "down", "ownerAccount": ACCOUNT, "region": REGION},
        ]}
        with patch.object(mod, "_get_dx_client", return_value=client):
            got = mod.collect_monitored_resources()
        assert mod.COLLECTOR.last_source == "enumerate"
        assert [r["id"] for r in got] == ["dxcon-ok"]
        client.describe_tags.assert_not_called()
        assert cache.stats["hits"] == 1

    def test_opensearch_rgt_path_adds_client_id_from_the_arn_like_describe_did_from_sts(self):
        mod = _mod("opensearch")
        arn = f"arn:aws:es:{REGION}:{ACCOUNT}:domain/"
        domains = [("logs", {"Monitoring": "on", "Team": "obs"}), ("scratch", {"Monitoring": "off"})]
        client = MagicMock()
        client.list_domain_names.return_value = {"DomainNames": [{"DomainName": n} for n, _ in domains]}
        client.describe_domains.side_effect = lambda DomainNames: {
            "DomainStatusList": [{"DomainName": n, "ARN": arn + n} for n in DomainNames]}
        by_arn = {arn + n: t for n, t in domains}
        client.list_tags.side_effect = lambda ARN: {"TagList": _kv(by_arn[ARN])}
        sts = MagicMock()
        sts.get_caller_identity.return_value = {"Account": ACCOUNT}
        with patch.object(mod, "_get_opensearch_client", return_value=client), \
             patch.object(mod, "_get_sts_client", return_value=sts):
            via_describe = mod.collect_monitored_resources()
        assert via_describe == [ResourceInfo(id="logs", type="OpenSearch", region=REGION,
                                             tags={"Monitoring": "on", "Team": "obs", "_client_id": ACCOUNT})]

        _activate_cache([(arn + n, t) for n, t in domains])
        untouched = MagicMock(side_effect=AssertionError("no service call on the RGT path"))
        with patch.object(mod, "_get_opensearch_client", untouched), patch.object(mod, "_get_sts_client", untouched):
            via_rgt = mod.collect_monitored_resources()
        assert mod.COLLECTOR.last_source == "rgt"
        assert via_rgt == via_describe

    def test_sagemaker_rgt_path_keeps_only_inservice_endpoints_and_reads_the_variant(self):
        mod = _mod("sagemaker")
        arn = f"arn:aws:sagemaker:{REGION}:{ACCOUNT}:endpoint/"
        endpoints = {  # name: (tags, status, variant)
            "churn": ({"Monitoring": "on"}, "InService", "AllTraffic"),
            "fraud": ({"Monitoring": "on"}, "Updating", "Blue"),
            "old": ({"Monitoring": "off"}, "InService", "AllTraffic"),
        }
        client = MagicMock()
        _paginated(client, [{"Endpoints": [{"EndpointName": n, "EndpointArn": arn + n, "EndpointStatus": s}
                                           for n, (_t, s, _v) in endpoints.items() if s == "InService"]}])
        client.list_tags.side_effect = lambda ResourceArn: {"Tags": _kv(endpoints[ResourceArn.rsplit("/", 1)[-1]][0])}
        client.describe_endpoint.side_effect = lambda EndpointName: {
            "EndpointStatus": endpoints[EndpointName][1],
            "ProductionVariants": [{"VariantName": endpoints[EndpointName][2]}]}
        with patch.object(mod, "_get_sagemaker_client", return_value=client):
            via_describe = mod.collect_monitored_resources()
        assert via_describe == [ResourceInfo(id="churn", type="SageMaker", region=REGION,
                                             tags={"Monitoring": "on", "_variant_name": "AllTraffic"})]

        _activate_cache([(arn + n, t) for n, (t, _s, _v) in endpoints.items()])
        client.reset_mock()
        with patch.object(mod, "_get_sagemaker_client", return_value=client):
            via_rgt = mod.collect_monitored_resources()
        assert mod.COLLECTOR.last_source == "rgt"
        assert via_rgt == via_describe
        # Monitoring=on 둘만 describe했고(상태·변형), list_endpoints·list_tags는 안 불렀다
        assert sorted(c.kwargs["EndpointName"] for c in client.describe_endpoint.call_args_list) == ["churn", "fraud"]
        client.get_paginator.assert_not_called()
        client.list_tags.assert_not_called()

    @pytest.mark.parametrize("name, client_attr, arn", [
        ("elasticache", "_get_elasticache_client", f"arn:aws:elasticache:{REGION}:{ACCOUNT}:cluster:redis-a"),
        ("ecs", "_get_ecs_client", f"arn:aws:ecs:{REGION}:{ACCOUNT}:service/prod/web"),
    ])
    def test_describe_only_types_ignore_a_cache_that_has_their_arns(self, name, client_attr, arn):
        mod = _mod(name)
        _activate_cache([(arn, {"Monitoring": "on"})])
        client = MagicMock()
        _paginated(client, [])          # describe가 아무것도 돌려주지 않으면 결과도 비어야 한다 — 캐시를 안 봤다는 증거
        client.list_domain_names.return_value = {"DomainNames": []}
        with patch.object(mod, client_attr, return_value=client):
            assert mod.collect_monitored_resources() == []
        assert mod.COLLECTOR.last_source == "enumerate"

    def test_ec2_subresources_use_the_server_side_tag_filter(self):
        natgw, vpn = _mod("natgw"), _mod("vpn")
        ec2 = MagicMock()
        _paginated(ec2, [{"NatGateways": [
            {"NatGatewayId": "nat-1", "State": "available", "Tags": _kv({"Monitoring": "on"})},
            {"NatGatewayId": "nat-2", "State": "deleting", "Tags": _kv({"Monitoring": "on"})}]}])
        ec2.describe_vpn_connections.return_value = {"VpnConnections": [
            {"VpnConnectionId": "vpn-1", "State": "available", "Tags": _kv({"Monitoring": "on"})}]}
        with patch.object(natgw, "_get_ec2_client", return_value=ec2), patch.object(vpn, "_get_ec2_client", return_value=ec2):
            assert [r["id"] for r in natgw.collect_monitored_resources()] == ["nat-1"]
            assert [r["id"] for r in vpn.collect_monitored_resources()] == ["vpn-1"]
        assert ec2.get_paginator.return_value.paginate.call_args.kwargs == {"Filter": [{"Name": "tag:Monitoring", "Values": ["on"]}]}
        assert ec2.describe_vpn_connections.call_args.kwargs == {"Filters": [{"Name": "tag:Monitoring", "Values": ["on"]}]}
        assert not natgw.COLLECTOR.rgt_capable and not vpn.COLLECTOR.rgt_capable

    def test_clb_rgt_path_keeps_only_classic_arns_from_the_shared_filter(self):
        mod = _mod("clb")
        lb_arn = f"arn:aws:elasticloadbalancing:{REGION}:{ACCOUNT}:loadbalancer/"
        entries = [(lb_arn + "legacy-lb", {"Monitoring": "on"}),
                   (lb_arn + "app/my-alb/0123456789abcdef", {"Monitoring": "on"}),
                   (lb_arn + "net/my-nlb/0123456789abcdef", {"Monitoring": "on"}),
                   (lb_arn + "gwy/my-gwlb/0123456789abcdef", {"Monitoring": "on"}),
                   (lb_arn + "legacy-off", {"Monitoring": "off"})]
        client = MagicMock()
        _paginated(client, [{"LoadBalancerDescriptions": [{"LoadBalancerName": "legacy-lb"}, {"LoadBalancerName": "legacy-off"}]}])
        client.describe_tags.side_effect = lambda LoadBalancerNames: {"TagDescriptions": [
            {"Tags": _kv({"Monitoring": "on" if LoadBalancerNames[0] == "legacy-lb" else "off"})}]}
        with patch.object(mod, "_get_elb_client", return_value=client):
            via_describe = mod.collect_monitored_resources()
        assert via_describe == [ResourceInfo(id="legacy-lb", type="CLB", tags={"Monitoring": "on"}, region=REGION)]

        _activate_cache(entries)
        untouched = MagicMock(side_effect=AssertionError("no service call on the RGT path"))
        with patch.object(mod, "_get_elb_client", untouched):
            via_rgt = mod.collect_monitored_resources()
        assert mod.COLLECTOR.last_source == "rgt"
        assert via_rgt == via_describe

    def test_waf_rgt_path_keeps_regional_acls_and_adds_the_internal_tags(self):
        mod = _mod("waf")
        entries = [(f"arn:aws:wafv2:{REGION}:{ACCOUNT}:regional/webacl/edge-acl/11111111", {"Monitoring": "on", "Env": "prod"}),
                   (f"arn:aws:wafv2:{REGION}:{ACCOUNT}:regional/webacl/quiet-acl/22222222", {"Monitoring": "off"}),
                   (f"arn:aws:wafv2:us-east-1:{ACCOUNT}:global/webacl/cf-acl/33333333", {"Monitoring": "on"})]
        client = MagicMock()
        client.list_web_acls.return_value = {"WebACLs": [{"Name": "edge-acl", "ARN": entries[0][0]},
                                                         {"Name": "quiet-acl", "ARN": entries[1][0]}]}
        by_arn = {arn: t for arn, t in entries}
        client.list_tags_for_resource.side_effect = lambda ResourceARN: {"TagInfoForResource": {"TagList": _kv(by_arn[ResourceARN])}}
        with patch.object(mod, "_get_wafv2_client", return_value=client):
            via_describe = mod.collect_monitored_resources()
        assert via_describe == [ResourceInfo(id="edge-acl", type="WAF", region=REGION,
                                             tags={"Monitoring": "on", "Env": "prod", "_waf_rule": "ALL", "_waf_region": REGION})]

        _activate_cache(entries)
        untouched = MagicMock(side_effect=AssertionError("no service call on the RGT path"))
        with patch.object(mod, "_get_wafv2_client", untouched):
            via_rgt = mod.collect_monitored_resources()
        assert mod.COLLECTOR.last_source == "rgt"
        assert via_rgt == via_describe      # CLOUDFRONT 스코프(global/)는 옛 수집기처럼 빠진다

    @pytest.mark.parametrize("name", ["route53", "s3", "apigw"])
    def test_global_or_named_types_stay_on_describe(self, name):
        assert not _mod(name).COLLECTOR.rgt_capable
        assert "identity 없음" in _mod(name).COLLECTOR.spec.notes

    def test_without_enumerate_a_dead_cache_collects_nothing_loudly(self, caplog):
        spec = R.get("SQS")
        col = GenericCollector(spec, alive=lambda names: names)
        with caplog.at_level("WARNING"):
            assert col.collect_monitored_resources() == []
        assert col.last_source == "none"
        assert "collecting nothing" in caplog.text

    def test_needs_some_way_to_enumerate(self):
        with pytest.raises(ValueError, match="needs spec.identity"):
            GenericCollector(R.get("ACM"), alive=lambda n: n)

    def test_is_monitored_matches_the_old_filter(self):
        assert is_monitored({"Monitoring": "on"}) and is_monitored({"Monitoring": "ON"})
        assert not is_monitored({"Monitoring": "off"}) and not is_monitored({}) and not is_monitored({"Monitoring": None})


# ────────────────────────────────── 메트릭: 정의에서 만든 쿼리 == 이관 전 스냅숏


def _dims_key(dims):
    # 디멘션 순서는 CloudWatch에 의미가 없다(MetricBatch.key_for도 정렬한다) — 옛 ECS 코드는 ClusterName을 먼저 썼다.
    return tuple(sorted((d["Name"], d["Value"]) for d in dims))


# 옛 수집기가 메트릭 키 개명(Phase 4 Task 16) 전 이름으로 결과를 돌려주던 곳. 알람 정의는 CloudWatch 이름을 쓰므로 범용
# get_metrics도 그 이름을 낸다 — daily run의 임계치 해석은 두 키가 같다(기본 80, `Threshold_CPU` 태그는 _LEGACY_TAG_MAP으로
# CPUUtilization에도 적용). 바뀌는 것은 임계치 알림의 metric_name 표기뿐이다. 3파의 RDS 계열(CPU·FreeMemoryGB·Connections…)은
# GB 변환이 얽혀 오버라이드로 남긴다 — 여기 목록은 범용으로 옮긴 타입만.
ACCEPTED_KEY_RENAMES = {("ElastiCache", "CPU"): "CPUUtilization"}

# 옛 수집기가 알람과 **다른 디멘션 집합**으로 물었던 곳 — CloudWatch는 디멘션이 정확히 일치하는 시리즈만 돌려주므로 옛 질의는
# 데이터가 없었다(WAF: 알람은 WebACL+Rule+Region, 수집기는 Region 없이; S3 요청 지표: 알람은 BucketName+FilterId, 수집기는
# BucketName만). 범용은 알람과 같은 빌더를 쓰므로 그 디멘션이 붙는다 — 비교에서 그 디멘션만 뺀다.
ACCEPTED_EXTRA_DIMS = {"WAF": {"Region"}, "S3": {"FilterId"}}
# 옛 S3 요청 지표는 collect_metric 대신 query_metric을 직접 불러 오라클에 결과 키가 없다 — 옛 코드가 넣던 키.
S3_REQUEST_KEYS = {"4xxErrors": "S34xxErrors", "5xxErrors": "S35xxErrors"}


def _expected_from_oracle(rtype, c):
    key = c["result_key"]
    label = c["label"]
    if rtype == "S3" and key is None:
        key, label = S3_REQUEST_KEYS[c["metric_name"]], "S3"
    return (c["namespace"], c["metric_name"], _dims_key(c["dimensions"]),
            ACCEPTED_KEY_RENAMES.get((rtype, key), key), c["stat"], c["transform"], label)


def _strip_accepted_dims(rtype, got):
    extra = ACCEPTED_EXTRA_DIMS.get(rtype, set())
    return [(ns, mn, tuple(d for d in dims if d[0] not in extra), key, stat, tr, label)
            for ns, mn, dims, key, stat, tr, label in got]


def _recorded_queries(mod, tags):
    calls = []

    def rec(ns, mn, dims, start, end, key, metrics, *, stat="Average", transform=None, resource_label="resource"):
        calls.append((ns, mn, _dims_key(dims), key, stat, bool(transform), resource_label))

    with patch("common.collectors.generic.collect_metric", rec):
        assert mod.get_metrics("RID", dict(tags)) is None
    return calls


class TestMetricsFromDefinitions:
    @pytest.mark.parametrize("name", GENERIC)
    def test_generic_get_metrics_issues_exactly_the_pre_migration_queries(self, name):
        mod = _mod(name)
        rtype = mod.COLLECTOR.spec.type
        oracle = ORACLE["types"][rtype]
        assert oracle["collector"] == name
        compared = 0
        for variant, entry in oracle["variants"].items():
            assert entry["status"] == "ok", (rtype, variant)
            if any(d["Value"] == "" for c in entry["calls"] for d in c["dimensions"]):
                # 옛 ECS/SageMaker 코드는 내부 태그가 없으면 빈 디멘션 값으로 질의했다 — CloudWatch가 거부하는 쿼리라
                # 성립하지 않았고, 알람 쪽 빌더(_build_dimensions)는 그 디멘션을 뺀다. 실제 태그가 있는 변형으로 비교한다.
                continue
            expected = [_expected_from_oracle(rtype, c) for c in entry["calls"]]
            got = _strip_accepted_dims(rtype, _recorded_queries(mod, json.loads(variant)))
            assert got == expected, (rtype, variant)
            compared += 1
        assert compared >= 1, rtype

    def test_get_metrics_is_batch_aware(self):
        mod = _mod("sqs")
        batch = cb.MetricBatch()
        cb.set_active_metric_batch(batch)
        try:
            batch.record()
            live = MagicMock(side_effect=AssertionError("record mode must not call CloudWatch"))
            with patch.object(cb, "_get_cw_client", live):
                assert mod.get_metrics("orders", {}) is None
            assert len(batch._pending) == len(mod.COLLECTOR.spec.alarms({}))
            assert all(k[0] == "AWS/SQS" and k[2] == (("QueueName", "orders"),) for k in batch._pending)
        finally:
            cb.set_active_metric_batch(None)

    def test_get_metrics_returns_values_under_metric_keys(self):
        mod = _mod("efs")
        from datetime import datetime, timezone
        cw = MagicMock()
        cw.get_metric_statistics.side_effect = lambda **kw: {"Datapoints": [
            {"Timestamp": datetime(2026, 9, 15, tzinfo=timezone.utc), kw["Statistics"][0]: 7.0}]} \
            if kw["MetricName"] == "PercentIOLimit" else {"Datapoints": []}
        with patch.object(cb, "_get_cw_client", return_value=cw):
            assert mod.get_metrics("fs-1", {}) == {"PercentIOLimit": 7.0}

    def test_tag_gated_definitions_follow_the_tags(self):
        """옵트인 정의(EC2 StatusCheckFailed_Application)는 태그가 있을 때만 알람이 되고, 메트릭도 그때만 본다."""
        spec = R.get("EC2")
        gate = {"Threshold_StatusCheckFailed_Application": "1"}
        opted_in = {d.get("metric_key") or d["metric"] for d in spec.alarms(gate) if d.get("opt_in")}
        assert opted_in and not {d["metric"] for d in spec.alarms({}) if d.get("opt_in")}
        col = GenericCollector(spec, alive=lambda n: n, enumerate=lambda: [])
        assert not {c[3] for c in _recorded_queries(col, {})} & opted_in
        assert {c[3] for c in _recorded_queries(col, gate)} >= opted_in
