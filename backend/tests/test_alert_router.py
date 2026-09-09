"""
Alert Router (`alert_router/lambda_handler.py`) — tasks 2.2.3

그룹 하나 = 채널당 한 통. 고정하는 것:
- 묶음: 알람 200건이 한 그룹이면 200통이 아니라 **한 통 + "외 199건"** (R6-9)
- 대표는 **가장 심각한 것** — 묶음 제목이 SEV-5인데 안에 SEV-1이 있으면 안 된다
- **중복 발송 방지**: 그룹을 조건부로 선점(claim)한다. 재시도·sweep이 겹쳐도 두 번 안 간다
- 조건에 맞는 채널만 고른다. 채널이 없으면 오류가 아니라 기록만 남긴다
- 결과는 구성원 이력에 남는다 — "왜 안 왔나"를 조사하는 첫 자리
"""

import json
from unittest.mock import patch

import pytest

from fakes_ddb import FakeHistoryTable, FakeStateTable, conditional_failure
from common.notification_send import DeliveryResult

GROUP = {"group_id": "g-abc-20260909", "group_key": "cust-1#SEV-2",
         "customer_id": "cust-1", "severity": "SEV-2"}


class FakeChannelTable:
    def __init__(self, items=None):
        self.items = list(items or [])

    def query(self, KeyConditionExpression=None, **_):
        wanted = KeyConditionExpression.get_expression()["values"][1]
        return {"Items": [dict(i) for i in self.items if i["customer_id"] == wanted]}


class ClaimingStateTable(FakeStateTable):
    """`update_item`에 조건부 선점을 흉내 낸다 — 라우터의 중복 방지가 여기 걸려 있다."""

    def __init__(self, delivered=False):
        super().__init__()
        self.delivered = delivered
        self.claims = 0

    def update_item(self, Key, UpdateExpression=None, ConditionExpression=None,
                    ExpressionAttributeValues=None, **_):
        self.claims += 1
        if self.delivered:
            raise conditional_failure()
        self.delivered = True


def channel_item(channel_id="c1", customer_id="cust-1", match=None, ctype="slack",
                 enabled=True, name="운영팀"):
    config = ({"webhook_url": "https://hooks.slack.com/services/T/B/x"}
              if ctype == "slack" else {"url": "https://example.com/h"})
    return {"customer_id": customer_id, "channel_id": channel_id, "name": name,
            "type": ctype, "config": config, "match": match or {}, "enabled": enabled}


def member(series="1#i-1#CPU", key="2026-09-09T01:00:00Z#a", *, severity="SEV-2",
           final="notify", occurred="2026-09-09T01:00:00Z", **over):
    m = {"series_id": series, "event_key": key, "group_id": GROUP["group_id"],
         "severity": severity, "final_action": final, "occurred_at": occurred,
         "state": "ALARM", "resource_type": "EC2", "resource_id": "i-1",
         "alarm_name": "[EC2] i-1 CPU > 80%", "customer_id": "cust-1"}
    m.update(over)
    return m


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("EVENT_HISTORY_TABLE", "hist")
    monkeypatch.setenv("ALERT_STATE_TABLE", "state")
    monkeypatch.setenv("NOTIFICATION_CHANNEL_TABLE", "channels")
    monkeypatch.setenv("ALERT_CONSOLE_URL", "https://app/alerts")
    from alert_router import lambda_handler as r
    r._get_ddb.cache_clear()
    yield
    r._get_ddb.cache_clear()


class StaleIndexHistory(FakeHistoryTable):
    """GSI 최종 일관성 재현 — 인덱스 사본에는 방금 쓴 `final_action`이 아직 없다.

    라이브에서 이 때문에 발송이 통째로 누락됐다(상태 머신은 SUCCEEDED, 알림만 안 감).
    기본 테이블(batch_get)은 현재 값을 준다 — 라우터는 그쪽을 봐야 한다.
    """

    name = "hist"

    def query(self, IndexName=None, **kw):
        resp = super().query(IndexName=IndexName, **kw)
        if IndexName:
            stale = []
            for item in resp["Items"]:
                copy = dict(item)
                copy.pop("final_action", None)
                stale.append(copy)
            return {"Items": stale}
        return resp

    def batch_get(self, keys):
        out = []
        for k in keys:
            item = self.items.get((k["series_id"], k["event_key"]))
            if item:
                out.append(dict(item))
        return out


class FakeDdbResource:
    """`batch_get_item`만 흉내 낸다. 일관 읽기를 안 쓰면 같은 버그가 되살아난다."""

    def __init__(self, history):
        self.history = history

    def batch_get_item(self, RequestItems=None):
        table_name, spec = next(iter(RequestItems.items()))
        assert spec.get("ConsistentRead") is True, "일관 읽기가 아니면 인덱스 지연에 다시 걸린다"
        return {"Responses": {table_name: self.history.batch_get(spec["Keys"])}}


def _with_base_table_reads(hist):
    """기본 테이블 일관 읽기를 흉내 낼 수 있게 최소 속성을 붙인다."""
    if not hasattr(hist, "name"):
        hist.name = "hist"
    if not hasattr(hist, "batch_get"):
        hist.batch_get = lambda keys: [
            dict(hist.items[(k["series_id"], k["event_key"])])
            for k in keys if (k["series_id"], k["event_key"]) in hist.items]
    return hist


def run(members, channels, *, state=None, results=None, group=None, history=None):
    from alert_router import lambda_handler as r
    hist = _with_base_table_reads(history if history is not None else FakeHistoryTable())
    for m in members:
        hist.put_item(Item=m)
    state = state or ClaimingStateTable()
    chan = FakeChannelTable(channels)
    sent = {}

    def fake_deliver_all(chs, notification, **kw):
        sent["channels"] = chs
        sent["notification"] = notification
        return results if results is not None else [
            DeliveryResult(channel_id=c.channel_id, channel_name=c.name,
                           type=c.type, ok=True, attempts=1, status=200) for c in chs]

    with patch.object(r, "_tables", return_value=(hist, state, chan)), \
         patch.object(r, "_get_ddb", return_value=FakeDdbResource(hist)), \
         patch.object(r, "deliver_all", side_effect=fake_deliver_all):
        out = r.lambda_handler({"group": group or GROUP}, None)
    return out, sent, hist, state


class TestBundling:
    def test_two_hundred_members_become_one_message(self):
        members = [member(series=f"1#i-{i}#CPU", key=f"2026-09-09T01:00:0{i % 10}Z#{i}")
                   for i in range(200)]
        out, sent, _, _ = run(members, [channel_item()])
        assert out["members"] == 200 and out["channels"] == 1 and out["sent"] == 1
        assert sent["notification"].count == 200
        assert "외 199건" in sent["notification"].summary_line()

    def test_representative_is_the_most_severe(self):
        members = [member(series="1#a#CPU", key="k1", severity="SEV-4"),
                   member(series="1#b#CPU", key="k2", severity="SEV-1",
                          alarm_name="[RDS] db down"),
                   member(series="1#c#CPU", key="k3", severity="SEV-3")]
        _, sent, _, _ = run(members, [channel_item()])
        assert sent["notification"].severity == "SEV-1"
        assert sent["notification"].title == "[RDS] db down"

    def test_ties_break_on_earliest(self):
        members = [member(series="1#a#CPU", key="k1", occurred="2026-09-09T02:00:00Z",
                          alarm_name="늦은 것"),
                   member(series="1#b#CPU", key="k2", occurred="2026-09-09T01:00:00Z",
                          alarm_name="이른 것")]
        _, sent, _, _ = run(members, [channel_item()])
        assert sent["notification"].title == "이른 것"

    def test_console_url_is_attached(self):
        _, sent, _, _ = run([member()], [channel_item()])
        assert sent["notification"].url == "https://app/alerts"


class TestOnlyNotifyMembersAreSent:
    def test_suppressed_members_are_ignored(self):
        members = [member(key="k1", final="notify"),
                   member(series="1#b#CPU", key="k2", final="suppress")]
        out, sent, _, _ = run(members, [channel_item()])
        assert out["members"] == 1 and sent["notification"].count == 1

    def test_group_with_nothing_to_notify_sends_nothing(self):
        out, sent, _, state = run([member(final="suppress")], [channel_item()])
        assert out["sent"] == 0 and out["reason"] == "nothing_to_notify"
        assert "notification" not in sent
        assert state.claims == 0, "보낼 게 없으면 선점도 하지 않는다"

    def test_unfinalised_members_are_ignored(self):
        out, _, _, _ = run([member(final=None)], [channel_item()])
        assert out["reason"] == "nothing_to_notify"


class TestChannelSelection:
    def test_conditions_narrow_the_channels(self):
        channels = [channel_item("all"),
                    channel_item("sev1", match={"severity": ["SEV-1"]}),
                    channel_item("ec2", match={"resource_type": ["EC2"]})]
        out, sent, _, _ = run([member(severity="SEV-2")], channels)
        assert {c.channel_id for c in sent["channels"]} == {"all", "ec2"}
        assert out["channels"] == 2

    def test_disabled_channels_are_skipped(self):
        out, _, _, _ = run([member()], [channel_item("off", enabled=False)])
        assert out["reason"] == "no_channel" and out["sent"] == 0

    def test_global_channels_are_included(self):
        channels = [channel_item("mine"), channel_item("noc", customer_id="__global__")]
        _, sent, _, _ = run([member()], channels)
        assert {c.channel_id for c in sent["channels"]} == {"mine", "noc"}

    def test_other_customers_channels_are_never_used(self):
        channels = [channel_item("mine"), channel_item("theirs", customer_id="cust-2")]
        _, sent, _, _ = run([member()], channels)
        assert {c.channel_id for c in sent["channels"]} == {"mine"}

    def test_no_matching_channel_is_recorded_not_an_error(self):
        out, sent, _, state = run([member()], [channel_item(match={"severity": ["SEV-1"]})])
        assert out["reason"] == "no_channel" and out["sent"] == 0
        assert "notification" not in sent
        assert state.claims == 0, "안 보냈으면 선점하지 않는다 — 채널이 생기면 다시 시도할 수 있어야"

    def test_channel_with_a_removed_type_is_skipped_not_fatal(self):
        channels = [channel_item("gone", ctype="pager-that-no-longer-exists"),
                    channel_item("ok")]
        out, sent, _, _ = run([member()], channels)
        assert out["sent"] == 1 and {c.channel_id for c in sent["channels"]} == {"ok"}


class TestClaimPreventsDoubleSend:
    def test_claims_before_sending(self):
        _, _, _, state = run([member()], [channel_item()])
        assert state.claims == 1 and state.delivered is True

    def test_second_run_sends_nothing(self):
        """상태 머신 재시도나 sweep이 겹쳐도 같은 알림이 두 번 가지 않는다."""
        out, sent, _, _ = run([member()], [channel_item()],
                              state=ClaimingStateTable(delivered=True))
        assert out["reason"] == "already_delivered" and out["sent"] == 0
        assert "notification" not in sent


class TestResultsAreRecorded:
    def test_success_is_written_to_every_member(self):
        members = [member(key="k1"), member(series="1#b#CPU", key="k2")]
        _, _, hist, _ = run(members, [channel_item()])
        for row in list(hist.items.values()):
            assert row["delivered"] is True
            assert row["delivery_results"][0]["ok"] is True
            assert row["delivered_at"].endswith("Z")

    def test_failure_is_recorded_with_the_reason(self):
        fail = [DeliveryResult(channel_id="c1", channel_name="운영팀", type="slack",
                               ok=False, attempts=3, status=500, error="HTTP 500")]
        out, _, hist, _ = run([member()], [channel_item()], results=fail)
        assert out["sent"] == 0 and out["failed"] == 1
        row = next(iter(hist.items.values()))
        assert row["delivered"] is False
        assert row["delivery_results"][0]["error"] == "HTTP 500"

    def test_partial_success_still_counts_as_delivered(self):
        mixed = [DeliveryResult(channel_id="a", channel_name="a", type="slack", ok=True),
                 DeliveryResult(channel_id="b", channel_name="b", type="slack", ok=False,
                                error="HTTP 404")]
        out, _, hist, _ = run([member()], [channel_item("a"), channel_item("b")],
                              results=mixed)
        assert (out["sent"], out["failed"]) == (1, 1)
        assert next(iter(hist.items.values()))["delivered"] is True

    def test_results_carry_no_credential(self):
        _, _, hist, _ = run([member()], [channel_item()])
        blob = json.dumps(list(hist.items.values()), ensure_ascii=False, default=str)
        assert "hooks.slack.com" not in blob


class TestInvocation:
    def test_rejects_a_group_without_identity(self):
        from alert_router import lambda_handler as r
        with pytest.raises(ValueError):
            r.lambda_handler({"group": {}}, None)

    def test_rejects_an_empty_event(self):
        from alert_router import lambda_handler as r
        with pytest.raises(ValueError):
            r.lambda_handler({}, None)


class TestIndexConsistency:
    """GSI는 최종 일관성 — finalize 직후엔 방금 쓴 final_action이 인덱스에 없다.

    라이브에서 이 때문에 발송이 통째로 누락됐다: 상태 머신은 SUCCEEDED인데 알림만 안 갔다.
    인덱스는 **구성원 키**만 주고, 상태는 기본 테이블에서 일관되게 읽어야 한다.
    """

    def test_sends_even_when_the_index_copy_is_stale(self):
        out, sent, _, _ = run([member()], [channel_item()], history=StaleIndexHistory())
        assert out["sent"] == 1, "인덱스 사본을 믿으면 여기서 아무것도 안 간다"
        assert sent["notification"].count == 1

    def test_index_is_only_used_for_keys(self):
        members = [member(series=f"1#i-{i}#CPU", key=f"k{i}") for i in range(3)]
        out, sent, _, _ = run(members, [channel_item()], history=StaleIndexHistory())
        assert out["members"] == 3 and sent["notification"].count == 3


class FakeIncidentTable:
    def __init__(self):
        self.items = {}

    def get_item(self, Key, **_):
        it = self.items.get(Key["incident_id"])
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item, **_):
        self.items[Item["incident_id"]] = dict(Item)


class PointerStateTable(ClaimingStateTable):
    """`inc#` 포인터와 `fp#` 상태를 함께 흉내 낸다."""

    def __init__(self, delivered=False, open_fingerprints=()):
        super().__init__(delivered=delivered)
        self.open_fps = set(open_fingerprints)

    def get_item(self, Key, **_):
        key = Key["state_key"]
        if key.startswith("fp#"):
            series = key[3:]
            return {"Item": {"state_key": key, "episode_open": series in self.open_fps}}
        return super().get_item(Key)


def run_with_incidents(members, channels, *, state=None, monkeypatch=None):
    from alert_router import lambda_handler as r
    hist = _with_base_table_reads(FakeHistoryTable())
    for m in members:
        hist.put_item(Item=m)
    state = state or PointerStateTable()
    chan = FakeChannelTable(channels)
    incidents = FakeIncidentTable()
    sent = {}

    def fake_deliver_all(chs, notification, **kw):
        sent["notification"] = notification
        return [DeliveryResult(channel_id=c.channel_id, channel_name=c.name,
                               type=c.type, ok=True, attempts=1, status=200) for c in chs]

    with patch.dict("os.environ", {"INCIDENT_TABLE": "inc"}), \
         patch.object(r, "_tables", return_value=(hist, state, chan)), \
         patch.object(r, "_incident_table", return_value=incidents), \
         patch.object(r, "_get_ddb", return_value=FakeDdbResource(hist)), \
         patch.object(r, "deliver_all", side_effect=fake_deliver_all):
        out = r.lambda_handler({"group": GROUP}, None)
    return out, sent, incidents, state


class TestIncidentLifecycle:
    """알람이 아니라 사건 단위로 묶는다 (requirements R4)."""

    def test_firing_opens_an_incident_and_stamps_the_notification(self):
        out, sent, incidents, state = run_with_incidents([member()], [channel_item()])
        assert out["incident_id"] and out["incident_status"] == "triggered"
        inc = incidents.items[out["incident_id"]]
        assert inc["members"] == ["1#i-1#CPU"] and inc["customer_id"] == "cust-1"
        assert sent["notification"].incident_id == out["incident_id"]
        assert state.items["inc#cust-1#SEV-2"]["incident_id"] == out["incident_id"]

    def test_second_window_merges_into_the_same_incident(self):
        """30초 창이 여러 번 지나도 원인이 살아 있으면 한 사건이다."""
        from alert_router import lambda_handler as r
        first, _, incidents, state = run_with_incidents(
            [member()], [channel_item()], state=PointerStateTable(open_fingerprints={"1#i-1#CPU"}))

        hist = _with_base_table_reads(FakeHistoryTable())
        hist.put_item(Item=member(series="1#i-2#CPU", key="k2"))
        state.delivered = False          # 새 그룹이므로 발송권을 다시 얻는다
        sent = {}

        def deliver(chs, notification, **kw):
            sent["notification"] = notification
            return [DeliveryResult(channel_id=c.channel_id, channel_name=c.name,
                                   type=c.type, ok=True) for c in chs]

        with patch.dict("os.environ", {"INCIDENT_TABLE": "inc"}), \
             patch.object(r, "_tables", return_value=(hist, state, FakeChannelTable([channel_item()]))), \
             patch.object(r, "_incident_table", return_value=incidents), \
             patch.object(r, "_get_ddb", return_value=FakeDdbResource(hist)), \
             patch.object(r, "deliver_all", side_effect=deliver):
            second = r.lambda_handler({"group": GROUP}, None)

        assert second["incident_id"] == first["incident_id"], "같은 사건이어야 한다"
        inc = incidents.items[second["incident_id"]]
        assert set(inc["members"]) == {"1#i-1#CPU", "1#i-2#CPU"}

    def test_clearing_resolves_when_every_cause_is_back_to_ok(self):
        """원인 알람이 모두 풀리면 자동 해소 (R4-4)."""
        state = PointerStateTable(open_fingerprints={"1#i-1#CPU"})
        _, _, incidents, state = run_with_incidents([member()], [channel_item()], state=state)
        open_id = next(iter(incidents.items))

        from alert_router import lambda_handler as r
        hist = _with_base_table_reads(FakeHistoryTable())
        hist.put_item(Item=member(key="k-ok", state="OK"))
        state.open_fps = set()           # 이제 아무것도 안 울린다
        state.delivered = False
        with patch.dict("os.environ", {"INCIDENT_TABLE": "inc"}), \
             patch.object(r, "_tables", return_value=(hist, state, FakeChannelTable([channel_item()]))), \
             patch.object(r, "_incident_table", return_value=incidents), \
             patch.object(r, "_get_ddb", return_value=FakeDdbResource(hist)), \
             patch.object(r, "deliver_all", side_effect=lambda chs, n, **kw: [
                 DeliveryResult(channel_id=c.channel_id, channel_name=c.name, type=c.type, ok=True)
                 for c in chs]):
            out = r.lambda_handler({"group": GROUP}, None)

        assert out["incident_status"] == "resolved"
        assert incidents.items[open_id]["mttr_sec"] is not None
        assert "inc#cust-1#SEV-2" not in state.items, "포인터가 지워져야 다음 발화가 새 사건을 연다"

    def test_still_firing_cause_blocks_resolution(self):
        state = PointerStateTable(open_fingerprints={"1#i-1#CPU", "1#i-2#CPU"})
        _, _, incidents, state = run_with_incidents(
            [member(), member(series="1#i-2#CPU", key="k2")], [channel_item()], state=state)
        open_id = next(iter(incidents.items))

        from alert_router import lambda_handler as r
        hist = _with_base_table_reads(FakeHistoryTable())
        hist.put_item(Item=member(key="k-ok", state="OK"))
        state.open_fps = {"1#i-2#CPU"}   # 하나는 아직 울린다
        state.delivered = False
        with patch.dict("os.environ", {"INCIDENT_TABLE": "inc"}), \
             patch.object(r, "_tables", return_value=(hist, state, FakeChannelTable([channel_item()]))), \
             patch.object(r, "_incident_table", return_value=incidents), \
             patch.object(r, "_get_ddb", return_value=FakeDdbResource(hist)), \
             patch.object(r, "deliver_all", side_effect=lambda chs, n, **kw: [
                 DeliveryResult(channel_id=c.channel_id, channel_name=c.name, type=c.type, ok=True)
                 for c in chs]):
            out = r.lambda_handler({"group": GROUP}, None)
        assert out["incident_status"] == "triggered"
        assert incidents.items[open_id].get("resolved_at") is None

    def test_delivery_continues_when_the_incident_table_is_absent(self):
        """사건 기록보다 알림이 급하다 — 표가 없어도 발송은 된다."""
        from alert_router import lambda_handler as r
        hist = _with_base_table_reads(FakeHistoryTable())
        hist.put_item(Item=member())
        sent = {}
        with patch.dict("os.environ", {}, clear=False), \
             patch.object(r, "_tables", return_value=(hist, PointerStateTable(),
                                                      FakeChannelTable([channel_item()]))), \
             patch.object(r, "_get_ddb", return_value=FakeDdbResource(hist)), \
             patch.object(r, "deliver_all",
                          side_effect=lambda chs, n, **kw: (sent.update(n=n), [
                              DeliveryResult(channel_id=c.channel_id, channel_name=c.name,
                                             type=c.type, ok=True) for c in chs])[1]):
            import os as _os
            _os.environ.pop("INCIDENT_TABLE", None)
            out = r.lambda_handler({"group": GROUP}, None)
        assert out["sent"] == 1 and out["incident_id"] == ""
        assert sent["n"].incident_id == ""


class ScanningIncidentTable(FakeIncidentTable):
    """`scan` + 조건부 `update_item`까지 흉내 낸다 — 재알림 선점이 여기 걸려 있다."""

    def __init__(self, items=None):
        super().__init__()
        for i in (items or []):
            self.items[i["incident_id"]] = dict(i)
        self.updates = 0

    def scan(self, FilterExpression=None, **_):
        rows = [dict(v) for v in self.items.values()]
        if FilterExpression is not None:
            expr = FilterExpression.get_expression()
            op, wanted = expr["operator"], expr["values"][1]
            if op == "=":
                rows = [r for r in rows if r.get("status") == wanted]
            elif op == "<>":
                rows = [r for r in rows if r.get("status") != wanted]
            else:
                raise AssertionError(f"unsupported scan filter {op}")
        return {"Items": rows}

    def update_item(self, Key, UpdateExpression=None, ConditionExpression=None,
                    ExpressionAttributeValues=None, ExpressionAttributeNames=None, **_):
        from fakes_ddb import _eval
        self.updates += 1
        item = self.items[Key["incident_id"]]
        if ConditionExpression is not None and not _eval(ConditionExpression, item):
            raise conditional_failure()
        values = ExpressionAttributeValues or {}
        if ":s" in values:                      # 정합성 회복의 해소 — 타임라인은 덧붙인다
            item["status"] = values[":s"]
            item["resolved_at"] = values[":at"]
            if ":mttr" in values:
                item["mttr_sec"] = values[":mttr"]
            item["timeline"] = list(item.get("timeline") or []) + list(values[":entry"])
        else:                                   # 재알림 표시
            item["renotified_at"] = values[":new"]
            item["timeline"] = values[":tl"]


def acked_incident(iid="inc-1", *, acked_minutes_ago=90, customer="cust-1",
                   severity="SEV-2", renotified_at=None):
    from datetime import datetime, timedelta, timezone
    from common.incident import acknowledge, merge_events, new_incident
    now = datetime.now(timezone.utc)
    opened = now - timedelta(minutes=acked_minutes_ago + 5)
    inc = new_incident(customer, severity, now=opened, title="[EC2] i-1 CPU > 80%")
    inc = merge_events(inc, [{"series_id": "1#i-1#CPU", "alarm_name": "[EC2] i-1"}], now=opened)
    inc = acknowledge(inc, by="oncall@mz.co.kr", now=now - timedelta(minutes=acked_minutes_ago))
    inc["incident_id"] = iid
    if renotified_at:
        inc["renotified_at"] = renotified_at
    return inc


def run_tick(incidents_items, channels, *, after_sec=3600, open_fps=("1#i-1#CPU",),
             pointers=(), state=None):
    """5분 틱을 돌린다. 기본은 사건의 원인 알람(`1#i-1#CPU`)이 **아직 울리는** 상태다 —
    안 울리면 정합성 회복이 사건을 먼저 닫아 버려 재알림이 아예 대상이 아니다."""
    from alert_router import lambda_handler as r
    from common.alert_suppression import SuppressionPolicy
    incidents = ScanningIncidentTable(incidents_items)
    chan = FakeChannelTable(channels)
    state = state or PointerStateTable(open_fingerprints=open_fps)
    for p in pointers:
        state.items[p["state_key"]] = dict(p)
    sent = []

    def fake_deliver_all(chs, notification, **kw):
        sent.append(notification)
        return [DeliveryResult(channel_id=c.channel_id, channel_name=c.name,
                               type=c.type, ok=True, status=200) for c in chs]

    with patch.dict("os.environ", {"INCIDENT_TABLE": "inc"}), \
         patch.object(r, "_tables", return_value=(None, state, chan)), \
         patch.object(r, "_incident_table", return_value=incidents), \
         patch.object(r, "_policy", return_value=SuppressionPolicy(renotify_after_sec=after_sec)), \
         patch.object(r, "deliver_all", side_effect=fake_deliver_all):
        out = r.lambda_handler({"action": "renotify"}, None)
    return out, sent, incidents, state


def run_renotify(incidents_items, channels, *, after_sec=3600):
    out, sent, incidents, _ = run_tick(incidents_items, channels, after_sec=after_sec)
    return out, sent, incidents


def open_incident(iid="inc-open", *, customer="cust-1", severity="SEV-2", members=("1#i-1#CPU",)):
    from datetime import datetime, timedelta, timezone
    from common.incident import merge_events, new_incident
    opened = datetime.now(timezone.utc) - timedelta(minutes=20)
    inc = new_incident(customer, severity, now=opened, title="[EC2] i-1 CPU > 80%")
    inc = merge_events(inc, [{"series_id": m} for m in members], now=opened)
    inc["incident_id"] = iid
    return inc


class TestReconcile:
    """Deliver 경로가 못 닫은 사건을 5분 틱이 닫는다 (review-phase2 M1).

    `fp#`가 진실이다: 원인 알람이 전부 OK로 돌아왔는데 열린 사건은 어떤 이유로든 5분 안에 닫혀야 한다 —
    안 그러면 확인된 사건이 매시간 영원히 재알림되고 사람이 끊을 방법이 없다.
    """

    def test_resolves_when_every_cause_is_back_to_ok(self):
        pointer = {"state_key": "inc#cust-1#SEV-2", "incident_id": "inc-1"}
        out, sent, incidents, state = run_tick([acked_incident(acked_minutes_ago=90)], [channel_item()],
                                               open_fps=(), pointers=[pointer])
        assert out["resolved"] == 1 and out["checked"] == 1
        assert out["renotified"] == 0 and sent == [], "방금 닫은 사건을 다시 띄우면 안 된다"
        row = incidents.items["inc-1"]
        assert row["status"] == "resolved" and row["resolved_at"]
        assert isinstance(row["mttr_sec"], int) and row["mttr_sec"] > 0
        assert row["timeline"][-1]["kind"] == "resolved" and "정합성" in row["timeline"][-1]["detail"]
        assert row["timeline"][0]["kind"] == "triggered", "타임라인은 덧붙여야지 갈아끼우면 안 된다"
        assert "inc#cust-1#SEV-2" not in state.items

    def test_a_cause_still_firing_keeps_it_open(self):
        out, sent, incidents, _ = run_tick([acked_incident(acked_minutes_ago=90)], [channel_item()],
                                           open_fps={"1#i-1#CPU"})
        assert out["resolved"] == 0 and incidents.items["inc-1"]["status"] == "acknowledged"
        assert out["renotified"] == 1 and len(sent) == 1

    def test_unacknowledged_incidents_are_reconciled_too(self):
        out, sent, incidents, _ = run_tick([open_incident()], [channel_item()], open_fps=())
        assert out["resolved"] == 1 and incidents.items["inc-open"]["status"] == "resolved"
        assert sent == []

    def test_only_one_of_two_causes_ok_is_not_enough(self):
        inc = open_incident(members=("1#i-1#CPU", "1#i-2#CPU"))
        out, _, incidents, _ = run_tick([inc], [channel_item()], open_fps={"1#i-2#CPU"})
        assert out["resolved"] == 0 and incidents.items["inc-open"]["status"] == "triggered"

    def test_pointer_of_a_newer_incident_is_left_alone(self):
        """그새 같은 축에 새 사건이 열렸으면 포인터는 그쪽 것이다 — 지우면 다음 발화가 또 새 사건을 연다."""
        pointer = {"state_key": "inc#cust-1#SEV-2", "incident_id": "inc-newer"}
        out, _, _, state = run_tick([acked_incident(acked_minutes_ago=90)], [channel_item()],
                                    open_fps=(), pointers=[pointer])
        assert out["resolved"] == 1
        assert state.items["inc#cust-1#SEV-2"]["incident_id"] == "inc-newer"

    def test_unreadable_state_keeps_the_incident_open(self):
        """fp#를 못 읽었으면 열려 있다고 본다 — 살아 있는 사건을 성급히 닫지 않는다."""
        from botocore.exceptions import ClientError

        class BrokenState(PointerStateTable):
            def get_item(self, Key, **kw):
                if Key["state_key"].startswith("fp#"):
                    raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException",
                                                 "Message": "x"}}, "GetItem")
                return super().get_item(Key, **kw)

        out, _, incidents, _ = run_tick([acked_incident(acked_minutes_ago=90)], [channel_item()],
                                        state=BrokenState())
        assert out["resolved"] == 0 and incidents.items["inc-1"]["status"] == "acknowledged"

    def test_runs_even_when_renotify_is_disabled(self):
        out, _, incidents, _ = run_tick([acked_incident(acked_minutes_ago=90)], [channel_item()],
                                        open_fps=(), after_sec=0)
        assert out["resolved"] == 1 and out["reason"] == "disabled"
        assert incidents.items["inc-1"]["status"] == "resolved"

    def test_someone_else_closing_first_is_not_an_error(self):
        """조건부 갱신이 실패하면(라우터가 먼저 닫음) 조용히 넘어간다 — 카운트에도 안 잡힌다."""
        class RacingTable(ScanningIncidentTable):
            def update_item(self, Key, **kw):
                self.items[Key["incident_id"]]["status"] = "resolved"     # 그 사이 누가 닫았다
                return super().update_item(Key, **kw)

        from alert_router import lambda_handler as r
        from common.alert_suppression import SuppressionPolicy
        incidents = RacingTable([acked_incident(acked_minutes_ago=90)])
        with patch.dict("os.environ", {"INCIDENT_TABLE": "inc"}), \
             patch.object(r, "_tables", return_value=(None, PointerStateTable(), FakeChannelTable([]))), \
             patch.object(r, "_incident_table", return_value=incidents), \
             patch.object(r, "_policy", return_value=SuppressionPolicy()):
            out = r.lambda_handler({"action": "tick"}, None)
        assert out["resolved"] == 0 and out["checked"] == 1

    def test_one_broken_row_does_not_stop_the_tick(self):
        class HalfBroken(ScanningIncidentTable):
            def update_item(self, Key, **kw):
                if Key["incident_id"] == "inc-bad":
                    raise RuntimeError("boom")
                return super().update_item(Key, **kw)

        from alert_router import lambda_handler as r
        from common.alert_suppression import SuppressionPolicy
        incidents = HalfBroken([open_incident(iid="inc-bad"), open_incident(iid="inc-good")])
        with patch.dict("os.environ", {"INCIDENT_TABLE": "inc"}), \
             patch.object(r, "_tables", return_value=(None, PointerStateTable(), FakeChannelTable([]))), \
             patch.object(r, "_incident_table", return_value=incidents), \
             patch.object(r, "_policy", return_value=SuppressionPolicy()):
            out = r.lambda_handler({"action": "tick"}, None)
        assert out["resolved"] == 1 and incidents.items["inc-good"]["status"] == "resolved"


class TestRenotify:
    """확인만 하고 방치된 사건을 다시 띄운다 (R4-6) — 새벽에 ack만 누르고 잠든 경우."""

    def test_sends_when_the_window_has_passed(self):
        out, sent, incidents = run_renotify([acked_incident(acked_minutes_ago=90)],
                                            [channel_item()])
        assert out["renotified"] == 1 and out["sent"] == 1
        note = sent[0]
        assert "미해결" in note.title and note.incident_id == "inc-1"
        assert "확인 후" in note.reason and "oncall@mz.co.kr" in note.reason
        assert incidents.items["inc-1"]["renotified_at"]

    def test_stays_quiet_inside_the_window(self):
        out, sent, _ = run_renotify([acked_incident(acked_minutes_ago=30)], [channel_item()])
        assert out["renotified"] == 0 and sent == []

    def test_marking_prevents_a_second_send_next_tick(self):
        inc = acked_incident(acked_minutes_ago=90)
        out1, _, incidents = run_renotify([inc], [channel_item()])
        assert out1["renotified"] == 1
        out2, sent2, _ = run_renotify(list(incidents.items.values()), [channel_item()])
        assert out2["renotified"] == 0 and sent2 == [], "표시했으면 다음 주기엔 조용해야 한다"

    def test_renotifies_again_after_another_window(self):
        from datetime import datetime, timedelta, timezone
        long_ago = (datetime.now(timezone.utc) - timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
        out, _, _ = run_renotify([acked_incident(acked_minutes_ago=300, renotified_at=long_ago)],
                                 [channel_item()])
        assert out["renotified"] == 1

    def test_triggered_incidents_are_not_touched(self):
        """확인조차 안 된 건은 에스컬레이션의 몫이다 — 여기서 중복으로 울리면 안 된다."""
        from common.incident import merge_events, new_incident
        from datetime import datetime, timezone
        inc = new_incident("cust-1", "SEV-2", now=datetime.now(timezone.utc))
        inc = merge_events(inc, [{"series_id": "1#i-1#CPU"}], now=datetime.now(timezone.utc))
        inc["incident_id"] = "inc-open"
        out, sent, _ = run_renotify([inc], [channel_item()])
        assert out["renotified"] == 0 and sent == []

    def test_disabled_when_the_policy_is_zero(self):
        out, sent, _ = run_renotify([acked_incident(acked_minutes_ago=999)],
                                    [channel_item()], after_sec=0)
        assert out["renotified"] == 0 and out["reason"] == "disabled" and sent == []

    def test_no_channel_means_no_claim(self):
        """보낼 곳이 없으면 표시하지 않는다 — 채널이 생기면 그때 울려야 한다."""
        out, sent, incidents = run_renotify(
            [acked_incident(acked_minutes_ago=90)],
            [channel_item(match={"severity": ["SEV-1"]})])
        assert out["renotified"] == 0 and sent == []
        assert "renotified_at" not in incidents.items["inc-1"]

    def test_severity_conditions_still_apply(self):
        out, sent, _ = run_renotify([acked_incident(acked_minutes_ago=90, severity="SEV-1")],
                                    [channel_item(match={"severity": ["SEV-1"]})])
        assert out["renotified"] == 1 and sent[0].severity == "SEV-1"

    def test_scheduled_event_shape_also_triggers_it(self):
        from alert_router import lambda_handler as r
        from common.alert_suppression import SuppressionPolicy
        incidents = ScanningIncidentTable([])
        with patch.dict("os.environ", {"INCIDENT_TABLE": "inc"}), \
             patch.object(r, "_tables", return_value=(None, PointerStateTable(), FakeChannelTable([]))), \
             patch.object(r, "_incident_table", return_value=incidents), \
             patch.object(r, "_policy", return_value=SuppressionPolicy()):
            out = r.lambda_handler({"detail-type": "Scheduled Event"}, None)
        assert out["checked"] == 0

    def test_group_invocations_still_work(self):
        """재알림 분기를 더해도 기존 발송 경로는 그대로다."""
        out, _, _, _ = run([member()], [channel_item()])
        assert out["sent"] == 1
