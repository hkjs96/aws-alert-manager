"""
AlarmIndex (런 스코프 인메모리 알람 인덱스) 테스트

- 라이브 검색(_find_alarms_for_resource)과 동일한 매칭 의미론
- sync_alarms_for_resource가 인덱스 경로에서 describe_alarms를 호출하지 않는지
- 글로벌 서비스는 인덱스를 무시하고 라이브 경로로 폴백하는지
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from patch_helpers import alarm_config_fields

from common.alarm_index import AlarmIndex
from common.alarm_manager import sync_alarms_for_resource


def _alarm(name, region="", **extra):
    a = {"AlarmName": name, **extra}
    if region:
        a["_region"] = region
    return a


ALB_ARN = (
    "arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:"
    "loadbalancer/app/my-alb/50dc6c495c0c9188"
)


class TestFindNames:
    def test_ec2_new_format_match(self):
        idx = AlarmIndex([
            _alarm("[EC2] srv CPUUtilization > 80% (TagName: i-001)"),
            _alarm("[EC2] other CPUUtilization > 80% (TagName: i-002)"),
            _alarm("[RDS] db CPUUtilization > 80% (TagName: i-001)"),
        ])
        names = idx.find_names("i-001", "EC2")
        assert names == ["[EC2] srv CPUUtilization > 80% (TagName: i-001)"]

    def test_legacy_resource_id_prefix_match(self):
        idx = AlarmIndex([
            _alarm("i-001-CPU-prod"),
            _alarm("i-002-CPU-prod"),
        ])
        assert idx.find_names("i-001", "EC2") == ["i-001-CPU-prod"]

    def test_alb_short_id_and_legacy_full_arn_suffix(self):
        idx = AlarmIndex([
            _alarm("[ALB] web RequestCount > 10000 (TagName: my-alb/50dc6c495c0c9188)"),
            _alarm(f"[ALB] web ELB5XX > 50 (TagName: {ALB_ARN})"),
            _alarm("[ELB] web RequestCount > 10000 (TagName: my-alb/50dc6c495c0c9188)"),
        ])
        names = set(idx.find_names(ALB_ARN, "ALB"))
        # short_id 서픽스 + 레거시 Full_ARN 서픽스 + 레거시 [ELB] 프리픽스 모두 매칭
        assert len(names) == 3

    def test_nat_legacy_prefix(self):
        idx = AlarmIndex([
            _alarm("[NATGateway] gw PacketsDropCount > 1 (TagName: nat-001)"),
            _alarm("[NAT] gw PacketsDropCount > 1 (TagName: nat-001)"),
        ])
        assert len(idx.find_names("nat-001", "NAT")) == 2

    def test_region_filter(self):
        idx = AlarmIndex([
            _alarm("[EC2] srv CPUUtilization > 80% (TagName: i-001)", region="ap-northeast-2"),
        ])
        assert idx.find_names("i-001", "EC2", region="ap-northeast-2")
        assert idx.find_names("i-001", "EC2", region="us-west-2") == []
        # _region 주석 없는 알람은 리전 무관 취급
        idx2 = AlarmIndex([_alarm("[EC2] srv CPUUtilization > 80% (TagName: i-001)")])
        assert idx2.find_names("i-001", "EC2", region="us-west-2")

    def test_live_parity(self):
        """같은 알람 집합에 대해 라이브 검색과 동일한 결과를 내야 한다."""
        from common.alarm_search import _find_alarms_for_resource

        alarms = [
            _alarm("[EC2] srv CPUUtilization > 80% (TagName: i-001)"),
            _alarm("[EC2] other mem_used_percent > 80% (TagName: i-999)"),
            _alarm("i-001-CPU-prod"),
            _alarm("[RDS] db CPUUtilization > 80% (TagName: db-1)"),
        ]
        idx = AlarmIndex(alarms)

        mock_cw = MagicMock()

        def paginate(**kwargs):
            prefix = kwargs.get("AlarmNamePrefix", "")
            return [{
                "MetricAlarms": [
                    a for a in alarms if a["AlarmName"].startswith(prefix)
                ]
            }]

        mock_cw.get_paginator.return_value.paginate.side_effect = paginate
        live = _find_alarms_for_resource("i-001", "EC2", cw=mock_cw)
        assert set(idx.find_names("i-001", "EC2")) == set(live)


class TestDescribe:
    def test_describe_returns_dicts_without_api(self):
        a = _alarm("[EC2] srv CPUUtilization > 80% (TagName: i-001)", Threshold=80.0)
        idx = AlarmIndex([a])
        out = idx.describe(["[EC2] srv CPUUtilization > 80% (TagName: i-001)", "missing"])
        assert out == {"[EC2] srv CPUUtilization > 80% (TagName: i-001)": a}

    def test_describe_prefers_matching_region(self):
        a1 = _alarm("[EC2] srv CPUUtilization > 80% (TagName: i-001)", region="us-east-1", Threshold=70.0)
        a2 = _alarm("[EC2] srv CPUUtilization > 80% (TagName: i-001)", region="ap-northeast-2", Threshold=80.0)
        idx = AlarmIndex([a1, a2])
        out = idx.describe(
            ["[EC2] srv CPUUtilization > 80% (TagName: i-001)"],
            region="ap-northeast-2",
        )
        assert out["[EC2] srv CPUUtilization > 80% (TagName: i-001)"]["Threshold"] == 80.0


class TestSyncWithIndex:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv("SNS_TOPIC_ARN_ALERT", "arn:aws:sns:us-east-1:123:alert")
        from common._clients import _get_cw_client
        _get_cw_client.cache_clear()
        yield
        _get_cw_client.cache_clear()

    @staticmethod
    def _desc(mk):
        meta = json.dumps(
            {"metric_key": mk, "resource_id": "i-001", "resource_type": "EC2"},
            separators=(",", ":"),
        )
        return f"Auto-created | {meta}"

    def _managed_alarms(self):
        # (알람 이름, CW metric_name, 메타데이터 metric_key, 임계치)
        specs = [
            ("[EC2] srv CPUUtilization > 80% (TagName: i-001)", "CPUUtilization", "CPUUtilization", 80.0),
            ("[EC2] srv mem_used_percent > 80% (TagName: i-001)", "mem_used_percent", "mem_used_percent", 80.0),
            ("[EC2] srv disk_used_percent(/) > 80% (TagName: i-001)", "disk_used_percent", "Disk_root", 80.0),
            ("[EC2] srv StatusCheckFailed > 0 (TagName: i-001)", "StatusCheckFailed", "StatusCheckFailed", 0.0),
        ]
        alarms = []
        for name, cw_metric, metric_key, thr in specs:
            alarms.append(_alarm(
                name,
                MetricName=cw_metric,
                Threshold=thr,
                AlarmDescription=self._desc(metric_key),
                Dimensions=[{"Name": "path", "Value": "/"}] if "disk" in name else [],
                **alarm_config_fields("EC2", cw_metric),
            ))
        return alarms

    def test_sync_all_ok_makes_zero_describe_calls(self):
        """인덱스 경로에서는 기존 알람 조회에 API 콜이 없어야 한다."""
        idx = AlarmIndex(self._managed_alarms())
        mock_cw = MagicMock()

        with patch("common._clients._get_cw_client", return_value=mock_cw):
            result = sync_alarms_for_resource("i-001", "EC2", {}, alarm_index=idx)

        assert len(result["ok"]) == 4
        assert result["created"] == []
        assert result["updated"] == []
        mock_cw.describe_alarms.assert_not_called()
        mock_cw.get_paginator.assert_not_called()

    def test_sync_without_index_still_uses_live_path(self):
        mock_cw = MagicMock()

        def paginate(**kwargs):
            return [{"MetricAlarms": []}]

        mock_cw.get_paginator.return_value.paginate.side_effect = paginate
        with patch("common._clients._get_cw_client", return_value=mock_cw), \
             patch("common.alarm_manager.create_alarms_for_resource", return_value=[]) as mock_create:
            sync_alarms_for_resource("i-001", "EC2", {})

        assert mock_cw.get_paginator.called
        mock_create.assert_called_once()

    def test_global_service_bypasses_index(self):
        """CloudFront 알람은 us-east-1 — 인덱스 무시, 라이브 경로 사용."""
        idx = AlarmIndex([])  # 비어있는 인덱스: 인덱스를 썼다면 '알람 없음→전체 생성'이 됨
        mock_global_cw = MagicMock()
        mock_global_cw.get_paginator.return_value.paginate.return_value = [
            {"MetricAlarms": []}
        ]

        with patch("common._clients._get_cw_client_for_region", return_value=mock_global_cw), \
             patch("common.alarm_manager.create_alarms_for_resource", return_value=[]):
            sync_alarms_for_resource("DIST123", "CloudFront", {}, alarm_index=idx)

        # 인덱스가 아니라 us-east-1 클라이언트로 라이브 검색했는지 확인
        assert mock_global_cw.get_paginator.called
