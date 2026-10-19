"""리전 자동 탐지 (2026-10) — 고객이 등록하지 않은 리전에 리소스가 있으면 알아챈다."""

import json
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError, EndpointConnectionError

from common.region_discovery import Detection


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
            got = rd.detect_regions({})
        assert got.regions == ["us-east-1", "ap-northeast-2"] and got.unchecked == []

    def test_deadline_returns_what_finished_and_names_the_rest(self):
        import threading
        from common import region_discovery as rd
        release = threading.Event()
        session = MagicMock()

        def client(_name, region_name, **_k):
            c = MagicMock()
            if region_name == "ap-northeast-2":
                c.get_resources.return_value = {"ResourceTagMappingList": [{"ResourceARN": "b"}]}
            else:
                c.get_resources.side_effect = lambda **_: release.wait(5) and {"ResourceTagMappingList": []}
            return c
        session.client.side_effect = client
        with patch("common.region_discovery.boto3.session.Session", return_value=session):
            got = rd.detect_regions({}, regions=("ap-northeast-2", "eu-west-1"), deadline=0.5)
        release.set()
        assert got.regions == ["ap-northeast-2"] and got.unchecked == ["eu-west-1"]

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
             patch.object(accounts, "detect_regions",
                          return_value=Detection(["us-east-1", "ap-northeast-2", "ap-northeast-1"])):
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
        with patch.object(lh, "detect_regions", return_value=Detection(["ap-northeast-2", "ap-northeast-1"])), \
             patch.object(lh, "send_error_alert") as alert:
            assert lh._notify_unregistered_regions("1", None, ["ap-northeast-2"]) == ["ap-northeast-1"]
        assert "ap-northeast-1" in str(alert.call_args.kwargs["error"])

    def test_nothing_missing_no_alert(self):
        from daily_monitor import lambda_handler as lh
        with patch.object(lh, "detect_regions", return_value=Detection(["ap-northeast-2", "us-east-1"])), \
             patch.object(lh, "send_error_alert") as alert:
            assert lh._notify_unregistered_regions("1", None, ["ap-northeast-2"]) == []
        alert.assert_not_called()


class TestDailyNoticeOnlyWhenTheListChanges:
    """2026-10-12~19: 중앙 계정이 같은 미등록 리전 5개(다른 프로젝트 리소스)를 매일 알렸다 — 이제 목록이 바뀔 때만."""

    ROW = {"customer_id": "c", "account_id": "949501913924"}
    FIVE = ["us-east-2", "us-west-2", "eu-west-1", "ap-northeast-2", "ap-southeast-1"]

    def _run(self, previous, detected):
        from daily_monitor import lambda_handler as lh
        row = {**self.ROW, "notified_unregistered_regions": previous} if previous is not None else dict(self.ROW)
        with patch.object(lh, "detect_regions", return_value=Detection(detected)), \
             patch.object(lh, "_account_rows", return_value=[row]), \
             patch.object(lh, "_save_region_detection") as save, \
             patch.object(lh, "send_error_alert") as alert:
            missing = lh._notify_unregistered_regions("949501913924", None, ["us-east-1"])
        return missing, alert, save

    def test_same_list_as_last_time_is_not_alerted_again(self):
        missing, alert, save = self._run(self.FIVE, ["us-east-1", *self.FIVE])
        assert missing == self.FIVE
        alert.assert_not_called()
        save.assert_called_once_with({**self.ROW, "notified_unregistered_regions": self.FIVE},
                                     ["us-east-1", *self.FIVE], self.FIVE)

    def test_first_time_alerts_and_remembers(self):
        _missing, alert, save = self._run(None, ["us-east-1", *self.FIVE])
        alert.assert_called_once()
        assert save.call_args.args[2] == self.FIVE

    def test_a_new_region_is_alerted_and_named(self):
        _missing, alert, _save = self._run(self.FIVE, ["us-east-1", *self.FIVE, "ap-northeast-1"])
        text = str(alert.call_args.kwargs["error"])
        assert "새로 생김: ap-northeast-1" in text

    def test_resolved_list_clears_without_alert_so_a_relapse_alerts(self):
        _missing, alert, save = self._run(self.FIVE, ["us-east-1"])
        alert.assert_not_called()
        assert save.call_args.args[2] == []
