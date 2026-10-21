"""채널 저장 전 미리보기 — 지난 30일 이력에 조건을 대 본다."""

import json
from unittest.mock import patch

from api_handler.routes import notification_channels as route


def _event(body, email="tlsgks678@mz.co.kr"):
    return {"body": json.dumps(body), "requestContext": {"authorizer": {"jwt": {"claims": {"email": email}}}}}


ROWS = [
    {"group_id": "g1", "severity": "SEV-3", "account_id": "1", "resource_type": "EC2"},
    {"group_id": "g1", "severity": "SEV-3", "account_id": "1", "resource_type": "EC2"},   # 같은 묶음 = 메시지 1건
    {"group_id": "g2", "severity": "SEV-2", "account_id": "1", "resource_type": "ALB"},
    {"group_id": "g3", "severity": "SEV-5", "account_id": "1", "resource_type": "TG"},
]


def _run(body, rows=ROWS, scope_ok=True):
    scope = type("S", (), {"allows_customer": lambda self, c: scope_ok})()
    with patch.object(route, "_history_rows", return_value=list(rows)) as hist, \
            patch.object(route, "scope_for", return_value=scope):
        resp = route.preview_channel(_event(body))
    return resp["statusCode"], json.loads(resp["body"]), hist


def test_counts_messages_by_group_for_matching_severity():
    code, body, hist = _run({"customer_id": "HOME", "match": {"severity": ["SEV-1", "SEV-2", "SEV-3"]}})
    assert code == 200
    assert (body["messages"], body["events"], body["events_total"]) == (2, 3, 4)
    assert body["per_day"] == round(2 / 30, 1)
    assert body["by_severity"] == {"SEV-2": 1, "SEV-3": 2}
    assert len(hist.call_args.args[1]) == 30


def test_empty_match_counts_everything():
    _, body, _ = _run({"customer_id": "HOME", "match": {}})
    assert body["messages"] == 3


def test_out_of_scope_customer_is_404():
    code, _, _ = _run({"customer_id": "OTHER", "match": {}}, scope_ok=False)
    assert code == 404


def test_bad_match_is_400():
    code, _, _ = _run({"customer_id": "HOME", "match": {"colour": ["red"]}})
    assert code == 400


# ── 테스트 보내기 ─────────────────────────────────────────────

from common.notification_send import DeliveryResult  # noqa: E402


def _test_event(customer_id="HOME", channel_id="c1"):
    return {"pathParameters": {"id": channel_id}, "queryStringParameters": {"customer_id": customer_id},
            "requestContext": {"authorizer": {"jwt": {"claims": {"email": "tlsgks678@mz.co.kr"}}}}}


def _send(channel, scope_ok=True, result=None):
    scope = type("S", (), {"allows_customer": lambda self, c: scope_ok})()
    sent = {}

    def fake_deliver(ch, note, **kw):
        sent["note"] = note
        return result or DeliveryResult(channel_id="c1", channel_name="n", type="slack", ok=True, status=200)

    with patch.object(route, "_load", return_value=channel), \
            patch.object(route, "scope_for", return_value=scope), \
            patch("common.notification_send.deliver", side_effect=fake_deliver):
        resp = route.test_channel(_test_event())
    return resp["statusCode"], json.loads(resp["body"]), sent


def _slack_channel():
    from common.notification_channel import Channel
    return Channel(channel_id="c1", customer_id="HOME", name="n", type="slack",
                   config={"webhook_url": "https://hooks.slack.com/services/x"})


def test_sends_a_marked_test_message():
    code, body, sent = _send(_slack_channel())
    assert code == 200 and body["ok"] is True and body["status"] == 200
    assert sent["note"].title.startswith("[테스트]") and "실제 알람이 아닙니다" in sent["note"].reason


def test_failure_is_reported_not_raised():
    bad = DeliveryResult(channel_id="c1", channel_name="n", type="slack", ok=False, status=404, error="no_service")
    code, body, _ = _send(_slack_channel(), result=bad)
    assert code == 200 and body["ok"] is False and body["error"] == "no_service"


def test_other_customers_channel_is_404():
    code, _, sent = _send(_slack_channel(), scope_ok=False)
    assert code == 404 and sent == {}


def test_missing_channel_is_404():
    code, _, _ = _send(None)
    assert code == 404
