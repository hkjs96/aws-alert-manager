"""
api_handler 라우트 단위 테스트 — alarms / resources / bulk / jobs / dashboard

검증 범위:
- GET /alarms, GET /alarms/summary
- GET /resources, POST /resources/sync, GET /resources/{id}, GET /resources/{id}/alarms
- POST /bulk/monitoring
- GET /jobs/{id}
- GET /dashboard/recent-alarms
- cw_helper: extract_resource_from_alarm, get_resources_from_alarms
"""

import json
import os
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


def _alarm(name: str, state: str = "OK", metric: str = "CPUUtilization",
           threshold: float = 80.0, severity: str = "SEV-3") -> dict:
    return {
        "AlarmName": name,
        "StateValue": state,
        "MetricName": metric,
        "Namespace": "AWS/EC2",
        "Threshold": threshold,
        "ComparisonOperator": "GreaterThanThreshold",
        "StateUpdatedTimestamp": datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        "Tags": [{"Key": "Severity", "Value": severity}],
    }


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("CUSTOMERS_TABLE", "test-customers")
    monkeypatch.setenv("ACCOUNTS_TABLE", "test-accounts")
    monkeypatch.setenv("THRESHOLD_OVERRIDES_TABLE", "test-thresholds")
    monkeypatch.setenv("JOB_STATUS_TABLE", "test-jobs")
    monkeypatch.setenv("BULK_OPERATION_QUEUE_URL", "https://sqs.ap-northeast-2.amazonaws.com/123/bulk.fifo")
    monkeypatch.setenv("API_STAGE", "dev")


# ── /alarms ──────────────────────────────────────────────────────────

class TestAlarms:

    def test_list_alarms_returns_paginated_items(self):
        mock_alarms = [
            _alarm(f"[EC2] server CPU >80% (TagName: i-00{i})", state="OK")
            for i in range(3)
        ]
        with patch("api_handler.routes.alarms.list_alarms", return_value=mock_alarms):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(_event("GET", "/alarms"), None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["total"] == 3
        assert len(body["items"]) == 3
        assert body["page"] == 1

    def test_list_alarms_page_size_limit(self):
        mock_alarms = [
            _alarm(f"[EC2] server CPU >80% (TagName: i-{i:03d})")
            for i in range(50)
        ]
        with patch("api_handler.routes.alarms.list_alarms", return_value=mock_alarms):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(_event("GET", "/alarms", qs={"page_size": "200"}), None)

        body = json.loads(resp["body"])
        assert body["page_size"] == 100  # max 100으로 클램프

    def test_list_alarms_pagination(self):
        mock_alarms = [
            _alarm(f"[EC2] server CPU >80% (TagName: i-{i:03d})")
            for i in range(30)
        ]
        with patch("api_handler.routes.alarms.list_alarms", return_value=mock_alarms):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/alarms", qs={"page": "2", "page_size": "10"}), None
            )

        body = json.loads(resp["body"])
        assert body["total"] == 30
        assert len(body["items"]) == 10
        assert body["page"] == 2

    def test_list_alarms_extracts_resource_id_and_type(self):
        mock_alarms = [_alarm("[EC2] prod-ec2-api CPU >80% (TagName: i-0abc1234)")]
        with patch("api_handler.routes.alarms.list_alarms", return_value=mock_alarms):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(_event("GET", "/alarms"), None)

        item = json.loads(resp["body"])["items"][0]
        assert item["resource"] == "i-0abc1234"
        assert item["type"] == "EC2"
        assert item["severity"] == "SEV-3"

    def test_list_alarms_cw_error_returns_500(self):
        from botocore.exceptions import ClientError
        err = ClientError({"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "DescribeAlarms")
        with patch("api_handler.routes.alarms.list_alarms", side_effect=err):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(_event("GET", "/alarms"), None)

        assert resp["statusCode"] == 500
        assert json.loads(resp["body"])["code"] == "CW_ERROR"

    def test_alarm_summary_counts_by_state(self):
        mock_alarms = [
            _alarm("[EC2] a CPU (TagName: i-001)", state="ALARM"),
            _alarm("[EC2] b CPU (TagName: i-002)", state="OK"),
            _alarm("[RDS] c CPU (TagName: db-001)", state="INSUFFICIENT_DATA"),
            _alarm("[RDS] d CPU (TagName: db-002)", state="ALARM"),
        ]
        with patch("api_handler.routes.alarms.list_alarms", return_value=mock_alarms):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(_event("GET", "/alarms/summary"), None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["total"] == 4
        assert body["by_state"]["ALARM"] == 2
        assert body["by_state"]["OK"] == 1
        assert body["by_state"]["INSUFFICIENT_DATA"] == 1


# ── /resources ────────────────────────────────────────────────────────

class TestResources:

    def test_list_resources_returns_paginated_result(self):
        mock_alarms = [
            _alarm("[EC2] server CPU >80% (TagName: i-001)"),
            _alarm("[EC2] server Mem >80% (TagName: i-001)"),
            _alarm("[RDS] db CPU >80% (TagName: db-001)"),
        ]
        with patch("api_handler.cw_helper.list_alarms", return_value=mock_alarms):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(_event("GET", "/resources"), None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["total"] == 2  # i-001과 db-001 두 리소스

    def test_list_resources_filters_by_type(self):
        mock_alarms = [
            _alarm("[EC2] server CPU (TagName: i-001)"),
            _alarm("[RDS] db CPU (TagName: db-001)"),
        ]
        with patch("api_handler.cw_helper.list_alarms", return_value=mock_alarms):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/resources", qs={"resource_type": "EC2"}), None
            )

        body = json.loads(resp["body"])
        assert body["total"] == 1
        assert body["items"][0]["type"] == "EC2"

    def test_list_resources_filters_by_search(self):
        mock_alarms = [
            _alarm("[EC2] server CPU (TagName: i-001)"),
            _alarm("[RDS] db CPU (TagName: prod-rds-01)"),
        ]
        with patch("api_handler.cw_helper.list_alarms", return_value=mock_alarms):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/resources", qs={"search": "prod"}), None
            )

        body = json.loads(resp["body"])
        assert body["total"] == 1
        assert "prod" in body["items"][0]["id"]

    def test_sync_resources_returns_202_like_response(self):
        from api_handler.lambda_handler import lambda_handler
        resp = lambda_handler(_event("POST", "/resources/sync"), None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert "message" in body

    def test_get_resource_returns_detail(self):
        mock_alarms = [
            _alarm("[EC2] server CPU >80% (TagName: i-001)"),
            _alarm("[EC2] server Mem >80% (TagName: i-001)", state="ALARM"),
        ]
        with patch("api_handler.routes.resources.list_alarms", return_value=mock_alarms):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/resources/i-001", path_params={"id": "i-001"}), None
            )

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["id"] == "i-001"
        assert body["type"] == "EC2"
        assert body["alarm_count"] == 2
        assert body["alarms"]["critical"] == 1

    def test_get_resource_not_found_returns_404(self):
        with patch("api_handler.routes.resources.list_alarms", return_value=[]):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/resources/nonexistent", path_params={"id": "nonexistent"}), None
            )

        assert resp["statusCode"] == 404
        assert json.loads(resp["body"])["code"] == "NOT_FOUND"

    def test_get_resource_alarms_lists_configs(self):
        mock_alarms = [
            _alarm("[EC2] server CPU >80% (TagName: i-001)", metric="CPUUtilization"),
            _alarm("[EC2] server Mem >80% (TagName: i-001)", metric="mem_used_percent"),
        ]
        with patch("api_handler.routes.resources.list_alarms", return_value=mock_alarms):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/resources/i-001/alarms", path_params={"id": "i-001"}), None
            )

        assert resp["statusCode"] == 200
        configs = json.loads(resp["body"])
        assert len(configs) == 2
        metrics = {c["metric_name"] for c in configs}
        assert metrics == {"CPUUtilization", "mem_used_percent"}

    def test_update_resource_alarms_updates_existing_alarm(self):
        mock_cw = MagicMock()
        mock_alarms = [{
            **_alarm("[EC2] server CPU >80% (TagName: i-001)", metric="CPUUtilization"),
            "AlarmArn": "arn:aws:cloudwatch:us-east-1:123456789012:alarm:test",
            "Dimensions": [{"Name": "InstanceId", "Value": "i-001"}],
            "Period": 300,
            "EvaluationPeriods": 1,
            "ActionsEnabled": True,
            "AlarmActions": ["arn:aws:sns:us-east-1:123456789012:alerts"],
            "OKActions": [],
            "InsufficientDataActions": [],
            "TreatMissingData": "notBreaching",
            "Statistic": "Average",
        }]

        with patch("api_handler.routes.resources.list_alarms", return_value=mock_alarms), \
             patch("api_handler.routes.resources._get_cw_client_for_region", return_value=mock_cw):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("PUT", "/resources/i-001/alarms",
                       body={"configs": [{
                           "metric_key": "CPUUtilization",
                           "threshold": 70,
                           "monitoring": True,
                           "unit": "Percent",
                           "direction": ">",
                           "severity": "SEV-4",
                       }]},
                       path_params={"id": "i-001"}),
                None,
            )

        assert resp["statusCode"] == 200, resp["body"]
        body = json.loads(resp["body"])
        assert body["completed_count"] == 1
        kwargs = mock_cw.put_metric_alarm.call_args.kwargs
        assert kwargs["AlarmName"] == "[EC2] server CPU >80% (TagName: i-001)"
        assert kwargs["Threshold"] == 70.0
        assert kwargs["ComparisonOperator"] == "GreaterThanThreshold"
        assert kwargs["Dimensions"] == [{"Name": "InstanceId", "Value": "i-001"}]
        assert kwargs["AlarmActions"] == ["arn:aws:sns:us-east-1:123456789012:alerts"]
        mock_cw.tag_resource.assert_called_once()

    def test_update_resource_alarms_returns_404_for_missing_metric(self):
        mock_alarms = [_alarm("[EC2] server CPU >80% (TagName: i-001)", metric="CPUUtilization")]
        with patch("api_handler.routes.resources.list_alarms", return_value=mock_alarms):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("PUT", "/resources/i-001/alarms",
                       body={"configs": [{"metric_key": "mem_used_percent", "threshold": 80}]},
                       path_params={"id": "i-001"}),
                None,
            )

        assert resp["statusCode"] == 404
        assert json.loads(resp["body"])["code"] == "NOT_FOUND"


# ── /bulk ─────────────────────────────────────────────────────────────

class TestBulk:

    def test_bulk_monitoring_validates_required_fields(self):
        from api_handler.lambda_handler import lambda_handler
        resp = lambda_handler(
            _event("POST", "/bulk/monitoring", body={"resource_type": "EC2"}), None
        )

        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["code"] == "BAD_REQUEST"

    def test_bulk_monitoring_enqueues_and_returns_job_id(self):
        mock_table = MagicMock()
        mock_table.put_item.return_value = {}
        mock_sqs = MagicMock()
        mock_sqs.send_message.return_value = {}

        with patch("api_handler.routes.bulk.job_status_table", return_value=mock_table):
            with patch("api_handler.routes.bulk._get_sqs", return_value=mock_sqs):
                from api_handler.lambda_handler import lambda_handler
                resp = lambda_handler(
                    _event("POST", "/bulk/monitoring", body={
                        "resource_ids": ["i-001", "i-002"],
                        "resource_type": "EC2",
                        "monitoring": True,
                    }), None
                )

        assert resp["statusCode"] == 202
        body = json.loads(resp["body"])
        assert body["job_id"].startswith("job-")
        assert body["total"] == 2
        assert body["status"] == "pending"
        assert mock_sqs.send_message.call_count == 2

    def test_bulk_monitoring_handles_invalid_json(self):
        from api_handler.lambda_handler import lambda_handler
        event = _event("POST", "/bulk/monitoring")
        event["body"] = "{invalid json"
        resp = lambda_handler(event, None)

        assert resp["statusCode"] == 400

    def test_bulk_monitoring_all_sqs_fail_returns_500(self):
        from botocore.exceptions import ClientError
        mock_table = MagicMock()
        mock_table.put_item.return_value = {}
        mock_sqs = MagicMock()
        mock_sqs.send_message.side_effect = ClientError(
            {"Error": {"Code": "QueueDoesNotExist", "Message": "Queue not found"}},
            "SendMessage",
        )

        with patch("api_handler.routes.bulk.job_status_table", return_value=mock_table):
            with patch("api_handler.routes.bulk._get_sqs", return_value=mock_sqs):
                from api_handler.lambda_handler import lambda_handler
                resp = lambda_handler(
                    _event("POST", "/bulk/monitoring", body={
                        "resource_ids": ["i-001"],
                        "resource_type": "EC2",
                    }), None
                )

        assert resp["statusCode"] == 500
        assert json.loads(resp["body"])["code"] == "QUEUE_ERROR"


# ── /jobs ─────────────────────────────────────────────────────────────

class TestJobs:

    def test_get_job_returns_item(self):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {
            "Item": {
                "job_id": "job-abc123",
                "status": "completed",
                "total_count": 5,
                "completed_count": 5,
                "failed_count": 0,
            }
        }
        with patch("api_handler.routes.jobs.job_status_table", return_value=mock_table):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/jobs/job-abc123", path_params={"id": "job-abc123"}), None
            )

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["job_id"] == "job-abc123"
        assert body["status"] == "completed"

    def test_get_job_not_found_returns_404(self):
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}

        with patch("api_handler.routes.jobs.job_status_table", return_value=mock_table):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/jobs/nonexistent", path_params={"id": "nonexistent"}), None
            )

        assert resp["statusCode"] == 404
        assert json.loads(resp["body"])["code"] == "NOT_FOUND"

    def test_get_job_missing_id_returns_400(self):
        from api_handler.lambda_handler import lambda_handler
        resp = lambda_handler(_event("GET", "/jobs/"), None)

        assert resp["statusCode"] in (400, 404)


# ── /dashboard/recent-alarms ──────────────────────────────────────────

class TestDashboardRecentAlarms:

    def test_recent_alarms_returns_alarm_items(self):
        mock_alarms = [
            _alarm("[EC2] server CPU >80% (TagName: i-001)", state="ALARM"),
            _alarm("[RDS] db free <2GB (TagName: db-01)", state="ALARM"),
        ]
        with patch("api_handler.routes.dashboard.list_alarms", return_value=mock_alarms):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(_event("GET", "/dashboard/recent-alarms"), None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["total"] == 2
        items = body["items"]
        assert all("alarm_name" in item for item in items)
        assert all("resource" in item for item in items)
        assert all("severity" in item for item in items)

    def test_recent_alarms_pagination(self):
        mock_alarms = [
            _alarm(f"[EC2] s CPU (TagName: i-{i:03d})", state="ALARM")
            for i in range(15)
        ]
        with patch("api_handler.routes.dashboard.list_alarms", return_value=mock_alarms):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/dashboard/recent-alarms", qs={"page": "2", "page_size": "5"}), None
            )

        body = json.loads(resp["body"])
        assert body["total"] == 15
        assert len(body["items"]) == 5

    def test_recent_alarms_page_size_clamped_to_50(self):
        mock_alarms = [
            _alarm(f"[EC2] s CPU (TagName: i-{i:03d})", state="ALARM")
            for i in range(100)
        ]
        with patch("api_handler.routes.dashboard.list_alarms", return_value=mock_alarms):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(
                _event("GET", "/dashboard/recent-alarms", qs={"page_size": "200"}), None
            )

        body = json.loads(resp["body"])
        assert body["page_size"] == 50

    def test_recent_alarms_cw_error_returns_500(self):
        from botocore.exceptions import ClientError
        err = ClientError({"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "DescribeAlarms")
        with patch("api_handler.routes.dashboard.list_alarms", side_effect=err):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(_event("GET", "/dashboard/recent-alarms"), None)

        assert resp["statusCode"] == 500


# ── cw_helper ─────────────────────────────────────────────────────────

class TestCwHelper:

    def test_extract_resource_from_alarm_valid_name(self):
        from api_handler.cw_helper import extract_resource_from_alarm
        result = extract_resource_from_alarm("[EC2] server CPU >80% (TagName: i-0abc1234)")
        assert result == ("EC2", "i-0abc1234")

    def test_extract_resource_from_alarm_invalid_name(self):
        from api_handler.cw_helper import extract_resource_from_alarm
        assert extract_resource_from_alarm("random-alarm-name") is None
        assert extract_resource_from_alarm("") is None

    def test_get_resources_from_alarms_deduplicates(self):
        mock_alarms = [
            _alarm("[EC2] server CPU >80% (TagName: i-001)"),
            _alarm("[EC2] server Mem >80% (TagName: i-001)"),
            _alarm("[EC2] server Disk >80% (TagName: i-001)"),
        ]
        with patch("api_handler.cw_helper.list_alarms", return_value=mock_alarms):
            from api_handler.cw_helper import get_resources_from_alarms
            result = get_resources_from_alarms()

        assert result["total"] == 1
        assert result["items"][0]["id"] == "i-001"

    def test_get_resources_from_alarms_counts_critical_alarms(self):
        mock_alarms = [
            {**_alarm("[EC2] a CPU (TagName: i-001)", state="ALARM"),
             "Tags": [{"Key": "Severity", "Value": "SEV-1"}]},
            {**_alarm("[EC2] b Mem (TagName: i-001)", state="ALARM"),
             "Tags": [{"Key": "Severity", "Value": "SEV-4"}]},
        ]
        with patch("api_handler.cw_helper.list_alarms", return_value=mock_alarms):
            from api_handler.cw_helper import get_resources_from_alarms
            result = get_resources_from_alarms()

        resource = result["items"][0]
        assert resource["alarms"]["critical"] == 1
        assert resource["alarms"]["warning"] == 1

    def test_get_resources_from_alarms_cw_error_returns_empty(self):
        from botocore.exceptions import ClientError
        err = ClientError({"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "DescribeAlarms")
        with patch("api_handler.cw_helper.list_alarms", side_effect=err):
            from api_handler.cw_helper import get_resources_from_alarms
            result = get_resources_from_alarms()

        assert result["items"] == []
        assert result["total"] == 0

    def test_list_alarms_uses_registered_account_regions(self):
        fake_cw = MagicMock()
        fake_cw.get_paginator.return_value.paginate.return_value = [{
            "MetricAlarms": [
                _alarm("[EC2] server CPU (TagName: i-001)", state="OK"),
            ],
        }]
        fake_sts = MagicMock()
        fake_sts.get_caller_identity.return_value = {"Account": "949501913924"}
        fake_sts.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "AKIA_TEST",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
            },
        }

        def client_side_effect(service, **kwargs):
            if service == "sts":
                return fake_sts
            if service == "cloudwatch":
                assert kwargs["region_name"] == "ap-northeast-2"
                assert kwargs["aws_access_key_id"] == "AKIA_TEST"
                return fake_cw
            raise AssertionError(service)

        with patch("api_handler.db.accounts_table", return_value=MagicMock()):
            with patch("api_handler.db.scan_all", return_value=[{
                "account_id": "111111111111",
                "role_arn": "arn:aws:iam::111111111111:role/Monitor",
                "regions": ["ap-northeast-2"],
            }]):
                with patch("api_handler.cw_helper.boto3.client", side_effect=client_side_effect):
                    from api_handler.cw_helper import list_alarms
                    alarms = list_alarms()

        assert len(alarms) == 1
        fake_sts.assume_role.assert_called_once()
        fake_cw.get_paginator.assert_called_once_with("describe_alarms")

    def test_list_alarms_skips_assume_role_for_current_account(self):
        fake_cw = MagicMock()
        fake_cw.get_paginator.return_value.paginate.return_value = [{
            "MetricAlarms": [
                _alarm("[EC2] server CPU (TagName: i-001)", state="OK"),
            ],
        }]
        fake_sts = MagicMock()
        fake_sts.get_caller_identity.return_value = {"Account": "949501913924"}

        def client_side_effect(service, **kwargs):
            if service == "sts":
                return fake_sts
            if service == "cloudwatch":
                assert kwargs["region_name"] == "ap-northeast-2"
                assert "aws_access_key_id" not in kwargs
                return fake_cw
            raise AssertionError(service)

        from api_handler.cw_helper import _get_current_account_id
        _get_current_account_id.cache_clear()

        with patch("api_handler.db.accounts_table", return_value=MagicMock()):
            with patch("api_handler.db.scan_all", return_value=[{
                "account_id": "949501913924",
                "role_arn": "arn:aws:iam::949501913924:role/aws-monitoring-engine-api-handler-role-dev",
                "regions": ["ap-northeast-2"],
            }]):
                with patch("api_handler.cw_helper.boto3.client", side_effect=client_side_effect):
                    from api_handler.cw_helper import list_alarms
                    alarms = list_alarms()

        assert len(alarms) == 1
        fake_sts.assume_role.assert_not_called()
        fake_cw.get_paginator.assert_called_once_with("describe_alarms")
