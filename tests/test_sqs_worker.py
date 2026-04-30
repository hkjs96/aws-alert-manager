"""
sqs_worker lambda_handler 단위 테스트

DynamoDB 테이블은 moto mock_aws + patch를 조합하여 모킹하고,
alarm_manager 함수는 unittest.mock으로 대체한다.
"""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

import boto3
from moto import mock_aws

os.environ["JOB_STATUS_TABLE"] = "job-status-test"
os.environ["BULK_OPERATION_QUEUE_URL"] = "https://sqs.ap-northeast-2.amazonaws.com/123456789012/bulk.fifo"
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-northeast-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")

_REGION = "ap-northeast-2"


def _setup_ddb_table():
    """mock_aws 컨텍스트 내에서 DynamoDB 테이블을 생성하고 반환."""
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    ddb.create_table(
        TableName="job-status-test",
        KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb.Table("job-status-test")


def _put_job(table, job_id: str, total: int, completed: int = 0, failed: int = 0):
    status = "in_progress" if (completed + failed) > 0 else "pending"
    table.put_item(Item={
        "job_id": job_id, "status": status,
        "total_count": total, "completed_count": completed, "failed_count": failed,
    })


def _make_record(body: dict, message_id: str = "msg-001") -> dict:
    return {"messageId": message_id, "body": json.dumps(body)}


def _make_event(*records: dict) -> dict:
    return {"Records": list(records)}


# ──────────────────────────────────────────────────────────────
# _increment_job_counter / _finalize_job
# ──────────────────────────────────────────────────────────────

class TestJobStatusUpdate(unittest.TestCase):
    """DynamoDB 헬퍼 함수 단위 테스트."""

    def setUp(self):
        self.mock = mock_aws()
        self.mock.start()
        self.table = _setup_ddb_table()
        # 프로덕션 코드의 lru_cache를 초기화하고, table 함수를 패치
        from sqs_worker import lambda_handler as lh
        lh._get_ddb.cache_clear()
        # _job_status_table()이 테스트 테이블을 반환하도록 패치
        self.patcher = patch("sqs_worker.lambda_handler._job_status_table", return_value=self.table)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        from sqs_worker import lambda_handler as lh
        lh._get_ddb.cache_clear()
        self.mock.stop()

    def test_increment_success(self):
        from sqs_worker.lambda_handler import _increment_job_counter
        _put_job(self.table, "job-001", 3)
        _increment_job_counter("job-001", True)
        item = self.table.get_item(Key={"job_id": "job-001"})["Item"]
        assert int(item["completed_count"]) == 1
        assert int(item["failed_count"]) == 0

    def test_increment_failure(self):
        from sqs_worker.lambda_handler import _increment_job_counter
        _put_job(self.table, "job-002", 3)
        _increment_job_counter("job-002", False)
        item = self.table.get_item(Key={"job_id": "job-002"})["Item"]
        assert int(item["completed_count"]) == 0
        assert int(item["failed_count"]) == 1

    def test_finalize_completed(self):
        from sqs_worker.lambda_handler import _finalize_job
        _put_job(self.table, "job-003", 2, completed=2, failed=0)
        _finalize_job("job-003")
        item = self.table.get_item(Key={"job_id": "job-003"})["Item"]
        assert item["status"] == "completed"

    def test_finalize_partial_failure(self):
        from sqs_worker.lambda_handler import _finalize_job
        _put_job(self.table, "job-004", 3, completed=2, failed=1)
        _finalize_job("job-004")
        item = self.table.get_item(Key={"job_id": "job-004"})["Item"]
        assert item["status"] == "partial_failure"

    def test_finalize_all_failed(self):
        from sqs_worker.lambda_handler import _finalize_job
        _put_job(self.table, "job-005", 2, completed=0, failed=2)
        _finalize_job("job-005")
        item = self.table.get_item(Key={"job_id": "job-005"})["Item"]
        assert item["status"] == "failed"

    def test_finalize_not_yet_done(self):
        from sqs_worker.lambda_handler import _finalize_job
        _put_job(self.table, "job-006", 3, completed=1, failed=0)
        _finalize_job("job-006")
        item = self.table.get_item(Key={"job_id": "job-006"})["Item"]
        assert item["status"] == "in_progress"


# ──────────────────────────────────────────────────────────────
# lambda_handler 통합
# ──────────────────────────────────────────────────────────────

class TestLambdaHandler(unittest.TestCase):
    def setUp(self):
        self.mock = mock_aws()
        self.mock.start()
        self.table = _setup_ddb_table()
        from sqs_worker import lambda_handler as lh
        lh._get_ddb.cache_clear()
        lh._get_cw_for_role.cache_clear()
        self.patcher = patch("sqs_worker.lambda_handler._job_status_table", return_value=self.table)
        self.patcher.start()
        _put_job(self.table, "job-ok", 1)

    def tearDown(self):
        self.patcher.stop()
        from sqs_worker import lambda_handler as lh
        lh._get_ddb.cache_clear()
        lh._get_cw_for_role.cache_clear()
        self.mock.stop()

    @patch("sqs_worker.lambda_handler.alarm_manager.create_alarms_for_resource")
    def test_create_alarms_action(self, mock_create):
        mock_create.return_value = ["alarm-1"]
        from sqs_worker.lambda_handler import lambda_handler
        event = _make_event(_make_record({
            "job_id": "job-ok",
            "action": "create_alarms",
            "resource_id": "i-001",
            "resource_type": "EC2",
            "resource_tags": {"Monitoring": "on"},
        }))
        result = lambda_handler(event, None)
        assert result["batchItemFailures"] == []
        mock_create.assert_called_once()
        item = self.table.get_item(Key={"job_id": "job-ok"})["Item"]
        assert int(item["completed_count"]) == 1

    @patch("sqs_worker.lambda_handler.alarm_manager.delete_alarms_for_resource")
    def test_delete_alarms_action(self, mock_delete):
        mock_delete.return_value = []
        from sqs_worker.lambda_handler import lambda_handler
        event = _make_event(_make_record({
            "job_id": "job-ok",
            "action": "delete_alarms",
            "resource_id": "i-001",
            "resource_type": "EC2",
        }))
        result = lambda_handler(event, None)
        assert result["batchItemFailures"] == []
        mock_delete.assert_called_once_with("i-001", "EC2")

    @patch("sqs_worker.lambda_handler.alarm_manager.sync_alarms_for_resource")
    def test_sync_alarms_action(self, mock_sync):
        mock_sync.return_value = {"created": [], "updated": [], "ok": [], "deleted": []}
        from sqs_worker.lambda_handler import lambda_handler
        event = _make_event(_make_record({
            "job_id": "job-ok",
            "action": "sync_alarms",
            "resource_id": "i-001",
            "resource_type": "EC2",
            "resource_tags": {},
        }))
        result = lambda_handler(event, None)
        assert result["batchItemFailures"] == []
        mock_sync.assert_called_once()

    @patch("sqs_worker.lambda_handler.alarm_manager.create_alarms_for_resource")
    def test_toggle_monitoring_on(self, mock_create):
        mock_create.return_value = []
        from sqs_worker.lambda_handler import lambda_handler
        event = _make_event(_make_record({
            "job_id": "job-ok",
            "action": "toggle_monitoring",
            "resource_id": "i-001",
            "resource_type": "EC2",
            "resource_tags": {},
            "monitoring": True,
        }))
        result = lambda_handler(event, None)
        assert result["batchItemFailures"] == []
        mock_create.assert_called_once()

    @patch("sqs_worker.lambda_handler.alarm_manager.delete_alarms_for_resource")
    def test_toggle_monitoring_off(self, mock_delete):
        mock_delete.return_value = []
        from sqs_worker.lambda_handler import lambda_handler
        event = _make_event(_make_record({
            "job_id": "job-ok",
            "action": "toggle_monitoring",
            "resource_id": "i-001",
            "resource_type": "EC2",
            "monitoring": False,
        }))
        result = lambda_handler(event, None)
        assert result["batchItemFailures"] == []
        mock_delete.assert_called_once()

    def test_invalid_json_body(self):
        from sqs_worker.lambda_handler import lambda_handler
        result = lambda_handler(
            {"Records": [{"messageId": "bad-msg", "body": "not-json"}]}, None
        )
        assert result["batchItemFailures"] == [{"itemIdentifier": "bad-msg"}]

    def test_unknown_action(self):
        _put_job(self.table, "job-bad", 1)
        from sqs_worker.lambda_handler import lambda_handler
        event = _make_event(_make_record({
            "job_id": "job-bad",
            "action": "fly_to_moon",
            "resource_id": "i-001",
            "resource_type": "EC2",
        }, "bad-action-msg"))
        result = lambda_handler(event, None)
        assert result["batchItemFailures"] == [{"itemIdentifier": "bad-action-msg"}]
        item = self.table.get_item(Key={"job_id": "job-bad"})["Item"]
        assert int(item["failed_count"]) == 1

    @patch("sqs_worker.lambda_handler.alarm_manager.create_alarms_for_resource")
    @patch("sqs_worker.lambda_handler.alarm_manager.delete_alarms_for_resource")
    def test_multiple_records_all_complete(self, mock_delete, mock_create):
        mock_create.return_value = []
        mock_delete.return_value = []
        _put_job(self.table, "job-multi", 2)
        event = _make_event(
            _make_record({"job_id": "job-multi", "action": "create_alarms", "resource_id": "i-001", "resource_type": "EC2", "resource_tags": {}}, "msg-1"),
            _make_record({"job_id": "job-multi", "action": "delete_alarms", "resource_id": "i-002", "resource_type": "EC2"}, "msg-2"),
        )
        from sqs_worker.lambda_handler import lambda_handler
        result = lambda_handler(event, None)
        assert result["batchItemFailures"] == []
        item = self.table.get_item(Key={"job_id": "job-multi"})["Item"]
        assert int(item["completed_count"]) == 2
        assert item["status"] == "completed"
