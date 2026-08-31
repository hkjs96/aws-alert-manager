"""
런 스코프 태그 캐시 (common/tag_cache.py) 테스트

- GetResources 페이지 순회 → ARN→태그 적재, 활성화 규칙(≥1건)
- 활성: 히트는 태그, 부재는 {} (trust_negative=False면 None)
- 비활성/프라임 실패/0건/TAG_CACHE=off → None (호출자 폴백)
- 컬렉터·디스커버리 호출부가 캐시를 우선 쓰고 리소스별 API를 건너뛰는지
"""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from common import tag_cache
from common.tag_cache import (
    TagCache,
    cached_tags,
    prime_tag_cache,
    set_active_tag_cache,
)

ARN_A = "arn:aws:rds:ap-northeast-2:123456789012:db:db-a"
ARN_B = "arn:aws:lambda:ap-northeast-2:123456789012:function:fn-b"


def _rgt_client(pages):
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = pages
    return client


@pytest.fixture(autouse=True)
def _reset_active(monkeypatch):
    monkeypatch.delenv("TAG_CACHE", raising=False)   # conftest의 전역 off 해제
    set_active_tag_cache(None)
    yield
    set_active_tag_cache(None)


class TestPrime:
    def test_loads_all_pages_and_activates(self):
        client = _rgt_client([
            {"ResourceTagMappingList": [
                {"ResourceARN": ARN_A, "Tags": [{"Key": "Monitoring", "Value": "on"}, {"Key": "Name", "Value": "A"}]},
            ]},
            {"ResourceTagMappingList": [
                {"ResourceARN": ARN_B, "Tags": []},
            ]},
        ])
        cache = TagCache()
        assert cache.prime(client) is True
        assert cache.active and len(cache) == 2
        assert cache.stats["pages"] == 2 and cache.stats["primed"] == 2
        kwargs = client.get_paginator.return_value.paginate.call_args.kwargs
        assert kwargs["ResourcesPerPage"] == 100
        assert "rds" in kwargs["ResourceTypeFilters"]

    def test_zero_resources_stays_inactive(self):
        cache = TagCache()
        assert cache.prime(_rgt_client([{"ResourceTagMappingList": []}])) is False
        assert not cache.active
        assert cache.lookup(ARN_A) is None

    def test_client_error_stays_inactive(self):
        client = MagicMock()
        client.get_paginator.return_value.paginate.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "no tag:GetResources"}},
            "GetResources",
        )
        cache = TagCache()
        assert cache.prime(client) is False
        assert not cache.active

    def test_magicmock_paginator_does_not_activate(self):
        # MagicMock 세션(테스트 픽스처)에서 paginate()는 빈 iterable → 0건 → 비활성
        cache = TagCache()
        assert cache.prime(MagicMock()) is False


class TestLookup:
    def _active_cache(self):
        cache = TagCache()
        cache.prime(_rgt_client([{"ResourceTagMappingList": [
            {"ResourceARN": ARN_A, "Tags": [{"Key": "Monitoring", "Value": "on"}]},
        ]}]))
        set_active_tag_cache(cache)
        return cache

    def test_hit_negative_and_copy_semantics(self):
        cache = self._active_cache()
        tags = cached_tags(ARN_A)
        assert tags == {"Monitoring": "on"}
        tags["mutated"] = "x"
        assert cached_tags(ARN_A) == {"Monitoring": "on"}   # 내부 dict 보호
        assert cached_tags(ARN_B) == {}                      # 부재 = 태그 없음
        assert cached_tags(ARN_B, trust_negative=False) is None
        assert cached_tags("") is None
        assert cache.stats["hits"] == 2 and cache.stats["negatives"] == 1

    def test_no_active_cache_returns_none(self):
        assert cached_tags(ARN_A) is None

    def test_env_kill_switch(self, monkeypatch):
        monkeypatch.setenv("TAG_CACHE", "off")
        factory = MagicMock()
        cache = prime_tag_cache(factory, label="t")
        assert not cache.active
        factory.assert_not_called()
        assert cached_tags(ARN_A) is None

    def test_prime_tag_cache_registers_active(self):
        client = _rgt_client([{"ResourceTagMappingList": [{"ResourceARN": ARN_A, "Tags": []}]}])
        cache = prime_tag_cache(lambda: client, label="t")
        assert cache.active and tag_cache.get_active_tag_cache() is cache
        assert cached_tags(ARN_A) == {}


class TestCallers:
    """호출부가 캐시를 우선 쓰고, 캐시가 없으면 기존 API로 폴백하는지."""

    def _activate(self, mapping: dict[str, dict]):
        cache = TagCache()
        cache.prime(_rgt_client([{"ResourceTagMappingList": [
            {"ResourceARN": arn, "Tags": [{"Key": k, "Value": v} for k, v in tags.items()]}
            for arn, tags in mapping.items()
        ]}]))
        set_active_tag_cache(cache)

    def test_rds_collector_skips_list_tags_when_cached(self):
        from common.collectors import rds as rds_collector

        self._activate({ARN_A: {"Monitoring": "on"}})
        client = MagicMock()
        assert rds_collector._get_tags(client, ARN_A) == {"Monitoring": "on"}
        assert rds_collector._get_tags(client, "arn:aws:rds:ap-northeast-2:1:db:other") == {}
        client.list_tags_for_resource.assert_not_called()

    def test_rds_collector_falls_back_without_cache(self):
        from common.collectors import rds as rds_collector

        client = MagicMock()
        client.list_tags_for_resource.return_value = {"TagList": [{"Key": "Monitoring", "Value": "on"}]}
        assert rds_collector._get_tags(client, ARN_A) == {"Monitoring": "on"}
        client.list_tags_for_resource.assert_called_once()

    def test_s3_collector_only_trusts_hits(self):
        from common.collectors import s3 as s3_collector

        self._activate({"arn:aws:s3:::bucket-a": {"Monitoring": "on"}})
        client = MagicMock()
        client.get_bucket_tagging.return_value = {"TagSet": [{"Key": "Name", "Value": "B"}]}
        assert s3_collector._get_bucket_tags(client, "bucket-a") == {"Monitoring": "on"}
        # 다른 리전 버킷일 수 있으므로 부재는 API 폴백
        assert s3_collector._get_bucket_tags(client, "bucket-b") == {"Name": "B"}
        client.get_bucket_tagging.assert_called_once()

    def test_discovery_rds_uses_cache(self):
        from common.resource_discovery import _discover_rds

        self._activate({ARN_A: {"Monitoring": "on", "Name": "A"}})
        rds = MagicMock()
        rds.get_paginator.return_value.paginate.return_value = [{"DBInstances": [
            {"DBInstanceIdentifier": "db-a", "Engine": "mysql", "DBInstanceArn": ARN_A},
            {"DBInstanceIdentifier": "db-z", "Engine": "mysql",
             "DBInstanceArn": "arn:aws:rds:ap-northeast-2:123456789012:db:db-z"},
        ]}]
        session = MagicMock()
        session.client.return_value = rds
        items = _discover_rds(session, "123456789012", "ap-northeast-2", "cust")
        assert [(i["resource_id"], i["monitoring"], i["tags"]) for i in items] == [
            ("db-a", True, {"Monitoring": "on", "Name": "A"}),
            ("db-z", False, {}),
        ]
        rds.list_tags_for_resource.assert_not_called()

    def test_discovery_dynamodb_skips_describe_table_when_cached(self):
        from common.resource_discovery import _discover_dynamodb

        arn = "arn:aws:dynamodb:ap-northeast-2:123456789012:table/t1"
        self._activate({arn: {"Monitoring": "on"}})
        ddb = MagicMock()
        ddb.get_paginator.return_value.paginate.return_value = [{"TableNames": ["t1"]}]
        session = MagicMock()
        session.client.return_value = ddb
        items = _discover_dynamodb(session, "123456789012", "ap-northeast-2", "cust")
        assert items[0]["arn"] == arn and items[0]["monitoring"] is True
        ddb.describe_table.assert_not_called()
        ddb.list_tags_of_resource.assert_not_called()

    def test_discover_resources_primes_per_region_and_global(self):
        from common import resource_discovery as rd

        primed_labels = []

        def fake_prime(factory, *, label=""):
            primed_labels.append(label)
            return TagCache()

        session = MagicMock()
        with patch.object(rd, "_get_session_for_account", return_value=session), \
             patch.object(rd, "prime_tag_cache", side_effect=fake_prime), \
             patch.object(rd, "_discover_ec2", return_value=[]):
            rd.discover_resources([{"account_id": "1", "role_arn": "", "regions": ["ap-northeast-2", "us-west-2"]}])
        assert primed_labels == [
            "account=1 region=ap-northeast-2",
            "account=1 region=us-west-2",
            "account=1 region=us-east-1 (global)",
        ]
        assert tag_cache.get_active_tag_cache() is None  # 종료 시 해제
