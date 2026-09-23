import json
import os
from unittest.mock import MagicMock, patch
import pytest

def _event(method: str, path: str, body=None, qs=None, path_params=None) -> dict:
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "rawPath": path,
        "queryStringParameters": qs or {},
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body else None,
    }

@pytest.fixture
def mock_db_env(monkeypatch):
    monkeypatch.setenv("RESOURCE_INVENTORY_TABLE", "test-inventory")
    monkeypatch.setenv("ACCOUNTS_TABLE", "test-accounts")
    monkeypatch.setenv("CUSTOMERS_TABLE", "test-customers")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setattr("api_handler.routes.resources.resource_inventory_table", lambda: MagicMock())

class TestResourceInventoryLogic:

    @patch("api_handler.routes.resources.scan_all")
    def test_list_resources_merges_aws_and_db(self, mock_scan, mock_db_env):
        # DB scan returns both resources and alarm items
        mock_scan.return_value = [{ # inventory
            "resource_id": "i-aws-01",
            "account_id": "123456789012",
            "name": "aws-instance",
            "type": "EC2",
            "customer_id": "cust-01",
            "region": "ap-northeast-2",
            "monitoring": True,
            "status": "active",
            "inventory_source": "aws",
            "entity_type": "resource",
            "alarm_count": 1,
            "critical_count": 1,
            "warning_count": 0,
        }, {
            "resource_id": "i-db-01",
            "account_id": "123456789012",
            "name": "stale-instance",
            "type": "EC2",
            "status": "missing",
            "inventory_source": "db",
            "entity_type": "resource",
            "alarm_count": 2,
            "critical_count": 0,
            "warning_count": 2,
        }, {
            "resource_id": "alarm#arn:aws:cloudwatch:ap-northeast-2:123456789012:alarm:aws-cpu",
            "alarm_name": "aws-cpu",
            "resource": "i-aws-01",
            "entity_type": "alarm",
            "state": "ALARM",
            "severity": "SEV-1"
        }, {
            "resource_id": "alarm#arn:aws:cloudwatch:ap-northeast-2:123456789012:alarm:db-mem1",
            "alarm_name": "db-mem1",
            "resource": "i-db-01",
            "entity_type": "alarm",
            "state": "ALARM",
            "severity": "SEV-3"
        }, {
            "resource_id": "alarm#arn:aws:cloudwatch:ap-northeast-2:123456789012:alarm:db-mem2",
            "alarm_name": "db-mem2",
            "resource": "i-db-01",
            "entity_type": "alarm",
            "state": "ALARM",
            "severity": "SEV-3"
        }]
        
        from api_handler.routes.resources import list_resources
        resp = list_resources(_event("GET", "/resources"))
        
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        items = body["items"]
        
        assert len(items) == 2
        
        # Check AWS discovered item
        aws_item = next(i for i in items if i["id"] == "i-aws-01")
        assert aws_item["inventory_source"] == "aws"
        assert aws_item["account"] == "123456789012"
        assert aws_item["account_id"] == "123456789012"
        assert aws_item["status"] == "active"
        assert aws_item["alarm_count"] == 1
        assert aws_item["alarms"]["critical"] == 1
        assert aws_item["persisted"] == True
        
        # Check DB stale item
        db_item = next(i for i in items if i["id"] == "i-db-01")
        assert db_item["inventory_source"] == "db"
        assert db_item["status"] == "missing"
        assert db_item["alarm_count"] == 2
        assert db_item["alarms"]["warning"] == 2
        assert db_item["persisted"] == True

    @patch("api_handler.routes.resources.scan_all")
    def test_list_resources_filters_correctly(self, mock_scan, mock_db_env):
        """resource_type 필터링이 정확히 동작해야 한다."""
        mock_scan.return_value = [ # inventory
            {"resource_id": "i-01", "name": "e1", "type": "EC2", "account_id": "1", "region": "r1", "monitoring": True, "status": "active", "entity_type": "resource"},
            {"resource_id": "db-01", "name": "r1", "type": "RDS", "account_id": "1", "region": "r1", "monitoring": True, "status": "active", "entity_type": "resource"}
        ]
        
        from api_handler.routes.resources import list_resources
        # EC2만 필터링
        resp = list_resources(_event("GET", "/resources", qs={"resource_type": "EC2"}))
        body = json.loads(resp["body"])
        assert body["total"] == 1
        assert body["items"][0]["type"] == "EC2"

    @patch("api_handler.routes.resources.scan_all")
    def test_list_resources_ignores_orphan_alarm_snapshots(self, mock_scan, mock_db_env):
        """리소스 snapshot 없는 alarm snapshot은 리소스 목록에 섞이면 안 된다."""
        mock_scan.return_value = [{
            "resource_id": "alarm#arn:aws:cloudwatch:us-east-1:123456789012:alarm:orphan-01",
            "alarm_name": "orphan-01",
            "resource": "i-orphan-01",
            "entity_type": "alarm",
            "state": "ALARM",
            "severity": "SEV-3",
        }]
        
        from api_handler.routes.resources import list_resources
        resp = list_resources(_event("GET", "/resources"))
        
        body = json.loads(resp["body"])
        items = body["items"]
        
        assert len(items) == 0

    @patch("api_handler.routes.resources.scan_all")
    def test_list_resources_keeps_legacy_resource_snapshots(self, mock_scan, mock_db_env):
        mock_scan.return_value = [{
            "resource_id": "i-legacy",
            "name": "legacy-instance",
            "type": "EC2",
            "account_id": "1",
            "region": "us-east-1",
            "monitoring": True,
            "status": "active",
        }]

        from api_handler.routes.resources import list_resources
        resp = list_resources(_event("GET", "/resources"))

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["total"] == 1
        assert body["items"][0]["id"] == "i-legacy"

    @patch("api_handler.routes.resources.scan_all")
    def test_list_resources_keeps_unmonitored_discovered_resources(self, mock_scan, mock_db_env):
        """Monitoring 태그 값이 비어도 실제 존재하는 리소스는 목록에 표시한다."""
        mock_scan.return_value = [{ # inventory
            "resource_id": "i-unmonitored",
            "name": "unmonitored",
            "type": "EC2",
            "account_id": "1",
            "region": "us-east-1",
            "customer_id": "cust-01",
            "monitoring": False,
            "status": "active",
            "entity_type": "resource",
        }]

        from api_handler.routes.resources import list_resources
        resp = list_resources(_event("GET", "/resources"))

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["total"] == 1
        assert body["items"][0]["id"] == "i-unmonitored"
        assert body["items"][0]["monitoring"] is False

    @patch("api_handler.routes.resources.scan_all")
    def test_get_resource_resolves_discovered_resource_by_name_without_alarms(self, mock_scan, mock_db_env):
        mock_scan.return_value = [{ # inventory
            "resource_id": "i-01",
            "name": "web-01",
            "type": "EC2",
            "account_id": "123",
            "customer_id": "cust-01",
            "region": "us-east-1",
            "monitoring": False,
            "status": "active",
            "entity_type": "resource",
        }]

        from api_handler.routes.resources import get_resource
        resp = get_resource(_event("GET", "/resources/web-01", path_params={"id": "web-01"}))

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["id"] == "i-01"
        assert body["name"] == "web-01"
        assert body["monitoring"] is False
        assert body["alarm_count"] == 0

    @patch("api_handler.routes.resources.scan_all")
    def test_get_resource_resolves_persisted_resource_by_id_without_alarms(self, mock_scan, mock_db_env):
        mock_scan.return_value = [{ # inventory
            "resource_id": "i-02",
            "name": "db-only",
            "type": "EC2",
            "account_id": "123",
            "customer_id": "cust-01",
            "region": "us-east-1",
            "monitoring": False,
            "status": "active",
            "inventory_source": "db",
            "entity_type": "resource",
        }]

        from api_handler.routes.resources import get_resource
        resp = get_resource(_event("GET", "/resources/i-02", path_params={"id": "i-02"}))

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["id"] == "i-02"
        assert body["name"] == "db-only"
        assert body["inventory_source"] == "db"
        assert body["monitoring"] is False

    # NOTE: 동기 sync_resources 테스트는 제거됨 — 비동기 잡 흐름은
    # test_api_routes.test_sync_resources_starts_async_job(202+job)와
    # test_daily_monitor_inventory.TestResourcesSyncJob이 커버한다.

    @patch("api_handler.routes.resources._apply_alarms_for_toggle")
    @patch("api_handler.routes.resources._get_tagging_client_for_region")
    @patch("api_handler.routes.resources.resource_inventory_table")
    @patch("api_handler.routes.resources.scan_all")
    def test_update_resource_monitoring_tags_via_rgt_and_updates_inventory(self, mock_scan, mock_table_func, mock_tagging_func, mock_apply, mock_db_env):
        mock_scan.return_value = [{
            "resource_id": "i-01",
            "account_id": "123",
            "type": "EC2",
            "region": "us-east-1",
            "monitoring": False,
            "entity_type": "resource",
        }]
        mock_table = MagicMock()
        mock_table_func.return_value = mock_table
        mock_tagging = MagicMock()
        mock_tagging.tag_resources.return_value = {"FailedResourcesMap": {}}
        mock_tagging_func.return_value = mock_tagging

        from api_handler.routes.resources import update_resource_monitoring
        resp = update_resource_monitoring(
            _event("PUT", "/resources/i-01/monitoring", body={"monitoring": True}, path_params={"id": "i-01"})
        )

        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["monitoring"] is True
        # 인벤토리 항목에 arn이 없으므로 타입별 템플릿으로 ARN을 구성해 RGT로 태깅한다.
        mock_tagging.tag_resources.assert_called_once_with(
            ResourceARNList=["arn:aws:ec2:us-east-1:123:instance/i-01"],
            Tags={"Monitoring": "on"},
        )
        mock_table.update_item.assert_called_once_with(
            Key={"resource_id": "i-01", "account_id": "123"},
            UpdateExpression="SET monitoring = :monitoring",
            ExpressionAttributeValues={":monitoring": True},
        )

    @patch("api_handler.routes.resources._apply_alarms_for_toggle")
    @patch("api_handler.routes.resources._get_tagging_client_for_region")
    @patch("api_handler.routes.resources.resource_inventory_table")
    @patch("api_handler.routes.resources.scan_all")
    def test_update_resource_monitoring_uses_stored_arn(self, mock_scan, mock_table_func, mock_tagging_func, mock_apply, mock_db_env):
        # 인벤토리에 arn이 저장된 경우(NLB/TG/신규 7종) 저장값을 그대로 사용한다.
        nlb_arn = "arn:aws:elasticloadbalancing:us-east-1:123:loadbalancer/net/nlb/abc"
        mock_scan.return_value = [{
            "resource_id": nlb_arn,
            "account_id": "123",
            "type": "NLB",
            "region": "us-east-1",
            "arn": nlb_arn,
            "entity_type": "resource",
        }]
        mock_table_func.return_value = MagicMock()
        mock_tagging = MagicMock()
        mock_tagging.tag_resources.return_value = {"FailedResourcesMap": {}}
        mock_tagging_func.return_value = mock_tagging

        from api_handler.routes.resources import update_resource_monitoring
        resp = update_resource_monitoring(
            _event("PUT", "/resources/x/monitoring", body={"monitoring": False}, path_params={"id": nlb_arn})
        )

        assert resp["statusCode"] == 200
        mock_tagging.tag_resources.assert_called_once_with(
            ResourceARNList=[nlb_arn],
            Tags={"Monitoring": "off"},
        )

    @patch("api_handler.routes.resources.scan_all")
    def test_update_resource_monitoring_rejects_unsupported_type(self, mock_scan, mock_db_env):
        mock_scan.return_value = [{"resource_id": "x-01", "type": "NotARealType", "entity_type": "resource"}]

        from api_handler.routes.resources import update_resource_monitoring
        resp = update_resource_monitoring(
            _event("PUT", "/resources/x-01/monitoring", body={"monitoring": True}, path_params={"id": "x-01"})
        )

        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["code"] == "UNSUPPORTED_RESOURCE_TYPE"

    @patch("api_handler.routes.resources._refresh_alarm_rows")
    @patch("api_handler.routes.resources._live_resource_tags", return_value={})
    @patch("api_handler.routes.resources.delete_alarms_for_resource")
    @patch("api_handler.routes.resources.sync_alarms_for_resource")
    @patch("api_handler.routes.resources._get_cw_client_for_region")
    @patch("api_handler.routes.resources._find_account", return_value=None)
    def test_apply_alarms_for_toggle_creates_on_deletes_off(self, mock_find, mock_cw, mock_sync, mock_delete,
                                                             mock_live, mock_rows, mock_db_env):
        # 갭 축소: 토글 ON은 알람 즉시 생성, OFF는 즉시 삭제 (다음 daily run을 안 기다림).
        from api_handler.routes.resources import _apply_alarms_for_toggle
        res = {"resource_id": "i-9", "type": "EC2", "region": "us-east-1", "account_id": "123"}

        _apply_alarms_for_toggle(res, True)
        mock_sync.assert_called_once()
        assert mock_sync.call_args.args[0] == "i-9"
        assert mock_sync.call_args.args[2] == {"Monitoring": "on"}
        mock_delete.assert_not_called()

        # 인벤토리 dim_hints가 있으면 알람 생성 태그에 병합된다
        # (APIGW v2 ApiId, TG _lb_arn 복합 디멘션 등 즉시 생성 정확도 확보).
        mock_sync.reset_mock()
        res_hints = {"resource_id": "30atme9kk0", "type": "APIGW", "region": "us-east-1",
                     "account_id": "123", "dim_hints": {"_api_type": "HTTP"}}
        _apply_alarms_for_toggle(res_hints, True)
        assert mock_sync.call_args.args[2] == {"Monitoring": "on", "_api_type": "HTTP"}

        mock_delete.return_value = ["[EC2] web CPUUtilization > 80% (TagName: i-9)"]
        _apply_alarms_for_toggle(res, False)
        mock_delete.assert_called_once()
        assert mock_delete.call_args.args[0] == "i-9"
        assert mock_rows.call_args.kwargs["deleted"] == ["[EC2] web CPUUtilization > 80% (TagName: i-9)"]


class TestToggleUsesTheResourcesRealTags:
    """2026-09-23 첫 실고객 토글: 알람 이름이 `[EC2] i-08e54786d6a2dae9d CPUUtilization …`로 만들어졌다. 고객 알람은
    `[EC2]EC2-AN2-HOME-PRD-BASTION-01A …` — 라벨이 Name 태그가 아니라 인스턴스 ID로 떨어진 것. 동기화는 기존 알람을 메트릭으로
    대조하므로 데일리 런이 이름을 고치지 않는다 — 토글이 처음부터 데일리 런과 같은 태그로 만들어야 한다."""

    def test_live_tags_give_the_alarm_its_name_and_thresholds(self):
        from api_handler.routes import resources as r
        res = {"resource_id": "i-08e5", "type": "EC2", "region": "ap-northeast-2", "account_id": "771283576189"}
        live = {"Name": "EC2-AN2-HOME-PRD-BASTION-01A", "Threshold_CPUUtilization": "90", "Monitoring": "off"}
        with patch.object(r, "_live_resource_tags", return_value=live):
            tags = r._toggle_alarm_tags(res)
        assert tags["Name"] == "EC2-AN2-HOME-PRD-BASTION-01A"
        assert tags["Threshold_CPUUtilization"] == "90"
        assert tags["Monitoring"] == "on"          # 방금 쓴 태그는 RGT 최종 일관성 때문에 아직 off로 보일 수 있다

    def test_dimension_hints_win_over_live_tags(self):
        from api_handler.routes import resources as r
        res = {"resource_id": "tg", "type": "TG", "region": "us-east-1", "account_id": "1",
               "dim_hints": {"_lb_arn": "arn:lb"}}
        with patch.object(r, "_live_resource_tags", return_value={"_lb_arn": "stale", "Name": "tg-a"}):
            assert r._toggle_alarm_tags(res) == {"_lb_arn": "arn:lb", "Name": "tg-a", "Monitoring": "on"}

    def test_name_label_reaches_the_alarm_name(self):
        """실제 알람 이름 빌더까지 — 라벨이 ID가 아니라 Name이어야 한다."""
        from common.alarm_naming import _pretty_alarm_name
        name = _pretty_alarm_name("EC2", "i-08e5", "EC2-AN2-HOME-PRD-BASTION-01A", "CPUUtilization", 80.0)
        assert name.startswith("[EC2] EC2-AN2-HOME-PRD-BASTION-01A CPUUtilization")
        assert name.endswith("(TagName: i-08e5)")

    def test_live_tags_are_read_through_the_account_session(self):
        from api_handler.routes import resources as r
        client = MagicMock()
        client.get_resources.return_value = {"ResourceTagMappingList": [
            {"ResourceARN": "arn:x", "Tags": [{"Key": "Name", "Value": "bastion"}]}]}
        session = MagicMock()
        session.client.return_value = client
        res = {"resource_id": "i-1", "type": "EC2", "account_id": "771283576189", "region": "ap-northeast-2"}
        with patch.object(r, "_resource_arn_for_tagging", return_value="arn:x"), \
             patch.object(r, "_resource_aws_session", return_value=(session, "ap-northeast-2", "771283576189")):
            assert r._live_resource_tags(res) == {"Name": "bastion"}
        session.client.assert_called_once_with("resourcegroupstaggingapi", region_name="ap-northeast-2")
        client.get_resources.assert_called_once_with(ResourceARNList=["arn:x"])

    def test_unreadable_tags_fall_back_to_the_old_behaviour(self):
        from botocore.exceptions import ClientError
        from api_handler.routes import resources as r
        client = MagicMock()
        client.get_resources.side_effect = ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, "GetResources")
        with patch.object(r, "_resource_arn_for_tagging", return_value="arn:x"), \
             patch.object(r, "_resource_aws_session", return_value=(None, "us-east-1", "1")), \
             patch.object(r, "_get_tagging_client_for_region", return_value=client):
            assert r._live_resource_tags({"resource_id": "i-1", "type": "EC2"}) == {}


class TestToggleRefreshesTheAlarmRows:
    """리소스 상세 화면의 알람 표는 인벤토리 알람 행을 읽는다. 예전에는 데일리 런·정합 런만 그 행을 써서, 켜도 끄도 화면이
    최대 한 시간 그대로였다(2026-09-23 첫 실고객 토글: 알람 3개가 생겼는데 표는 비어 있었다)."""

    ALARM = {
        "AlarmName": "[EC2] bastion CPUUtilization > 80% (TagName: i-08e5)",
        "AlarmArn": "arn:aws:cloudwatch:ap-northeast-2:771283576189:alarm:[EC2] bastion CPUUtilization > 80% (TagName: i-08e5)",
        "AlarmDescription": 'Auto-created | {"metric_key":"CPUUtilization","resource_id":"i-08e5","resource_type":"EC2"}',
        "StateValue": "OK", "MetricName": "CPUUtilization", "Namespace": "AWS/EC2", "Threshold": 80.0,
        "ComparisonOperator": "GreaterThanThreshold",
    }
    CUSTOMERS_OWN = {  # 고객이 만든 비슷한 이름 — 관리 포맷이 아니라 행이 되면 안 된다
        "AlarmName": "[EC2]EC2-AN2-HOME-PRD-BASTION-01A STATUS_CHECK_FAILED (TagName:EC2-AN2-HOME-PRD-BASTION-01A)",
        "AlarmArn": "arn:aws:cloudwatch:ap-northeast-2:771283576189:alarm:custom", "StateValue": "OK",
    }

    def _run(self, *, deleted=None, alarms=()):
        from api_handler.routes import resources as r
        cw = MagicMock()
        cw.meta.region_name = "ap-northeast-2"
        cw.describe_alarms.return_value = {"MetricAlarms": list(alarms)}
        table = MagicMock()
        batch = table.batch_writer.return_value.__enter__.return_value
        res = {"resource_id": "i-08e5", "type": "EC2", "account_id": "771283576189"}
        with patch.dict("os.environ", {"RESOURCE_INVENTORY_TABLE": "inv"}), \
             patch.object(r, "resource_inventory_table", return_value=table), \
             patch.object(r, "_find_alarms_for_resource", return_value=[a["AlarmName"] for a in alarms]):
            r._refresh_alarm_rows(res, cw, deleted=deleted)
        return batch, cw

    def test_on_writes_a_row_per_managed_alarm(self):
        batch, cw = self._run(alarms=[self.ALARM, self.CUSTOMERS_OWN])
        rows = [c.kwargs["Item"] for c in batch.put_item.call_args_list]
        assert len(rows) == 1
        row = rows[0]
        assert row["resource_id"] == f"alarm#{self.ALARM['AlarmArn']}"
        assert row["account_id"] == "771283576189"
        assert row["resource"] == "i-08e5" and row["entity_type"] == "alarm" and row["state"] == "OK"
        batch.delete_item.assert_not_called()

    def test_off_removes_the_rows_of_the_deleted_alarms(self):
        name = "[EC2] bastion CPUUtilization > 80% (TagName: i-08e5)"
        batch, cw = self._run(deleted=[name])
        batch.delete_item.assert_called_once_with(Key={
            "resource_id": f"alarm#arn:aws:cloudwatch:ap-northeast-2:771283576189:alarm:{name}",
            "account_id": "771283576189"})
        batch.put_item.assert_not_called()
        cw.describe_alarms.assert_not_called()

    def test_rows_use_the_same_builder_as_the_daily_run(self):
        """두 경로의 행이 어긋나면 화면이 토글 직후와 정합 런 뒤에 다르게 보인다."""
        from common.alarm_inventory import alarm_snapshot_items
        from daily_monitor.lambda_handler import _write_alarm_snapshots
        table = MagicMock()
        batch = table.batch_writer.return_value.__enter__.return_value
        _, fresh = _write_alarm_snapshots(table, [self.ALARM])
        daily_row = batch.put_item.call_args.kwargs["Item"]
        assert daily_row == alarm_snapshot_items([self.ALARM])[0]
        assert fresh == {(daily_row["resource_id"], "771283576189")}

    def test_a_failed_refresh_does_not_fail_the_toggle(self):
        from botocore.exceptions import ClientError
        from api_handler.routes import resources as r
        cw = MagicMock()
        cw.meta.region_name = "ap-northeast-2"
        table = MagicMock()
        table.batch_writer.side_effect = ClientError({"Error": {"Code": "Throttling", "Message": "x"}}, "BatchWriteItem")
        with patch.dict("os.environ", {"RESOURCE_INVENTORY_TABLE": "inv"}), \
             patch.object(r, "resource_inventory_table", return_value=table):
            r._refresh_alarm_rows({"resource_id": "i-1", "type": "EC2", "account_id": "1"}, cw, deleted=[])

    @patch("api_handler.routes.resources._apply_alarms_for_toggle",
           side_effect=KeyError("_lb_arn"))
    @patch("api_handler.routes.resources._get_tagging_client_for_region")
    @patch("api_handler.routes.resources.resource_inventory_table")
    @patch("api_handler.routes.resources.scan_all")
    def test_toggle_succeeds_when_immediate_alarms_need_collector_hints(self, mock_scan, mock_table_func, mock_tagging_func, mock_apply, mock_db_env):
        # TG처럼 collector 내부 태그(_lb_arn) 없이는 즉시 알람 디멘션을 못 만드는
        # 타입은 KeyError가 난다 — 토글은 성공(200)하고 daily가 self-heal 해야 한다.
        tg_arn = "arn:aws:elasticloadbalancing:us-east-1:123:targetgroup/tg/abc"
        mock_scan.return_value = [{
            "resource_id": tg_arn, "account_id": "123", "type": "TG",
            "region": "us-east-1", "arn": tg_arn, "entity_type": "resource",
        }]
        mock_table_func.return_value = MagicMock()
        mock_tagging = MagicMock()
        mock_tagging.tag_resources.return_value = {"FailedResourcesMap": {}}
        mock_tagging_func.return_value = mock_tagging

        from api_handler.routes.resources import update_resource_monitoring
        resp = update_resource_monitoring(
            _event("PUT", "/resources/x/monitoring", body={"monitoring": True}, path_params={"id": tg_arn})
        )

        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["monitoring"] is True

    @patch("api_handler.routes.resources._get_cw_client_for_region")
    @patch("api_handler.routes.resources.scan_all")
    def test_apigw_v2_metrics_use_apiid_dimension(self, mock_scan, mock_cw_func, mock_db_env):
        # APIGW v2(HTTP/WS)는 메트릭을 ApiId 디멘션으로 발행 — dim_hints._api_type으로
        # 정적 맵(ApiName) 대신 ApiId 키를 써야 한다 (compound-dim 보정).
        mock_scan.return_value = [{
            "resource_id": "30atme9kk0", "account_id": "123", "type": "APIGW",
            "region": "us-east-1", "entity_type": "resource",
            "dim_hints": {"_api_type": "HTTP"},
        }]
        cw = MagicMock()
        cw.list_metrics.return_value = {"Metrics": [
            {"MetricName": "Count", "Namespace": "AWS/ApiGateway"},
        ]}
        mock_cw_func.return_value = cw

        from api_handler.routes.resources import get_resource_metrics
        resp = get_resource_metrics(
            _event("GET", "/resources/x/metrics", path_params={"id": "30atme9kk0"})
        )

        assert resp["statusCode"] == 200
        dims = cw.list_metrics.call_args.kwargs["Dimensions"]
        assert dims == [{"Name": "ApiId", "Value": "30atme9kk0"}]
        assert json.loads(resp["body"])[0]["metric_name"] == "Count"

    @patch("api_handler.routes.resources._find_account", return_value=None)
    def test_resource_aws_session_forces_us_east_1_for_global_services(self, mock_find, mock_db_env):
        # CloudFront/Route53은 RGT 태깅·CW 알람 모두 us-east-1 전용 — 인벤토리
        # region 값이 무엇이든 us-east-1로 강제해야 한다 (리뷰 지적 사항).
        from api_handler.routes.resources import _resource_aws_session

        for rtype in ("CloudFront", "Route53"):
            _, region, _ = _resource_aws_session(
                {"resource_id": "x", "type": rtype, "region": "ap-northeast-2", "account_id": "123"})
            assert region == "us-east-1", rtype

        # 일반 리전 서비스는 인벤토리 region 그대로.
        _, region, _ = _resource_aws_session(
            {"resource_id": "x", "type": "EC2", "region": "ap-northeast-2", "account_id": "123"})
        assert region == "ap-northeast-2"
