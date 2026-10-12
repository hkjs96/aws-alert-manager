"""리전 자동 탐지 (2026-10) — 고객이 등록하지 않은 리전에 리소스가 있으면 알아챈다."""

import json
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError, EndpointConnectionError


def _sessions(by_region):
    """region → 결과(list = 리소스 목록, Exception = 실패)인 Session 목."""
    def make_session(**_kw):
        session = MagicMock()

        def client(_name, region_name, **_k):
            c = MagicMock()
            outcome = by_region.get(region_name, [])
            if isinstance(outcome, Exception):
                c.get_resources.side_effect = outcome
            else:
                c.get_resources.return_value = {"ResourceTagMappingList": outcome}
            return c
        session.client.side_effect = client
        return session
    return make_session


class TestDetectRegions:
    def test_regions_with_resources_in_candidate_order(self):
        from common import region_discovery as rd
        denied = ClientError({"Error": {"Code": "UnrecognizedClientException", "Message": "opt-in"}}, "GetResources")
        by_region = {"us-east-1": [{"ResourceARN": "a"}], "ap-northeast-2": [{"ResourceARN": "b"}],
                     "ap-east-1": denied, "me-south-1": EndpointConnectionError(endpoint_url="x")}
        with patch("common.region_discovery.boto3.session.Session", side_effect=_sessions(by_region)):
            assert rd.detect_regions({}) == ["us-east-1", "ap-northeast-2"]

    def test_unregistered_excludes_registered_and_virginia(self):
        from common.region_discovery import unregistered_regions
        assert unregistered_regions(["us-east-1", "ap-northeast-2", "ap-northeast-1"], ["ap-northeast-2"]) == \
            ["ap-northeast-1"]


class TestConnectionTestReportsRegions:
    def test_unregistered_regions_are_reported_and_detected_saved(self):
        from api_handler.routes import accounts
        item = {"customer_id": "c", "account_id": "771283576189", "role_arn": "arn:r", "regions": ["ap-northeast-2"]}
        table = MagicMock()
        table.get_item.return_value = {"Item": item}
        with patch.object(accounts, "accounts_table", return_value=table), \
             patch.object(accounts, "_probe_regions", return_value=("connected", [], "")), \
             patch.object(accounts, "check_alert_forwarding", return_value={"status": "ok"}), \
             patch.object(accounts, "_assume_role_kwargs", return_value={}), \
             patch.object(accounts, "detect_regions", return_value=["us-east-1", "ap-northeast-2", "ap-northeast-1"]):
            resp = accounts.test_connection({"pathParameters": {"id": "771283576189"},
                                             "queryStringParameters": {"customer_id": "c"}})
        body = json.loads(resp["body"])
        assert body["detected_regions"] == ["us-east-1", "ap-northeast-2", "ap-northeast-1"]
        assert body["unregistered_regions"] == ["ap-northeast-1"]
        assert table.update_item.call_args.kwargs["ExpressionAttributeValues"][":d"] == body["detected_regions"]

    def test_failed_connection_skips_detection(self):
        from api_handler.routes import accounts
        table = MagicMock()
        table.get_item.return_value = {"Item": {"customer_id": "c", "account_id": "1", "role_arn": "arn:r"}}
        with patch.object(accounts, "accounts_table", return_value=table), \
             patch.object(accounts, "_probe_regions", return_value=("failed", [], "denied")), \
             patch.object(accounts, "check_alert_forwarding", return_value={"status": "ok"}), \
             patch.object(accounts, "detect_regions") as detect:
            body = json.loads(accounts.test_connection({"pathParameters": {"id": "1"},
                                                        "queryStringParameters": {"customer_id": "c"}})["body"])
        detect.assert_not_called()
        assert "unregistered_regions" not in body


class TestUpdateRegions:
    def _call(self, regions, table):
        from api_handler.routes import accounts
        with patch.object(accounts, "accounts_table", return_value=table):
            return accounts.update_account_regions({
                "pathParameters": {"id": "771283576189"}, "queryStringParameters": {"customer_id": "c"},
                "body": json.dumps({"regions": regions})})

    def test_saves_deduplicated_regions(self):
        table = MagicMock()
        table.update_item.return_value = {"Attributes": {"regions": ["ap-northeast-2", "ap-northeast-1"]}}
        resp = self._call(["ap-northeast-2", "ap-northeast-1", "ap-northeast-2"], table)
        assert resp["statusCode"] == 200
        assert table.update_item.call_args.kwargs["ExpressionAttributeValues"][":r"] == \
            ["ap-northeast-2", "ap-northeast-1"]

    def test_rejects_empty_and_unknown(self):
        table = MagicMock()
        assert self._call([], table)["statusCode"] == 400
        assert self._call(["mars-1"], table)["statusCode"] == 400
        table.update_item.assert_not_called()

    def test_missing_account_is_404(self):
        table = MagicMock()
        table.update_item.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}}, "UpdateItem")
        assert self._call(["ap-northeast-2"], table)["statusCode"] == 404


class TestDailyNotice:
    def test_alerts_with_the_missing_regions(self):
        from daily_monitor import lambda_handler as lh
        with patch.object(lh, "detect_regions", return_value=["ap-northeast-2", "ap-northeast-1"]), \
             patch.object(lh, "send_error_alert") as alert:
            assert lh._notify_unregistered_regions("1", None, ["ap-northeast-2"]) == ["ap-northeast-1"]
        assert "ap-northeast-1" in str(alert.call_args.kwargs["error"])

    def test_nothing_missing_no_alert(self):
        from daily_monitor import lambda_handler as lh
        with patch.object(lh, "detect_regions", return_value=["ap-northeast-2", "us-east-1"]), \
             patch.object(lh, "send_error_alert") as alert:
            assert lh._notify_unregistered_regions("1", None, ["ap-northeast-2"]) == []
        alert.assert_not_called()
