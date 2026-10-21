"""열린 사건의 원인 알람을 CloudWatch로 확인해 닫는다 — 삭제된 알람은 해소 이벤트를 보내지 않는다(2026-10-21 HOME)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from common import alarm_liveness as lv

ARN = ("arn:aws:cloudwatch:ap-northeast-2:771283576189:alarm:"
       "[EC2]WEBFIL /webfilter Disk Utilization over 80% (TagName:WEBFIL)")
ARN_MEMBER = f"771283576189#{ARN}#disk_used_percent"
OURS_MEMBER = "771283576189#i-1#CPU"


def _ours(state="OK"):
    return {"AlarmArn": "arn:aws:cloudwatch:ap-northeast-2:771283576189:alarm:ours", "StateValue": state,
            "AlarmName": "[EC2] web CPU > 80% (TagName: i-1)", "AlarmDescription": ""}


class TestParse:
    def test_arn_member_keeps_colons_and_knows_its_region(self):
        m = lv.parse_member(ARN_MEMBER)
        assert (m.account_id, m.alarm_arn, m.metric, m.region) == (
            "771283576189", ARN, "disk_used_percent", "ap-northeast-2")

    def test_ours_member_has_no_region(self):
        m = lv.parse_member(OURS_MEMBER)
        assert (m.resource, m.metric, m.region) == ("i-1", "CPU", "")

    def test_garbage_is_none(self):
        assert lv.parse_member("nohash") is None


class TestClassify:
    def test_arn_member_missing_in_its_region_is_deleted(self):
        assert lv.classify(lv.parse_member(ARN_MEMBER), {"ap-northeast-2": []}) == lv.DELETED

    def test_arn_member_ok_is_not_firing(self):
        alarms = {"ap-northeast-2": [{"AlarmArn": ARN, "StateValue": "OK"}]}
        assert lv.classify(lv.parse_member(ARN_MEMBER), alarms) == lv.NOT_FIRING

    def test_arn_member_alarm_is_firing(self):
        alarms = {"ap-northeast-2": [{"AlarmArn": ARN, "StateValue": "ALARM"}]}
        assert lv.classify(lv.parse_member(ARN_MEMBER), alarms) == lv.FIRING

    def test_unreadable_region_is_unknown_never_deleted(self):
        assert lv.classify(lv.parse_member(ARN_MEMBER), {"ap-northeast-2": None}) == lv.UNKNOWN

    def test_ours_member_matches_by_identity_across_regions(self):
        identity = type("I", (), {"resource_id": "i-1", "metric_key": "CPU"})()
        with patch.object(lv, "identify_alarm", side_effect=lambda a: identity if a["AlarmArn"].endswith("ours") else None):
            m = lv.parse_member(OURS_MEMBER)
            assert lv.classify(m, {"ap-northeast-2": [_ours("ALARM")], "us-east-1": []}) == lv.FIRING
            assert lv.classify(m, {"ap-northeast-2": [], "us-east-1": []}) == lv.DELETED
            # 같은 리소스에 다른 메트릭으로 울리는 알람이 있으면(키 표기 어긋남일 수 있다) 단정하지 않는다
            other = {**_ours("ALARM"), "AlarmArn": "arn:aws:cloudwatch:ap-northeast-2:771283576189:alarm:ours"}
            other_identity = type("I", (), {"resource_id": "i-1", "metric_key": "CPUUtilization"})()
            with patch.object(lv, "identify_alarm", return_value=other_identity):
                assert lv.classify(m, {"ap-northeast-2": [other], "us-east-1": []}) == lv.UNKNOWN
            # 한 리전이라도 못 읽었으면 삭제라고 단정하지 않는다
            assert lv.classify(m, {"ap-northeast-2": [], "us-east-1": None}) == lv.UNKNOWN

    def test_all_quiet_needs_every_member_certain(self):
        assert lv.all_quiet([lv.DELETED, lv.NOT_FIRING])
        assert not lv.all_quiet([lv.DELETED, lv.UNKNOWN])
        assert not lv.all_quiet([lv.DELETED, lv.FIRING])
        assert not lv.all_quiet([])


class TestLiveAlarms:
    def test_unregistered_account_is_unknown(self):
        assert lv.LiveAlarms([], "949501913924").status(lv.parse_member(ARN_MEMBER)) == lv.UNKNOWN

    def test_reads_each_region_once(self):
        live = lv.LiveAlarms([{"account_id": "771283576189", "regions": ["ap-northeast-2"]}], "x")
        with patch.object(live, "_alarms", return_value=[]) as read:
            live.status(lv.parse_member(ARN_MEMBER))
            assert read.call_args_list[0].args == ("771283576189", "ap-northeast-2")
        assert live.regions_for("771283576189") == ["ap-northeast-2", "us-east-1"]


# ── 라우터 5분 점검 ───────────────────────────────────────────────

from tests.test_alert_router import (  # noqa: E402 — 라우터 테스트의 가짜 테이블을 그대로 쓴다
    PointerStateTable, channel_item, open_incident, run_tick,
)


class EpisodeState(PointerStateTable):
    """열린 지문에 에피소드 시작 시각을 싣고, 지문 닫기(UpdateItem)를 기록한다."""

    def __init__(self, open_fps, started_minutes_ago=60):
        super().__init__(open_fingerprints=open_fps)
        self.started = (datetime.now(timezone.utc) - timedelta(minutes=started_minutes_ago)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        self.closed_fps = []

    def get_item(self, Key, **kw):
        out = super().get_item(Key, **kw)
        if Key["state_key"].startswith("fp#") and out["Item"].get("episode_open"):
            out["Item"]["episode_started_at"] = self.started
        return out

    def update_item(self, Key, **kw):
        if Key["state_key"].startswith("fp#"):
            self.closed_fps.append(Key["state_key"][3:])
            self.open_fps.discard(Key["state_key"][3:])
            return {}
        return super().update_item(Key=Key, **kw)


class FakeLive:
    def __init__(self, statuses):
        self.statuses = statuses

    def status(self, member):
        return self.statuses.get(f"{member.account_id}#{member.resource}#{member.metric}", lv.UNKNOWN)


def _tick(inc, state, statuses):
    from alert_router import lambda_handler as r
    with patch.object(r, "_live_alarms", return_value=FakeLive(statuses)):
        return run_tick([inc], [channel_item()], state=state)


class TestRouterClosesGoneAlarms:
    def test_deleted_cause_closes_and_frees_the_fingerprint(self):
        inc = open_incident(members=(ARN_MEMBER,))
        state = EpisodeState({ARN_MEMBER})
        out, sent, incidents, state = _tick(inc, state, {ARN_MEMBER: lv.DELETED})
        row = incidents.items["inc-open"]
        assert out["resolved"] == 1 and row["status"] == "resolved"
        assert "삭제됐거나 해소됨" in row["timeline"][-1]["detail"]
        assert state.closed_fps == [ARN_MEMBER], "열린 지문을 두면 같은 알람의 다음 발화가 중복으로 눌린다"
        assert sent == []

    def test_cause_still_firing_in_cloudwatch_stays_open(self):
        inc = open_incident(members=(ARN_MEMBER,))
        out, _, incidents, state = _tick(inc, EpisodeState({ARN_MEMBER}), {ARN_MEMBER: lv.FIRING})
        assert out["resolved"] == 0 and incidents.items["inc-open"]["status"] == "triggered"
        assert state.closed_fps == []

    def test_unknown_member_keeps_it_open(self):
        inc = open_incident(members=(ARN_MEMBER, OURS_MEMBER))
        out, _, _, _ = _tick(inc, EpisodeState({ARN_MEMBER, OURS_MEMBER}),
                             {ARN_MEMBER: lv.DELETED, OURS_MEMBER: lv.UNKNOWN})
        assert out["resolved"] == 0

    def test_fresh_episode_is_left_alone(self):
        """방금 열린 발화는 해소 이벤트가 오는 중일 수 있다 — 유예 시간 안에는 CloudWatch로 닫지 않는다."""
        inc = open_incident(members=(ARN_MEMBER,))
        out, _, _, _ = _tick(inc, EpisodeState({ARN_MEMBER}, started_minutes_ago=5), {ARN_MEMBER: lv.DELETED})
        assert out["resolved"] == 0


class TestMergeAgeCap:
    def test_old_incident_is_not_merged_into(self):
        from alert_router import lambda_handler as r
        now = datetime.now(timezone.utc)
        assert r._too_old_to_merge({"triggered_at": (now - timedelta(hours=7)).isoformat()}, now)
        assert not r._too_old_to_merge({"triggered_at": (now - timedelta(hours=1)).isoformat()}, now)
        assert not r._too_old_to_merge({"triggered_at": ""}, now)
