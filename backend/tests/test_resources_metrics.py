"""
api_handler /resources/{id}/metrics 엔드포인트 + POST 알람 생성 일반화 테스트
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ── 공통 픽스처 ─────────────────────────────────────────────────────

def _event(method: str, path: str, body=None, qs=None, path_params=None) -> dict:
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "rawPath": path,
        "queryStringParameters": qs or {},
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body else None,
    }


def _alarm(name: str, metric: str = "CPUUtilization") -> dict:
    return {
        "AlarmName": name,
        "StateValue": "OK",
        "MetricName": metric,
        "Namespace": "AWS/EC2",
        "Threshold": 80.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "StateUpdatedTimestamp": datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        "Tags": [{"Key": "Severity", "Value": "SEV-3"}],
    }


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("API_STAGE", "dev")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-2")


# ── GET /resources/{id}/metrics ─────────────────────────────────────

class TestGetResourceMetrics:

    def test_returns_404_when_resource_has_no_alarms(self):
        """리소스에 매칭되는 알람이 없으면 404."""
        with patch("api_handler.routes.resources.list_alarms", return_value=[]):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/resources/nonexistent/metrics",
                       path_params={"id": "nonexistent"}),
                None,
            )
        assert resp["statusCode"] == 404
        assert json.loads(resp["body"])["code"] == "NOT_FOUND"

    def test_ec2_returns_namespace_metric_pairs(self):
        """EC2 리소스 → AWS/EC2 + CWAgent 두 namespace에서 list_metrics 호출 결과 결합."""
        mock_alarms = [_alarm("[EC2] server CPU >80% (TagName: i-001)")]
        mock_cw = MagicMock()
        # AWS/EC2 → CPUUtilization, NetworkIn
        # CWAgent → disk_used_percent (path=/, /data 두 개), mem_used_percent
        def list_metrics_side_effect(**kw):
            ns = kw["Namespace"]
            if ns == "AWS/EC2":
                return {"Metrics": [
                    {"MetricName": "CPUUtilization",
                     "Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]},
                    {"MetricName": "NetworkIn",
                     "Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]},
                ]}
            if ns == "CWAgent":
                return {"Metrics": [
                    {"MetricName": "disk_used_percent",
                     "Dimensions": [
                         {"Name": "InstanceId", "Value": "i-001"},
                         {"Name": "path", "Value": "/"},
                         {"Name": "device", "Value": "nvme0n1p1"},
                         {"Name": "fstype", "Value": "ext4"},
                     ]},
                    {"MetricName": "disk_used_percent",
                     "Dimensions": [
                         {"Name": "InstanceId", "Value": "i-001"},
                         {"Name": "path", "Value": "/data"},
                         {"Name": "device", "Value": "nvme1n1"},
                         {"Name": "fstype", "Value": "ext4"},
                     ]},
                    {"MetricName": "mem_used_percent",
                     "Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]},
                ]}
            return {"Metrics": []}
        mock_cw.list_metrics.side_effect = list_metrics_side_effect

        with patch("api_handler.routes.resources.list_alarms", return_value=mock_alarms), \
             patch("api_handler.routes.resources._get_cw_client", return_value=mock_cw):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/resources/i-001/metrics",
                       path_params={"id": "i-001"}),
                None,
            )

        assert resp["statusCode"] == 200
        items = json.loads(resp["body"])
        # disk_used_percent는 두 path가 있어도 1개로 묶여야 함
        names = [(m["namespace"], m["metric_name"]) for m in items]
        assert ("AWS/EC2", "CPUUtilization") in names
        assert ("AWS/EC2", "NetworkIn") in names
        assert ("CWAgent", "disk_used_percent") in names
        assert ("CWAgent", "mem_used_percent") in names
        # disk만 deduped
        disk_count = sum(1 for n, m in names if m == "disk_used_percent")
        assert disk_count == 1

    def test_disk_used_percent_has_needs_mount_path_true(self):
        """disk_used_percent 항목에는 needs_mount_path: true 플래그."""
        mock_alarms = [_alarm("[EC2] server CPU (TagName: i-001)")]
        mock_cw = MagicMock()
        mock_cw.list_metrics.side_effect = lambda **kw: {
            "Metrics": [
                {"MetricName": "disk_used_percent",
                 "Dimensions": [
                     {"Name": "InstanceId", "Value": "i-001"},
                     {"Name": "path", "Value": "/"},
                 ]},
            ] if kw["Namespace"] == "CWAgent" else []
        }

        with patch("api_handler.routes.resources.list_alarms", return_value=mock_alarms), \
             patch("api_handler.routes.resources._get_cw_client", return_value=mock_cw):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/resources/i-001/metrics",
                       path_params={"id": "i-001"}),
                None,
            )

        items = json.loads(resp["body"])
        disk = next((m for m in items if m["metric_name"] == "disk_used_percent"), None)
        assert disk is not None
        assert disk["needs_mount_path"] is True
        assert disk["unit"] == "%"
        assert disk["direction"] == ">"

    def test_other_metrics_have_needs_mount_path_false(self):
        """disk가 아닌 메트릭은 needs_mount_path: false."""
        mock_alarms = [_alarm("[EC2] server CPU (TagName: i-001)")]
        mock_cw = MagicMock()
        mock_cw.list_metrics.side_effect = lambda **kw: {
            "Metrics": [
                {"MetricName": "CPUUtilization",
                 "Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]},
            ] if kw["Namespace"] == "AWS/EC2" else []
        }

        with patch("api_handler.routes.resources.list_alarms", return_value=mock_alarms), \
             patch("api_handler.routes.resources._get_cw_client", return_value=mock_cw):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/resources/i-001/metrics",
                       path_params={"id": "i-001"}),
                None,
            )

        items = json.loads(resp["body"])
        cpu = next((m for m in items if m["metric_name"] == "CPUUtilization"), None)
        assert cpu is not None
        assert cpu["needs_mount_path"] is False

    def test_unregistered_metric_returns_unit_null(self):
        """_METRIC_DISPLAY에 없는 메트릭도 통과(unit: null, direction: '>')."""
        mock_alarms = [_alarm("[EC2] server CPU (TagName: i-001)")]
        mock_cw = MagicMock()
        mock_cw.list_metrics.side_effect = lambda **kw: {
            "Metrics": [
                {"MetricName": "MyCustomMetric",
                 "Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]},
            ] if kw["Namespace"] == "AWS/EC2" else []
        }

        with patch("api_handler.routes.resources.list_alarms", return_value=mock_alarms), \
             patch("api_handler.routes.resources._get_cw_client", return_value=mock_cw):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/resources/i-001/metrics",
                       path_params={"id": "i-001"}),
                None,
            )

        items = json.loads(resp["body"])
        custom = next((m for m in items if m["metric_name"] == "MyCustomMetric"), None)
        assert custom is not None
        assert custom["unit"] is None
        assert custom["direction"] == ">"

    def test_rds_uses_db_instance_identifier_dimension(self):
        """RDS 리소스 → DBInstanceIdentifier 디멘션으로 list_metrics 호출."""
        mock_alarms = [_alarm("[RDS] db CPU (TagName: db-001)")]
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {"Metrics": []}

        with patch("api_handler.routes.resources.list_alarms", return_value=mock_alarms), \
             patch("api_handler.routes.resources._get_cw_client", return_value=mock_cw):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/resources/db-001/metrics",
                       path_params={"id": "db-001"}),
                None,
            )

        assert resp["statusCode"] == 200
        # list_metrics가 DBInstanceIdentifier 디멘션으로 호출됐는지 확인
        calls = mock_cw.list_metrics.call_args_list
        assert any(
            any(d.get("Name") == "DBInstanceIdentifier"
                for d in (call.kwargs.get("Dimensions") or []))
            for call in calls
        )

    def test_paginates_via_next_token(self):
        """list_metrics에 NextToken이 있으면 다음 페이지를 이어 호출."""
        mock_alarms = [_alarm("[EC2] s CPU (TagName: i-001)")]
        mock_cw = MagicMock()
        # 첫 호출엔 NextToken 포함, 두 번째엔 없음
        responses_by_ns = {
            "AWS/EC2": [
                {"Metrics": [{"MetricName": "CPUUtilization",
                              "Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}],
                 "NextToken": "tok-1"},
                {"Metrics": [{"MetricName": "NetworkIn",
                              "Dimensions": [{"Name": "InstanceId", "Value": "i-001"}]}]},
            ],
            "CWAgent": [{"Metrics": []}],
        }

        def list_metrics(**kw):
            ns = kw["Namespace"]
            queue = responses_by_ns.get(ns, [{"Metrics": []}])
            return queue.pop(0) if queue else {"Metrics": []}

        mock_cw.list_metrics.side_effect = list_metrics

        with patch("api_handler.routes.resources.list_alarms", return_value=mock_alarms), \
             patch("api_handler.routes.resources._get_cw_client", return_value=mock_cw):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/resources/i-001/metrics",
                       path_params={"id": "i-001"}),
                None,
            )

        items = json.loads(resp["body"])
        names = {m["metric_name"] for m in items}
        assert {"CPUUtilization", "NetworkIn"}.issubset(names)


# ── POST /resources/{id}/alarms (일반화) ─────────────────────────────

class TestCreateResourceAlarmGeneralized:

    def test_disk_used_percent_still_requires_mount_path(self):
        """disk_used_percent 알람은 mount_path 없으면 400."""
        with patch("api_handler.routes.resources.list_alarms",
                   return_value=[_alarm("[EC2] s CPU (TagName: i-001)")]):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("POST", "/resources/i-001/alarms",
                       body={"metric_name": "disk_used_percent", "threshold": 80},
                       path_params={"id": "i-001"}),
                None,
            )
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["code"] == "MISSING_PARAM"

    def test_mem_used_percent_creates_cwagent_alarm(self):
        """mem_used_percent → namespace=CWAgent + InstanceId 디멘션 자동 해석."""
        mock_alarms = [_alarm("[EC2] s CPU (TagName: i-001)")]
        mock_cw = MagicMock()
        mock_cw.put_metric_alarm.return_value = {}

        # _resolve_metric_dimensions가 CWAgent / InstanceId 반환하도록 모킹
        with patch("api_handler.routes.resources.list_alarms", return_value=mock_alarms), \
             patch("api_handler.routes.resources._get_cw_client", return_value=mock_cw), \
             patch("api_handler.routes.resources._get_instance_name", return_value="my-server"), \
             patch("common.dimension_builder._resolve_metric_dimensions",
                   return_value=("CWAgent",
                                 [{"Name": "InstanceId", "Value": "i-001"}])):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("POST", "/resources/i-001/alarms",
                       body={"metric_name": "mem_used_percent",
                             "threshold": 85, "severity": "SEV-3"},
                       path_params={"id": "i-001"}),
                None,
            )

        assert resp["statusCode"] == 201, resp["body"]
        # put_metric_alarm 호출 인자 검증
        kwargs = mock_cw.put_metric_alarm.call_args.kwargs
        assert kwargs["Namespace"] == "CWAgent"
        assert kwargs["MetricName"] == "mem_used_percent"
        assert {"Name": "InstanceId", "Value": "i-001"} in kwargs["Dimensions"]
        # 알람 이름은 _pretty_alarm_name 포맷 (TagName 포함)
        assert "(TagName: i-001)" in kwargs["AlarmName"]
        assert kwargs["AlarmName"].startswith("[EC2]")

    def test_unresolvable_metric_returns_404(self):
        """list_metrics에서 못 찾은 메트릭은 404 반환."""
        mock_alarms = [_alarm("[EC2] s CPU (TagName: i-001)")]
        mock_cw = MagicMock()

        with patch("api_handler.routes.resources.list_alarms", return_value=mock_alarms), \
             patch("api_handler.routes.resources._get_cw_client", return_value=mock_cw), \
             patch("api_handler.routes.resources._get_instance_name", return_value=""), \
             patch("common.dimension_builder._resolve_metric_dimensions", return_value=None):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("POST", "/resources/i-001/alarms",
                       body={"metric_name": "MissingMetric", "threshold": 50},
                       path_params={"id": "i-001"}),
                None,
            )
        assert resp["statusCode"] == 404
        assert json.loads(resp["body"])["code"] == "NO_METRIC"

    def test_disk_alarm_path_dim_unchanged(self):
        """disk_used_percent 알람은 기존 동작 유지 (CWAgent + path/device/fstype 디멘션)."""
        mock_alarms = [_alarm("[EC2] s CPU (TagName: i-001)")]
        mock_cw = MagicMock()
        mock_cw.list_metrics.return_value = {
            "Metrics": [
                {"MetricName": "disk_used_percent",
                 "Dimensions": [
                     {"Name": "InstanceId", "Value": "i-001"},
                     {"Name": "path", "Value": "/data"},
                     {"Name": "device", "Value": "nvme1n1"},
                     {"Name": "fstype", "Value": "ext4"},
                 ]},
            ]
        }
        mock_cw.put_metric_alarm.return_value = {}

        with patch("api_handler.routes.resources.list_alarms", return_value=mock_alarms), \
             patch("api_handler.routes.resources._get_cw_client", return_value=mock_cw), \
             patch("api_handler.routes.resources._get_instance_name", return_value="my-server"):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("POST", "/resources/i-001/alarms",
                       body={"metric_name": "disk_used_percent",
                             "threshold": 80, "mount_path": "/data"},
                       path_params={"id": "i-001"}),
                None,
            )

        assert resp["statusCode"] == 201, resp["body"]
        kwargs = mock_cw.put_metric_alarm.call_args.kwargs
        assert kwargs["Namespace"] == "CWAgent"
        # path/device/fstype/InstanceId 디멘션 모두 포함
        dim_names = {d["Name"] for d in kwargs["Dimensions"]}
        assert {"InstanceId", "path", "device", "fstype"}.issubset(dim_names)
