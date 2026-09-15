"""
alarm-sync 드라이런 도구 (`scripts/alarm_sync_dryrun.py`) — resource-type-registry P0.3

고정하는 것:
- **쓰기 호출이 실제 클라이언트에 닿지 않는다.** put/delete/tag는 스텁이 먹고, 읽기는 위임된다.
- 진짜 생성 경로를 돌리므로 payload가 `create_alarms_for_resource`의 것과 같다 — 이름을 따로 계산하지 않는다.
- 덤프는 결정적이다(정렬) — 이관 전후 diff의 전제.
"""

import importlib.util
import json
import types
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("alarm_sync_dryrun", ROOT / "scripts" / "alarm_sync_dryrun.py")
dryrun = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dryrun)


class FakeRealCloudWatch:
    """읽기 전용 실제 클라이언트 노릇. 쓰기가 여기 오면 실패다."""

    def __init__(self):
        self.reads = []
        self.meta = types.SimpleNamespace(region_name="us-east-1")    # boto3 클라이언트의 meta.region_name

    def describe_alarms(self, **kw):
        self.reads.append(("describe_alarms", kw))
        return {"MetricAlarms": [], "CompositeAlarms": []}

    def get_paginator(self, name):
        fake = self

        class P:
            def paginate(self, **kw):
                fake.reads.append((name, kw))
                yield {"MetricAlarms": [], "CompositeAlarms": [], "Metrics": []}
        return P()

    def list_metrics(self, **kw):
        self.reads.append(("list_metrics", kw))
        return {"Metrics": []}

    def list_tags_for_resource(self, **kw):
        return {"Tags": []}

    def put_metric_alarm(self, **kw):
        raise AssertionError("write reached the real client")

    def tag_resource(self, **kw):
        raise AssertionError("write reached the real client")

    def delete_alarms(self, **kw):
        raise AssertionError("write reached the real client")


@pytest.fixture
def fake_real(monkeypatch):
    import common._clients as clients
    real = FakeRealCloudWatch()
    monkeypatch.setattr(clients, "_get_cw_client", lambda: real)
    monkeypatch.setattr(clients, "_get_cw_client_for_region", lambda region: real)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    with patch("common.alarm_builder._get_aws_account_id", return_value="111122223333"):
        yield real


def test_recording_stub_swallows_writes_and_delegates_reads():
    real = FakeRealCloudWatch()
    cw = dryrun.RecordingCloudWatch(real)
    cw.put_metric_alarm(AlarmName="x")
    cw.tag_resource(ResourceARN="arn", Tags=[])
    cw.delete_alarms(AlarmNames=["x"])
    assert [p["AlarmName"] for p in cw.puts] == ["x"] and cw.deletes == [["x"]] and len(cw.tags) == 1
    assert cw.describe_alarms(AlarmNamePrefix="[SQS]") == {"MetricAlarms": [], "CompositeAlarms": []}
    assert real.reads and real.reads[0][0] == "describe_alarms"


def test_plan_runs_the_real_creation_path_without_writing(fake_real):
    plan = dryrun._plan({"type": "SQS", "id": "orders", "region": "us-east-1",
                         "tags": {"Monitoring": "on", "Name": "orders-q"}})
    assert plan["type"] == "SQS" and plan["id"] == "orders"
    names = [a["AlarmName"] for a in plan["alarms"]]
    assert len(names) == 3, names                                   # SQS 정의 3개
    assert all(n.startswith("[SQS] orders-q ") and n.endswith("(TagName: orders)") for n in names)
    for a in plan["alarms"]:
        assert a["Namespace"] == "AWS/SQS"
        assert a["Dimensions"] == [{"Name": "QueueName", "Value": "orders"}]
        assert "Threshold" in a and "ComparisonOperator" in a
    assert plan["created_names"] == sorted(names)
    assert plan["internal_tags"] == {} and plan["threshold_tags"] == {}


def test_plan_output_is_sorted_for_diffing(fake_real):
    plan = dryrun._plan({"type": "SQS", "id": "orders", "region": "us-east-1", "tags": {"Monitoring": "on"}})
    names = [a["AlarmName"] for a in plan["alarms"]]
    assert names == sorted(names)


def test_plan_carries_internal_and_threshold_tags_for_the_diff(fake_real):
    plan = dryrun._plan({"type": "SQS", "id": "orders", "region": "us-east-1",
                         "tags": {"Monitoring": "on", "_cluster_name": "c", "Threshold_SQSOldestMessage": "600"}})
    assert plan["internal_tags"] == {"_cluster_name": "c"}
    assert plan["threshold_tags"] == {"Threshold_SQSOldestMessage": "600"}
    oldest = next(a for a in plan["alarms"] if a["MetricName"] == "ApproximateAgeOfOldestMessage")
    assert oldest["Threshold"] == 600.0, "태그 임계치가 payload에 반영돼야 한다"


def test_diff_reports_added_removed_and_changed(tmp_path, capsys):
    before = {"resources": [{"alarms": [{"AlarmName": "a", "Threshold": 1}, {"AlarmName": "b", "Threshold": 1}]}]}
    after = {"resources": [{"alarms": [{"AlarmName": "a", "Threshold": 2}, {"AlarmName": "c", "Threshold": 1}]}]}
    pb, pa = tmp_path / "b.json", tmp_path / "a.json"
    pb.write_text(json.dumps(before), encoding="utf-8")
    pa.write_text(json.dumps(after), encoding="utf-8")
    assert dryrun.diff(pb, pa) == 1
    out = capsys.readouterr().out
    assert "only before: 1" in out and "only after: 1" in out and "changed: 1" in out
    pa.write_text(json.dumps(before), encoding="utf-8")
    assert dryrun.diff(pb, pa) == 0, "같으면 0 — 이관 게이트의 종료 코드"
