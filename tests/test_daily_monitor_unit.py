"""
daily_monitor.lambda_handler 단위 테스트

moto + unittest.mock 기반으로 orchestration 로직을 검증한다.
AWS API 호출은 moto로, collector/alarm_manager는 mock으로 격리한다.

커버 케이스:
- 리소스 0개: 처리 없이 ok 반환
- 리소스 1개: 알람 동기화 + 메트릭 조회 + 결과 반환
- collector 에러: 해당 collector 건너뛰고 나머지 처리
- role_arn 세션 전환: STS AssumeRole 호출 확인
- AssumeRole 실패: assume_role_failed 반환
- 고아 알람 정리: terminated 인스턴스 알람 삭제
"""

import os
from unittest.mock import MagicMock, patch, call

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws


# ──────────────────────────────────────────────
# 공통 환경 변수 / 픽스처
# ──────────────────────────────────────────────

_ENV = {
    "ENVIRONMENT": "test",
    "SNS_TOPIC_ARN_ALERT": "arn:aws:sns:us-east-1:123456789012:test-alerts",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_SESSION_TOKEN": "testing",
}


def _make_resource(resource_id="i-0abc1234", resource_type="EC2", tags=None):
    return {
        "id": resource_id,
        "type": resource_type,
        "tags": tags or {"Monitoring": "on", "Name": "test-srv"},
    }


def _make_sync_result(created=1, updated=0, ok=2, deleted=0):
    return {
        "created": ["alarm"] * created,
        "updated": ["alarm"] * updated,
        "ok": ["alarm"] * ok,
        "deleted": ["alarm"] * deleted,
    }


def _make_collector_mock(name="mock_collector", resources=None):
    """__name__ 속성이 있는 collector mock 생성 헬퍼."""
    m = MagicMock()
    m.__name__ = name
    m.collect_monitored_resources.return_value = resources if resources is not None else []
    m.get_metrics.return_value = {}
    return m


# ──────────────────────────────────────────────
# lambda_handler — 기본 동작
# ──────────────────────────────────────────────

class TestLambdaHandlerBasic:
    """lambda_handler의 기본 orchestration 흐름 검증."""

    @mock_aws
    def test_no_resources_returns_ok_with_zero_processed(self):
        """모든 collector가 빈 목록을 반환하면 processed=0으로 ok 반환."""
        from daily_monitor import lambda_handler as lh

        lh._get_cw_client.cache_clear()

        mock_collector = _make_collector_mock(resources=[])

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with patch.object(lh, "_COLLECTOR_MODULES", [mock_collector]):
                result = lh.lambda_handler({}, None)

        assert result["status"] == "ok"
        assert result["processed"] == 0
        assert result["alerts"] == 0

    @mock_aws
    def test_one_resource_processed_and_alarms_synced(self):
        """리소스 1개 → sync + 메트릭 조회 → processed=1."""
        from daily_monitor import lambda_handler as lh

        lh._get_cw_client.cache_clear()

        mock_collector = _make_collector_mock(resources=[_make_resource()])

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch.object(lh, "_COLLECTOR_MODULES", [mock_collector]),
                patch("daily_monitor.lambda_handler.sync_alarms_for_resource", return_value=_make_sync_result()),
                patch("daily_monitor.lambda_handler._process_resource", return_value=0) as mock_proc,
                patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[]),
            ):
                result = lh.lambda_handler({}, None)

        assert result["status"] == "ok"
        assert result["processed"] == 1
        assert mock_proc.call_count == 1

    @mock_aws
    def test_alarm_sync_counts_accumulated(self):
        """2개 리소스의 sync 결과가 누적된다."""
        from daily_monitor import lambda_handler as lh

        lh._get_cw_client.cache_clear()

        resources = [_make_resource("i-001"), _make_resource("i-002")]
        mock_collector = _make_collector_mock(resources=resources)

        sync_result = {"created": ["a"], "updated": [], "ok": ["b", "c"], "deleted": []}

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch.object(lh, "_COLLECTOR_MODULES", [mock_collector]),
                patch("daily_monitor.lambda_handler.sync_alarms_for_resource", return_value=sync_result),
                patch("daily_monitor.lambda_handler._process_resource", return_value=0),
                patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[]),
            ):
                result = lh.lambda_handler({}, None)

        # 2 리소스 × 1 created → 2, 2 리소스 × 2 ok → 4
        assert result["alarms_synced"]["created"] == 2
        assert result["alarms_synced"]["ok"] == 4
        assert result["processed"] == 2

    @mock_aws
    def test_single_account_mode_no_role_arn(self):
        """role_arn 없으면 AssumeRole 없이 단일 계정 모드 실행."""
        from daily_monitor import lambda_handler as lh

        lh._get_cw_client.cache_clear()

        mock_collector = _make_collector_mock(resources=[])

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch.object(lh, "_COLLECTOR_MODULES", [mock_collector]),
                patch("daily_monitor.lambda_handler._switch_account_session") as mock_switch,
                patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[]),
            ):
                result = lh.lambda_handler({}, None)

        mock_switch.assert_not_called()
        assert result["status"] == "ok"

    @mock_aws
    def test_account_id_in_result(self):
        """event에 account_id가 있으면 결과에 포함된다."""
        from daily_monitor import lambda_handler as lh

        lh._get_cw_client.cache_clear()

        mock_collector = _make_collector_mock(resources=[])

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch.object(lh, "_COLLECTOR_MODULES", [mock_collector]),
                patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[]),
            ):
                result = lh.lambda_handler({"account_id": "111122223333"}, None)

        assert result["account_id"] == "111122223333"


# ──────────────────────────────────────────────
# lambda_handler — 에러 처리
# ──────────────────────────────────────────────

class TestLambdaHandlerErrorHandling:
    """collector 에러 발생 시 나머지 collector는 계속 처리."""

    @mock_aws
    def test_collector_client_error_is_skipped(self):
        """collector가 ClientError 발생 시 해당 collector skip, 다음 collector 계속."""
        from daily_monitor import lambda_handler as lh

        lh._get_cw_client.cache_clear()

        failing_collector = _make_collector_mock(name="failing_collector", resources=[])
        failing_collector.collect_monitored_resources.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
            "ListInstances",
        )
        ok_collector = _make_collector_mock(name="ok_collector", resources=[_make_resource()])

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch.object(lh, "_COLLECTOR_MODULES", [failing_collector, ok_collector]),
                patch("daily_monitor.lambda_handler.sync_alarms_for_resource", return_value=_make_sync_result()),
                patch("daily_monitor.lambda_handler._process_resource", return_value=0),
                patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[]),
                patch("daily_monitor.lambda_handler.send_error_alert"),
            ):
                result = lh.lambda_handler({}, None)

        # ok_collector의 리소스는 처리됨
        assert result["status"] == "ok"
        assert result["processed"] == 1

    @mock_aws
    def test_sync_alarm_error_does_not_abort_processing(self):
        """sync_alarms_for_resource 에러 발생 시 메트릭 처리는 계속."""
        from daily_monitor import lambda_handler as lh

        lh._get_cw_client.cache_clear()

        mock_collector = _make_collector_mock(resources=[_make_resource()])

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch.object(lh, "_COLLECTOR_MODULES", [mock_collector]),
                patch(
                    "daily_monitor.lambda_handler.sync_alarms_for_resource",
                    side_effect=ClientError(
                        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
                        "DescribeAlarms",
                    ),
                ),
                patch("daily_monitor.lambda_handler._process_resource", return_value=0) as mock_proc,
                patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[]),
            ):
                result = lh.lambda_handler({}, None)

        # sync 에러 후에도 _process_resource는 호출됨
        assert mock_proc.call_count == 1
        assert result["status"] == "ok"

    @mock_aws
    def test_process_resource_error_does_not_abort_other_resources(self):
        """첫 번째 리소스 처리 에러가 두 번째 리소스에 영향 없음."""
        from daily_monitor import lambda_handler as lh

        lh._get_cw_client.cache_clear()

        resources = [_make_resource("i-001"), _make_resource("i-002")]
        mock_collector = _make_collector_mock(resources=resources)

        call_count = {"n": 0}

        def side_effect(rid, rtype, tags, mod):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ClientError(
                    {"Error": {"Code": "InternalError", "Message": "error"}},
                    "GetMetricStatistics",
                )
            return 0

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch.object(lh, "_COLLECTOR_MODULES", [mock_collector]),
                patch("daily_monitor.lambda_handler.sync_alarms_for_resource", return_value=_make_sync_result()),
                patch("daily_monitor.lambda_handler._process_resource", side_effect=side_effect),
                patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[]),
                patch("daily_monitor.lambda_handler.send_error_alert"),
            ):
                result = lh.lambda_handler({}, None)

        # i-001 에러, i-002 정상 처리 → processed=1
        assert result["processed"] == 1


# ──────────────────────────────────────────────
# lambda_handler — 멀티 어카운트 세션 전환
# ──────────────────────────────────────────────

class TestMultiAccountSessionSwitch:
    """role_arn 주입 시 STS AssumeRole 호출 및 에러 처리."""

    @mock_aws
    def test_role_arn_triggers_assume_role(self):
        """role_arn이 있으면 _switch_account_session이 호출된다."""
        from daily_monitor import lambda_handler as lh

        lh._get_cw_client.cache_clear()

        mock_collector = _make_collector_mock(resources=[])

        event = {
            "account_id": "111122223333",
            "role_arn": "arn:aws:iam::111122223333:role/AlarmManagerRole",
        }

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch.object(lh, "_COLLECTOR_MODULES", [mock_collector]),
                patch("daily_monitor.lambda_handler._switch_account_session") as mock_switch,
                patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[]),
            ):
                result = lh.lambda_handler(event, None)

        mock_switch.assert_called_once_with(
            "arn:aws:iam::111122223333:role/AlarmManagerRole",
            "111122223333",
        )
        assert result["status"] == "ok"

    @mock_aws
    def test_assume_role_failure_returns_error(self):
        """AssumeRole 실패 시 status=error, reason=assume_role_failed 반환."""
        from daily_monitor import lambda_handler as lh

        lh._get_cw_client.cache_clear()

        event = {
            "account_id": "111122223333",
            "role_arn": "arn:aws:iam::111122223333:role/AlarmManagerRole",
        }

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with patch(
                "daily_monitor.lambda_handler._switch_account_session",
                side_effect=ClientError(
                    {"Error": {"Code": "AccessDenied", "Message": "Not authorized"}},
                    "AssumeRole",
                ),
            ):
                result = lh.lambda_handler(event, None)

        assert result["status"] == "error"
        assert result["reason"] == "assume_role_failed"
        assert result["account_id"] == "111122223333"

    @mock_aws
    def test_non_dict_event_uses_single_account_mode(self):
        """event가 dict가 아니면 role_arn 없이 단일 계정 모드로 동작."""
        from daily_monitor import lambda_handler as lh

        lh._get_cw_client.cache_clear()

        mock_collector = _make_collector_mock(resources=[])

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            with (
                patch.object(lh, "_COLLECTOR_MODULES", [mock_collector]),
                patch("daily_monitor.lambda_handler._switch_account_session") as mock_switch,
                patch("daily_monitor.lambda_handler._cleanup_orphan_alarms", return_value=[]),
            ):
                result = lh.lambda_handler(None, None)

        mock_switch.assert_not_called()
        assert result["status"] == "ok"


# ──────────────────────────────────────────────
# _cleanup_orphan_alarms
# ──────────────────────────────────────────────

class TestCleanupOrphanAlarms:
    """고아 알람 정리 로직 검증."""

    @mock_aws
    def test_no_alarms_returns_empty_list(self):
        """알람이 없으면 빈 목록 반환."""
        from daily_monitor.lambda_handler import _cleanup_orphan_alarms, _get_cw_client

        _get_cw_client.cache_clear()

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)
            result = _cleanup_orphan_alarms()

        assert result == []

    @mock_aws
    def test_alive_resources_alarms_not_deleted(self):
        """resolve_alive_ids가 리소스를 alive로 반환하면 알람 미삭제."""
        from daily_monitor.lambda_handler import (
            _cleanup_orphan_alarms, _get_cw_client, ec2_collector,
        )

        _get_cw_client.cache_clear()

        resource_id = "i-0abc1234def567890"
        alarm_name = f"[EC2] test CPUUtilization > 80% (TagName: {resource_id})"

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)

            # CloudWatch에 알람 등록
            cw = boto3.client("cloudwatch", region_name="us-east-1")
            cw.put_metric_alarm(
                AlarmName=alarm_name,
                MetricName="CPUUtilization",
                Namespace="AWS/EC2",
                Statistic="Average",
                Period=300,
                EvaluationPeriods=2,
                Threshold=80.0,
                ComparisonOperator="GreaterThanThreshold",
                Dimensions=[{"Name": "InstanceId", "Value": resource_id}],
            )

            with patch.object(ec2_collector, "resolve_alive_ids", return_value={resource_id}):
                deleted = _cleanup_orphan_alarms()

        assert deleted == []

    @mock_aws
    def test_terminated_resource_alarm_deleted(self):
        """resolve_alive_ids가 빈 집합을 반환하면 알람 삭제."""
        from daily_monitor.lambda_handler import (
            _cleanup_orphan_alarms, _get_cw_client, ec2_collector,
        )

        _get_cw_client.cache_clear()

        resource_id = "i-0deadbeef00000001"
        alarm_name = f"[EC2] test CPUUtilization > 80% (TagName: {resource_id})"

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)

            cw = boto3.client("cloudwatch", region_name="us-east-1")
            cw.put_metric_alarm(
                AlarmName=alarm_name,
                MetricName="CPUUtilization",
                Namespace="AWS/EC2",
                Statistic="Average",
                Period=300,
                EvaluationPeriods=2,
                Threshold=80.0,
                ComparisonOperator="GreaterThanThreshold",
                Dimensions=[{"Name": "InstanceId", "Value": resource_id}],
            )

            # resolve_alive_ids가 빈 집합 반환 (terminated)
            with patch.object(ec2_collector, "resolve_alive_ids", return_value=set()):
                deleted = _cleanup_orphan_alarms()

        assert alarm_name in deleted

        # CW에서도 실제 삭제됐는지 확인
        cw = boto3.client("cloudwatch", region_name="us-east-1")
        resp = cw.describe_alarms(AlarmNames=[alarm_name])
        assert len(resp["MetricAlarms"]) == 0

    @mock_aws
    def test_unknown_resource_type_alarm_skipped(self):
        """알 수 없는 resource_type은 collector 없으므로 스킵 (삭제 안 함)."""
        from daily_monitor.lambda_handler import _cleanup_orphan_alarms, _get_cw_client

        _get_cw_client.cache_clear()

        alarm_name = "[UNKNOWN] something > 0 (TagName: unknown-id)"

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)

            cw = boto3.client("cloudwatch", region_name="us-east-1")
            cw.put_metric_alarm(
                AlarmName=alarm_name,
                MetricName="SomeMetric",
                Namespace="AWS/Unknown",
                Statistic="Average",
                Period=300,
                EvaluationPeriods=1,
                Threshold=0.0,
                ComparisonOperator="GreaterThanThreshold",
            )

            deleted = _cleanup_orphan_alarms()

        assert alarm_name not in deleted


# ──────────────────────────────────────────────
# _classify_alarm
# ──────────────────────────────────────────────

class TestClassifyAlarm:
    """알람 이름 분류 로직 검증."""

    def test_new_format_ec2_alarm(self):
        from daily_monitor.lambda_handler import _classify_alarm

        result = {}
        _classify_alarm("[EC2] myserver CPUUtilization > 80% (TagName: i-0abc1234)", result)

        assert "EC2" in result
        assert "i-0abc1234" in result["EC2"]

    def test_new_format_rds_alarm(self):
        from daily_monitor.lambda_handler import _classify_alarm

        result = {}
        _classify_alarm("[RDS] mydb FreeStorageSpace < 10GB (TagName: db-prod)", result)

        assert "RDS" in result
        assert "db-prod" in result["RDS"]

    def test_legacy_format_ec2_alarm(self):
        from daily_monitor.lambda_handler import _classify_alarm

        result = {}
        _classify_alarm("i-0abc1234-CPUUtilization-prod", result)

        assert "EC2" in result
        assert "i-0abc1234" in result["EC2"]

    def test_unknown_format_ignored(self):
        from daily_monitor.lambda_handler import _classify_alarm

        result = {}
        _classify_alarm("some-unrelated-alarm-name", result)

        assert result == {}

    def test_multiple_alarms_same_resource(self):
        from daily_monitor.lambda_handler import _classify_alarm

        result = {}
        _classify_alarm("[EC2] srv CPU > 80% (TagName: i-001)", result)
        _classify_alarm("[EC2] srv Memory > 80% (TagName: i-001)", result)

        assert len(result["EC2"]["i-001"]) == 2
