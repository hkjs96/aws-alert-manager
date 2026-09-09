"""
알림 채널 코어 — 어댑터 레지스트리 + 채널 검증 + 조건 매칭 (tasks 2.2, design.md D3)

여기서 고정하는 것은 **확장 규칙**이다. 새 채널 유형을 파일 하나로 추가할 수 있어야 하고,
그때 자격증명 노출·조건 매칭이 자동으로 따라와야 한다. 그래서 개별 어댑터를 하나씩 검사하는
대신, **등록된 모든 어댑터가 만족해야 하는 계약**을 검사한다(TestEveryAdapter) — 나중에 추가한
Teams·Discord도 테스트를 새로 안 써도 이 그물에 걸린다.
"""

import json

import pytest

from common import notification_adapters as A
from common.notification_adapters import AdapterError, Notification
from common.notification_channel import (
    MATCH_FIELDS,
    Channel,
    ChannelError,
    channel_from_item,
    channel_to_dict,
    channel_to_item,
    matches,
    notification_from_event,
    select,
    validate_channel,
    validate_match,
)

SLACK_URL = "https://hooks.slack.com/services/T000/B000/xxxxxxxx"


def body(**over):
    b = {"name": "운영팀 슬랙", "type": "slack", "config": {"webhook_url": SLACK_URL}}
    b.update(over)
    return b


def ev(**over):
    e = {"customer_id": "cust-1", "account_id": "111122223333", "severity": "SEV-2",
         "resource_type": "RDS", "resource_id": "db-1", "metric_key": "CPUUtilization",
         "state": "ALARM", "alarm_name": "[RDS] db-1 CPU > 80%",
         "state_reason": "Threshold crossed", "occurred_at": "2026-09-09T01:00:00Z"}
    e.update(over)
    return e


def ch(**over):
    c = {"channel_id": "c1", "customer_id": "cust-1", "name": "ops", "type": "slack",
         "config": {"webhook_url": SLACK_URL}, "match": {}, "enabled": True}
    c.update(over)
    return Channel(**c)


# ────────────────────────────────── 모든 어댑터가 지켜야 하는 계약

class TestEveryAdapter:
    """새 채널 유형이 추가돼도 이 검사들이 자동으로 적용된다."""

    @pytest.mark.parametrize("adapter", A.all_adapters(), ids=lambda a: a.type)
    def test_declares_identity_and_fields(self, adapter):
        assert adapter.type and adapter.label
        assert adapter.fields, "설정 필드가 하나도 없는 채널은 보낼 곳을 모른다"
        assert adapter.rate_limit_per_sec > 0
        assert len({f.name for f in adapter.fields}) == len(adapter.fields)

    @pytest.mark.parametrize("adapter", A.all_adapters(), ids=lambda a: a.type)
    def test_render_produces_a_non_empty_payload(self, adapter):
        payload = adapter.render(Notification(title="테스트 알람", severity="SEV-1"))
        assert isinstance(payload, dict) and payload
        assert any(str(v).strip() for v in payload.values())

    @pytest.mark.parametrize("adapter", A.all_adapters(), ids=lambda a: a.type)
    def test_secret_values_never_appear_in_public_config(self, adapter):
        """자격증명이 응답으로 새지 않는 것은 어댑터별로 기억할 일이 아니라 구조가 보장한다."""
        config = {f.name: f"secret-value-{f.name}" for f in adapter.fields}
        public = adapter.public_config(config)
        for name in adapter.secret_fields:
            assert public[name] == "(설정됨)"
            assert f"secret-value-{name}" not in json.dumps(public, ensure_ascii=False)

    @pytest.mark.parametrize("adapter", A.all_adapters(), ids=lambda a: a.type)
    def test_required_fields_are_enforced(self, adapter):
        required = [f for f in adapter.fields if f.required]
        if not required:
            pytest.skip("필수 필드 없음")
        with pytest.raises(AdapterError):
            adapter.validate_config({})

    @pytest.mark.parametrize("adapter", A.all_adapters(), ids=lambda a: a.type)
    def test_unknown_config_keys_are_rejected(self, adapter):
        """조용히 버리면 오타를 친 채 '저장됨'을 받고 발송은 안 된다."""
        with pytest.raises(AdapterError, match="모르는 설정"):
            adapter.validate_config({"nope": "x"})


class TestRegistry:
    def test_lists_the_types_we_ship(self):
        assert set(A.types()) >= {"slack", "email", "webhook"}

    def test_unknown_type_names_the_alternatives(self):
        with pytest.raises(AdapterError) as e:
            A.get("carrier-pigeon")
        assert "slack" in str(e.value)

    def test_duplicate_registration_is_refused(self):
        with pytest.raises(ValueError, match="already registered"):
            A.register(A.Adapter(type="slack", label="x", fields=(), render=lambda n: {}))


class TestSlackAdapter:
    def test_rejects_a_non_slack_url(self):
        with pytest.raises(AdapterError, match="Slack"):
            A.SLACK.validate_config({"webhook_url": "https://example.com/hook"})

    def test_rejects_http(self):
        with pytest.raises(AdapterError):
            A.SLACK.validate_config({"webhook_url": "http://hooks.slack.com/x"})

    def test_render_carries_a_plain_text_fallback_and_severity_colour(self):
        p = A.SLACK.render(Notification(title="CPU 높음", severity="SEV-1", resource_id="i-1"))
        assert p["text"]
        assert p["attachments"][0]["color"] == "#d32f2f"

    def test_rate_limit_is_one_per_second(self):
        assert A.SLACK.rate_limit_per_sec == 1.0


class TestEmailAdapter:
    def test_accepts_a_comma_separated_list(self):
        out = A.EMAIL.validate_config({"addresses": "a@b.com, c@d.co.kr"})
        assert out["addresses"] == "a@b.com, c@d.co.kr"

    def test_rejects_a_malformed_address(self):
        with pytest.raises(AdapterError, match="형식"):
            A.EMAIL.validate_config({"addresses": "a@b.com, nope"})

    def test_subject_is_capped(self):
        p = A.EMAIL.render(Notification(title="x" * 300))
        assert len(p["subject"]) <= 100


class TestWebhookAdapter:
    def test_auth_header_is_optional_and_secret(self):
        out = A.WEBHOOK.validate_config({"url": "https://example.com/h"})
        assert "auth_header" not in out
        assert "auth_header" in A.WEBHOOK.secret_fields

    def test_body_is_json(self):
        p = A.WEBHOOK.render(Notification(title="알람", severity="SEV-3"))
        assert json.loads(p["body"])["severity"] == "SEV-3"


# ────────────────────────────────── 채널 검증

class TestValidateChannel:
    def test_builds_a_channel_and_assigns_an_id(self):
        c = validate_channel(body(), customer_id="cust-1")
        assert c.type == "slack" and c.customer_id == "cust-1" and c.enabled
        assert c.config["webhook_url"] == SLACK_URL
        assert len(c.channel_id) == 16

    def test_empty_customer_is_a_global_channel(self):
        assert validate_channel(body(), customer_id="").is_global

    def test_name_is_required(self):
        with pytest.raises(ChannelError, match="이름"):
            validate_channel(body(name="  "), customer_id="cust-1")

    def test_unknown_type_is_rejected(self):
        with pytest.raises(ChannelError, match="채널 유형"):
            validate_channel(body(type="fax"), customer_id="cust-1")

    def test_bad_credential_is_rejected_at_the_api(self):
        with pytest.raises(ChannelError):
            validate_channel(body(config={"webhook_url": "not-a-url"}), customer_id="cust-1")


class TestValidateMatch:
    def test_empty_means_everything(self):
        assert validate_match(None) == {} and validate_match({}) == {}

    def test_normalises_a_single_value_to_a_list(self):
        assert validate_match({"severity": "SEV-1"}) == {"severity": ["SEV-1"]}

    def test_deduplicates_and_keeps_order(self):
        assert validate_match({"resource_type": ["RDS", "EC2", "RDS"]})["resource_type"] == ["RDS", "EC2"]

    def test_unknown_axis_is_rejected(self):
        """조용히 버리면 'RDS만'이라 믿는데 실제로는 전부 받는다."""
        with pytest.raises(ChannelError, match="쓸 수 없는"):
            validate_match({"region": ["ap-northeast-2"]})

    def test_bad_severity_is_rejected(self):
        with pytest.raises(ChannelError, match="등급"):
            validate_match({"severity": ["CRITICAL"]})

    def test_every_declared_axis_is_accepted(self):
        raw = {f: (["SEV-1"] if f == "severity" else ["x"]) for f in MATCH_FIELDS}
        assert set(validate_match(raw)) == set(MATCH_FIELDS)


# ────────────────────────────────── 직렬화

class TestSerialisation:
    def test_round_trip_through_the_table(self):
        c = validate_channel(body(match={"severity": ["SEV-1"]}), customer_id="cust-1")
        back = channel_from_item(channel_to_item(c))
        assert (back.channel_id, back.type, back.config, back.match) == (
            c.channel_id, c.type, c.config, c.match)

    def test_api_response_never_contains_the_credential(self):
        c = validate_channel(body(), customer_id="cust-1")
        blob = json.dumps(channel_to_dict(c), ensure_ascii=False)
        assert SLACK_URL not in blob
        assert "(설정됨)" in blob

    def test_response_still_says_which_type_and_whether_configured(self):
        d = channel_to_dict(validate_channel(body(), customer_id="cust-1"))
        assert d["type"] == "slack" and d["type_label"] == "Slack"
        assert d["config"]["webhook_url"] == "(설정됨)"

    def test_stored_item_keeps_the_credential(self):
        """응답에서는 빼되 저장은 해야 발송이 된다 (design.md D7)."""
        item = channel_to_item(validate_channel(body(), customer_id="cust-1"))
        assert item["config"]["webhook_url"] == SLACK_URL


# ────────────────────────────────── 매칭

class TestMatching:
    def test_no_conditions_receives_everything(self):
        assert matches(ch(), ev()) is True

    def test_disabled_channel_receives_nothing(self):
        assert matches(ch(enabled=False), ev()) is False

    def test_severity_filter(self):
        c = ch(match={"severity": ["SEV-1", "SEV-2"]})
        assert matches(c, ev(severity="SEV-2")) is True
        assert matches(c, ev(severity="SEV-3")) is False

    def test_resource_type_filter(self):
        c = ch(match={"resource_type": ["RDS", "DocDB"]})
        assert matches(c, ev(resource_type="RDS")) is True
        assert matches(c, ev(resource_type="EC2")) is False

    def test_axes_are_combined_with_and(self):
        c = ch(match={"severity": ["SEV-1"], "resource_type": ["RDS"]})
        assert matches(c, ev(severity="SEV-1", resource_type="RDS")) is True
        assert matches(c, ev(severity="SEV-1", resource_type="EC2")) is False

    def test_missing_event_field_does_not_match_a_narrowed_axis(self):
        assert matches(ch(match={"resource_type": ["RDS"]}), ev(resource_type="")) is False

    def test_unknown_stored_axis_is_ignored_not_fatal(self):
        """옛 행이 남아도 좁히지 못할 뿐 다른 고객사로 새지는 않는다 — 경계는 키가 지킨다."""
        assert matches(ch(match={"legacy_axis": ["x"]}), ev()) is True

    def test_select_returns_matching_channels_in_a_stable_order(self):
        a = ch(channel_id="a", name="b-ops")
        b = ch(channel_id="b", name="a-ops")
        g = ch(channel_id="g", name="noc", customer_id="")
        miss = ch(channel_id="m", name="db", match={"resource_type": ["EC2"]})
        got = select([a, b, g, miss], ev())
        assert [c.channel_id for c in got] == ["b", "a", "g"]

    def test_select_on_no_channels(self):
        assert select([], ev()) == []


class TestNotificationFromEvent:
    def test_maps_the_history_item(self):
        n = notification_from_event(ev(), url="https://app/alerts")
        assert n.title == "[RDS] db-1 CPU > 80%" and n.severity == "SEV-2"
        assert n.resource_id == "db-1" and n.url == "https://app/alerts"
        assert n.count == 1 and n.is_bundle is False

    def test_bundle_summary_mentions_the_rest(self):
        n = notification_from_event(ev(), count=7)
        assert n.is_bundle and "외 6건" in n.summary_line()

    def test_missing_fields_do_not_crash(self):
        n = notification_from_event({})
        assert n.title == "알람" and n.summary_line()
