"""켜기 전 중복 점검 (2026-10) — 바스티온: 고객 STATUS_CHECK_FAILED와 우리 StatusCheckFailed가 같은 지표를 봤다."""

import json
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from common.alarm_overlap import find_overlaps

IID = "i-08e54786d6a2dae9d"


def _cw(alarms):
    cw = MagicMock()
    cw.get_paginator.return_value.paginate.return_value = [{"MetricAlarms": alarms}]
    return cw


def _alarm(name, metric, dims, namespace="AWS/EC2", description=""):
    return {"AlarmName": name, "Namespace": namespace, "MetricName": metric, "Dimensions": dims,
            "Threshold": 0.0, "ComparisonOperator": "GreaterThanThreshold", "StateValue": "OK",
            "AlarmDescription": description}


CUSTOMER_STATUS = _alarm("[EC2]EC2-AN2-HOME-PRD-BASTION-01A STATUS_CHECK_FAILED", "StatusCheckFailed",
                         [{"Name": "InstanceId", "Value": IID}])
OURS_STATUS = _alarm(f"[EC2] EC2-AN2-HOME-PRD-BASTION-01A StatusCheckFailed > 0 (TagName: {IID})", "StatusCheckFailed",
                     [{"Name": "InstanceId", "Value": IID}])


class TestFindOverlaps:
    def test_customer_alarm_on_the_same_metric_and_instance_is_reported(self):
        got = find_overlaps(IID, "EC2", {"Monitoring": "on"}, _cw([CUSTOMER_STATUS, OURS_STATUS]))
        assert [o["metric"] for o in got] == ["StatusCheckFailed"]
        assert got[0]["customer_alarms"][0]["name"] == "[EC2]EC2-AN2-HOME-PRD-BASTION-01A STATUS_CHECK_FAILED"

    def test_our_own_alarms_are_not_overlaps(self):
        assert find_overlaps(IID, "EC2", {"Monitoring": "on"}, _cw([OURS_STATUS])) == []

    def test_other_instance_or_extra_dimension_is_not_an_overlap(self):
        other = _alarm("cpu other", "CPUUtilization", [{"Name": "InstanceId", "Value": "i-other"}])
        extra = _alarm("cpu by type", "CPUUtilization",
                       [{"Name": "InstanceId", "Value": IID}, {"Name": "InstanceType", "Value": "t3.micro"}])
        assert find_overlaps(IID, "EC2", {"Monitoring": "on"}, _cw([other, extra])) == []

    def test_dimension_order_does_not_matter(self):
        tg_arn = "arn:aws:elasticloadbalancing:ap-northeast-2:1:targetgroup/tg-a/abc"
        lb_arn = "arn:aws:elasticloadbalancing:ap-northeast-2:1:loadbalancer/app/lb-a/def"
        theirs = _alarm("tg unhealthy", "UnHealthyHostCount",
                        [{"Name": "LoadBalancer", "Value": "app/lb-a/def"}, {"Name": "TargetGroup", "Value": "targetgroup/tg-a/abc"}],
                        namespace="AWS/ApplicationELB")
        got = find_overlaps(tg_arn, "TG", {"Monitoring": "on", "_lb_arn": lb_arn}, _cw([theirs]))
        assert "UnHealthyHostCount" in [o["metric_name"] for o in got]

    def test_disk_alarms_are_skipped(self):
        disk = _alarm("disk", "disk_used_percent", [{"Name": "InstanceId", "Value": IID}], namespace="CWAgent")
        assert all(o["metric"] != "disk_used_percent" for o in find_overlaps(IID, "EC2", {}, _cw([disk])))


class TestOverlapRoute:
    def _call(self, items, cw):
        from api_handler.routes import resources as r
        with patch.object(r, "query_by_pk", return_value=items), \
             patch.object(r, "resource_inventory_table"), \
             patch.object(r, "_resource_aws_session", return_value=(None, "ap-northeast-2", "771283576189")), \
             patch.object(r, "_get_cw_client_for_region", return_value=cw), \
             patch.object(r, "_live_resource_tags", return_value={"Name": "EC2-AN2-HOME-PRD-BASTION-01A"}):
            return r.get_alarm_overlaps({"pathParameters": {"id": IID}})

    def test_returns_overlaps_for_an_inventory_resource(self):
        item = {"resource_id": IID, "account_id": "771283576189", "type": "EC2", "region": "ap-northeast-2"}
        with patch("api_handler.routes.resources._is_resource_snapshot", return_value=True):
            resp = self._call([item], _cw([CUSTOMER_STATUS]))
        body = json.loads(resp["body"])
        assert resp["statusCode"] == 200 and body["overlaps"][0]["metric"] == "StatusCheckFailed"

    def test_unknown_resource_is_404(self):
        assert self._call([], _cw([]))["statusCode"] == 404

    def test_alarm_read_failure_is_502(self):
        cw = MagicMock()
        cw.get_paginator.return_value.paginate.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "x"}}, "DescribeAlarms")
        item = {"resource_id": IID, "account_id": "1", "type": "EC2", "region": "ap-northeast-2"}
        with patch("api_handler.routes.resources._is_resource_snapshot", return_value=True):
            assert self._call([item], cw)["statusCode"] == 502

    def test_route_is_registered(self):
        from api_handler import lambda_handler as lh
        src = open(lh.__file__, encoding="utf-8").read()
        assert "alarm-overlaps$" in src and "resources.get_alarm_overlaps" in src


class TestDiskPathsUseTheResourcesAccount:
    """GET /resources/{id}/disk-paths는 리전만 맞추고 중앙 계정 CW를 봐서 고객 EC2는 늘 빈 목록이었다(2026-10-19 발견)."""

    def test_customer_ec2_disk_paths_come_from_the_customer_session(self):
        from api_handler.routes import resources as r
        item = {"resource_id": IID, "account_id": "771283576189", "type": "EC2", "region": "ap-northeast-2"}
        session, cw = MagicMock(), MagicMock()
        session.client.return_value = cw
        cw.list_metrics.return_value = {"Metrics": [
            {"Dimensions": [{"Name": "InstanceId", "Value": IID}, {"Name": "path", "Value": "/"}]}]}
        with patch.dict("os.environ", {"RESOURCE_INVENTORY_TABLE": "t"}), \
             patch.object(r, "query_by_pk", return_value=[item]), patch.object(r, "resource_inventory_table"), \
             patch.object(r, "_is_resource_snapshot", return_value=True), \
             patch.object(r, "_resource_aws_session", return_value=(session, "ap-northeast-2", "771283576189")), \
             patch.object(r, "_get_cw_client") as central:
            resp = r.get_disk_paths({"pathParameters": {"id": IID}})
        assert json.loads(resp["body"]) == ["/"]
        session.client.assert_called_once_with("cloudwatch", region_name="ap-northeast-2")
        central.assert_not_called()
