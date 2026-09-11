"""
전송 계층 (`common/notification_send.py`) — tasks 2.2.4~2.2.6

고정하는 것:
- 설정 오류(4xx)는 재시도하지 않고, 일시적 실패(5xx·타임아웃·429)만 재시도한다
- **한 채널이 실패해도 나머지는 계속 간다** (R6-7)
- 오류 기록에 자격증명이 남지 않는다 — 응답에서 가린 의미가 없어진다
- 같은 유형끼리는 어댑터가 선언한 속도만큼 간격을 둔다
"""

import json
import urllib.error

import pytest

from common.notification_adapters import Notification
from common.notification_channel import Channel
from common.notification_send import (
    MAX_ATTEMPTS,
    DeliveryResult,
    Transports,
    deliver,
    deliver_all,
)

SLACK_URL = "https://hooks.slack.com/services/T0/B0/super-secret"
NOTE = Notification(title="CPU 높음", severity="SEV-1", resource_id="i-1")


def slack(channel_id="c1", name="ops"):
    return Channel(channel_id=channel_id, customer_id="cust-1", name=name, type="slack",
                   config={"webhook_url": SLACK_URL})


def webhook(url="https://example.com/hook", auth=None):
    config = {"url": url}
    if auth:
        config["auth_header"] = auth
    return Channel(channel_id="w1", customer_id="cust-1", name="hook", type="webhook",
                   config=config)


def email(addresses="a@b.com, c@d.com"):
    return Channel(channel_id="e1", customer_id="cust-1", name="메일", type="email",
                   config={"addresses": addresses})


class FakeTransports(Transports):
    def __init__(self, statuses=None, raises=None):
        self.calls = []
        self.emails = []
        self._statuses = list(statuses or [200])
        self._raises = list(raises or [])

    def post(self, url, body, headers, timeout):
        self.calls.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
        if self._raises:
            exc = self._raises.pop(0)
            if exc is not None:
                raise exc
        return self._statuses.pop(0) if self._statuses else 200

    def send_email(self, sender, recipients, subject, body):
        self.emails.append({"sender": sender, "recipients": recipients,
                            "subject": subject, "body": body})
        if self._raises:
            exc = self._raises.pop(0)
            if exc is not None:
                raise exc


def http_error(code):
    return urllib.error.HTTPError("https://x", code, "err", {}, None)


class TestHttpsDelivery:
    def test_posts_the_rendered_payload_to_the_declared_endpoint(self):
        t = FakeTransports()
        r = deliver(slack(), NOTE, transports=t, sleep=lambda _: None)
        assert r.ok and r.attempts == 1 and r.status == 200
        assert t.calls[0]["url"] == SLACK_URL
        assert "CPU 높음" in t.calls[0]["body"]

    def test_webhook_body_is_the_adapters_json(self):
        t = FakeTransports()
        deliver(webhook(), NOTE, transports=t, sleep=lambda _: None)
        assert json.loads(t.calls[0]["body"])["severity"] == "SEV-1"

    def test_auth_header_is_sent_when_configured(self):
        t = FakeTransports()
        deliver(webhook(auth="Bearer abc"), NOTE, transports=t, sleep=lambda _: None)
        assert t.calls[0]["headers"]["Authorization"] == "Bearer abc"

    def test_no_auth_header_when_not_configured(self):
        t = FakeTransports()
        deliver(webhook(), NOTE, transports=t, sleep=lambda _: None)
        assert "Authorization" not in t.calls[0]["headers"]

    def test_missing_endpoint_is_reported_without_retrying(self):
        broken = Channel(channel_id="x", customer_id="c", name="x", type="slack", config={})
        t = FakeTransports()
        r = deliver(broken, NOTE, transports=t, sleep=lambda _: None)
        assert r.ok is False and t.calls == []
        assert "webhook_url" in r.error


class TestRetryPolicy:
    @pytest.mark.parametrize("status", [500, 502, 503, 504, 429, 408])
    def test_transient_status_is_retried_then_succeeds(self, status):
        t = FakeTransports(statuses=[status, 200])
        r = deliver(slack(), NOTE, transports=t, sleep=lambda _: None)
        assert r.ok and r.attempts == 2

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 410])
    def test_config_errors_are_not_retried(self, status):
        """다시 보내도 같은 답이 온다 — 지연만 늘고 속도 제한만 먹는다."""
        t = FakeTransports(statuses=[status, 200])
        r = deliver(slack(), NOTE, transports=t, sleep=lambda _: None)
        assert r.ok is False and r.attempts == 1 and r.status == status

    def test_gives_up_after_the_attempt_limit(self):
        t = FakeTransports(statuses=[503] * (MAX_ATTEMPTS + 2))
        r = deliver(slack(), NOTE, transports=t, sleep=lambda _: None)
        assert r.ok is False and r.attempts == MAX_ATTEMPTS
        assert len(t.calls) == MAX_ATTEMPTS

    def test_network_error_is_retried(self):
        t = FakeTransports(raises=[urllib.error.URLError("boom"), None], statuses=[200])
        r = deliver(slack(), NOTE, transports=t, sleep=lambda _: None)
        assert r.ok and r.attempts == 2

    def test_http_error_object_is_treated_as_its_status(self):
        t = FakeTransports(raises=[http_error(404)])
        r = deliver(slack(), NOTE, transports=t, sleep=lambda _: None)
        assert r.ok is False and r.status == 404 and r.attempts == 1

    def test_backoff_grows(self):
        waits = []
        t = FakeTransports(statuses=[503, 503, 503])
        deliver(slack(), NOTE, transports=t, sleep=waits.append)
        assert waits == sorted(waits) and len(waits) == MAX_ATTEMPTS - 1


class TestCredentialsNeverLeakIntoErrors:
    def test_error_text_hides_the_webhook_url(self):
        """실패 기록으로 새면 응답에서 가린 의미가 없다."""
        t = FakeTransports(raises=[urllib.error.URLError(f"cannot reach {SLACK_URL}")] * MAX_ATTEMPTS)
        r = deliver(slack(), NOTE, transports=t, sleep=lambda _: None)
        assert r.ok is False
        assert SLACK_URL not in r.error and "(가림)" in r.error

    def test_result_dict_carries_no_credential(self):
        t = FakeTransports(statuses=[404])
        r = deliver(slack(), NOTE, transports=t, sleep=lambda _: None)
        assert SLACK_URL not in json.dumps(r.to_dict(), ensure_ascii=False)


class TestEmailDelivery:
    def test_sends_to_every_address(self):
        t = FakeTransports()
        r = deliver(email(), NOTE, transports=t, sender="noreply@mz.co.kr",
                    sleep=lambda _: None)
        assert r.ok
        assert t.emails[0]["recipients"] == ["a@b.com", "c@d.com"]
        assert t.emails[0]["sender"] == "noreply@mz.co.kr"
        assert t.emails[0]["subject"]

    def test_missing_sender_is_reported_clearly(self):
        t = FakeTransports()
        r = deliver(email(), NOTE, transports=t, sender="", sleep=lambda _: None)
        assert r.ok is False and "ALERT_EMAIL_SENDER" in r.error
        assert t.emails == []

    def test_ses_failure_is_captured(self):
        t = FakeTransports(raises=[RuntimeError("not verified")] * MAX_ATTEMPTS)
        r = deliver(email(), NOTE, transports=t, sender="x@y.com", sleep=lambda _: None)
        assert r.ok is False and "not verified" in r.error


class TestDeliverAll:
    def test_one_failure_does_not_stop_the_others(self):
        t = FakeTransports(statuses=[404, 200, 200])
        results = deliver_all([slack("a", "첫째"), slack("b", "둘째"), webhook()],
                              NOTE, transports=t, sleep=lambda _: None)
        assert [r.ok for r in results] == [False, True, True]
        assert len(t.calls) == 3

    def test_results_identify_the_channel(self):
        t = FakeTransports(statuses=[200])
        r = deliver_all([slack("a", "운영팀")], NOTE, transports=t, sleep=lambda _: None)[0]
        assert (r.channel_id, r.channel_name, r.type) == ("a", "운영팀", "slack")

    def test_same_type_is_paced_by_the_declared_rate(self):
        waits = []
        t = FakeTransports(statuses=[200, 200])
        deliver_all([slack("a"), slack("b")], NOTE, transports=t, sleep=waits.append)
        assert any(w > 0 for w in waits), "Slack은 초당 1건이라 간격이 필요하다"

    def test_first_send_is_not_delayed(self):
        waits = []
        t = FakeTransports(statuses=[200])
        deliver_all([slack("a")], NOTE, transports=t, sleep=waits.append)
        assert waits == []

    def test_empty_channel_list(self):
        assert deliver_all([], NOTE, transports=FakeTransports()) == []

    def test_channels_past_the_deadline_are_recorded_not_sent(self):
        """Lambda가 중간에 죽으면 어디까지 갔는지조차 안 남는다 — 예산이 다 되면 남은 채널을 기록으로 남긴다 (L5)."""
        from unittest.mock import patch
        import common.notification_send as ns

        class Clock:
            t = 0.0

            def monotonic(self):
                self.t += 10.0          # 호출마다 10초씩 흐른다
                return self.t

        t = FakeTransports(statuses=[200, 200, 200])
        with patch.object(ns, "time", Clock()):
            results = deliver_all([slack("a"), slack("b", name="b"), slack("c", name="c")], NOTE,
                                  transports=t, sleep=lambda _: None, deadline=15.0)
        assert results[0].ok is True
        assert [r.error for r in results[1:]] == [ns.BUDGET_EXCEEDED] * 2
        assert [r.channel_id for r in results] == ["a", "b", "c"], "건너뛴 채널도 결과에 남아야 한다"

    def test_no_deadline_means_every_channel_is_attempted(self):
        t = FakeTransports(statuses=[200, 200, 200])
        results = deliver_all([slack("a"), slack("b", name="b"), slack("c", name="c")], NOTE,
                              transports=t, sleep=lambda _: None)
        assert all(r.ok for r in results) and len(results) == 3


class TestRealTransportDoesNotFollowRedirects:
    """https로 검증한 URL이 http로 302하면 urllib가 Authorization을 들고 따라간다 (review-phase2 L4).

    가짜가 아니라 진짜 `Transports.post`를 로컬 서버에 쏜다 — 리다이렉트 처리는 urllib 내부라
    가짜로는 검증이 안 된다.
    """

    def test_a_302_is_reported_not_followed(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        hits = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):                                # noqa: N802
                hits.append((self.path, self.headers.get("Authorization")))
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                if self.path == "/hook":
                    self.send_response(302)
                    self.send_header("Location", "/leak")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/hook"
            with pytest.raises(urllib.error.HTTPError) as exc:
                Transports().post(url, "{}", {"Authorization": "Bearer secret"}, 5)
            assert exc.value.code == 302
            assert [p for p, _ in hits] == ["/hook"], "리다이렉트 대상(/leak)으로 가면 안 된다"
        finally:
            server.shutdown()
            server.server_close()

    def test_a_302_result_is_a_recorded_failure_without_retry(self):
        """3xx는 설정 오류다 — 재시도해도 같다."""
        t = FakeTransports(raises=[http_error(302)])
        r = deliver(webhook(), NOTE, transports=t, sleep=lambda _: None)
        assert r.ok is False and r.status == 302 and r.attempts == 1


class TestDeliveryResult:
    def test_to_dict_drops_empty_fields(self):
        d = DeliveryResult(channel_id="c", channel_name="n", type="slack", ok=True,
                           attempts=1, status=200).to_dict()
        assert "error" not in d and d["status"] == 200
