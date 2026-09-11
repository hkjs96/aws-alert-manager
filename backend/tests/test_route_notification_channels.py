"""
/alert/channels CRUD (tasks 2.2.1)

가장 중요한 것은 **자격증명이 어떤 응답에도 안 나오는가**다(R6-8). 그 다음이 수정 시
자격증명을 다시 안 보내도 유지되는가 — 안 그러면 이름만 고쳤는데 발송이 조용히 멈춘다.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from test_api_handler import _event

SLACK_URL = "https://hooks.slack.com/services/T000/B000/secret-part"
ADMIN = "admin@mz.co.kr"
MEMBER = "member@mz.co.kr"


def _reject_empty_key(*values):
    """DynamoDB는 **키 속성에 빈 문자열을 허용하지 않는다.** 라이브에서만 드러났던 제약이라
    가짜도 똑같이 거절한다 — 안 그러면 같은 종류의 버그를 또 놓친다."""
    for v in values:
        if v == "":
            raise ClientError(
                {"Error": {"Code": "ValidationException",
                           "Message": "The AttributeValue for a key attribute cannot "
                                      "contain an empty string value. Key: customer_id"}},
                "Query")


class FakeTable:
    """(customer_id, channel_id) 복합 키 테이블. 키 제약까지 실제처럼 지킨다."""

    def __init__(self, items=None):
        self.items = {}
        for i in (items or []):
            self.items[(i["customer_id"], i["channel_id"])] = dict(i)

    def get_item(self, Key, **_):
        _reject_empty_key(Key["customer_id"], Key["channel_id"])
        it = self.items.get((Key["customer_id"], Key["channel_id"]))
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item, ConditionExpression=None, **_):
        from fakes_ddb import _eval, conditional_failure
        _reject_empty_key(Item["customer_id"], Item["channel_id"])
        cur = self.items.get((Item["customer_id"], Item["channel_id"]))
        if ConditionExpression is not None and not _eval(ConditionExpression, cur):
            raise conditional_failure()
        self.items[(Item["customer_id"], Item["channel_id"])] = dict(Item)

    def delete_item(self, Key, **_):
        _reject_empty_key(Key["customer_id"], Key["channel_id"])
        self.items.pop((Key["customer_id"], Key["channel_id"]), None)

    def query(self, KeyConditionExpression=None, **_):
        wanted = KeyConditionExpression.get_expression()["values"][1]
        _reject_empty_key(wanted)
        return {"Items": [dict(v) for k, v in sorted(self.items.items()) if k[0] == wanted]}


def stored(channel_id="c1", customer_id="cust-1", **over):
    from common.notification_channel import storage_key
    customer_id = storage_key(customer_id)
    item = {"customer_id": customer_id, "channel_id": channel_id, "name": "운영팀",
            "type": "slack", "config": {"webhook_url": SLACK_URL}, "match": {},
            "enabled": True}
    item.update(over)
    return item


def call(method, path, *, table=None, body=None, qs=None, path_params=None,
         email=ADMIN, admins=ADMIN):
    from api_handler.routes import notification_channels as nc
    table = table if table is not None else FakeTable()
    ev = _event(method, path, body=body, qs=qs, path_params=path_params)
    ev["requestContext"]["authorizer"] = {"jwt": {"claims": {"email": email}}}
    with patch.object(nc, "notification_channel_table", return_value=table), \
         patch.object(nc, "scan_all", side_effect=lambda t: list(t.items.values())), \
         patch.dict("os.environ", {"ADMIN_EMAILS": admins}):
        from api_handler.lambda_handler import lambda_handler
        resp = lambda_handler(ev, None)
    return resp, json.loads(resp["body"] or "{}"), table


def new_body(**over):
    b = {"name": "운영팀 슬랙", "type": "slack", "config": {"webhook_url": SLACK_URL},
         "customer_id": "cust-1"}
    b.update(over)
    return b


class TestCredentialsNeverLeak:
    def test_create_response_hides_the_webhook(self):
        resp, b, _ = call("POST", "/alert/channels", body=new_body())
        assert resp["statusCode"] == 201, resp["body"]
        assert SLACK_URL not in resp["body"]
        assert b["config"]["webhook_url"] == "(설정됨)"

    def test_list_response_hides_the_webhook(self):
        resp, b, _ = call("GET", "/alert/channels", table=FakeTable([stored()]))
        assert resp["statusCode"] == 200
        assert SLACK_URL not in resp["body"]
        assert b["channels"][0]["config"]["webhook_url"] == "(설정됨)"

    def test_update_response_hides_the_webhook(self):
        resp, _, _ = call("PUT", "/alert/channels/c1", table=FakeTable([stored()]),
                          body={"name": "새 이름"}, qs={"customer_id": "cust-1"},
                          path_params={"id": "c1"})
        assert resp["statusCode"] == 200, resp["body"]
        assert SLACK_URL not in resp["body"]

    def test_the_value_is_still_stored(self):
        """응답에서만 가린다 — 저장은 해야 보낼 수 있다 (design.md D7)."""
        _, _, table = call("POST", "/alert/channels", body=new_body())
        item = next(iter(table.items.values()))
        assert item["config"]["webhook_url"] == SLACK_URL


class TestCreate:
    def test_assigns_an_id_and_stores_the_row(self):
        resp, b, table = call("POST", "/alert/channels", body=new_body())
        assert resp["statusCode"] == 201
        assert b["channel_id"] and len(table.items) == 1

    def test_rejects_a_bad_webhook(self):
        resp, b, table = call("POST", "/alert/channels",
                              body=new_body(config={"webhook_url": "https://example.com/x"}))
        assert resp["statusCode"] == 400 and b["code"] == "VALIDATION_ERROR"
        assert table.items == {}

    def test_rejects_an_unknown_type(self):
        resp, b, _ = call("POST", "/alert/channels", body=new_body(type="fax"))
        assert resp["statusCode"] == 400

    def test_rejects_an_unknown_condition_axis(self):
        resp, _, _ = call("POST", "/alert/channels", body=new_body(match={"region": ["x"]}))
        assert resp["statusCode"] == 400

    def test_stores_conditions(self):
        _, b, _ = call("POST", "/alert/channels",
                       body=new_body(match={"severity": ["SEV-1"], "resource_type": ["RDS"]}))
        assert b["match"] == {"severity": ["SEV-1"], "resource_type": ["RDS"]}

    def test_per_customer_limit(self):
        table = FakeTable([stored(channel_id=f"c{i}") for i in range(50)])
        resp, b, _ = call("POST", "/alert/channels", table=table, body=new_body())
        assert resp["statusCode"] == 400 and b["code"] == "LIMIT_EXCEEDED"

    def test_existing_id_is_a_conflict_not_an_overwrite(self):
        """POST가 PUT 노릇을 하면 자격증명이 조용히 바뀐다 (review-phase2 L2)."""
        table = FakeTable([stored("c1")])
        resp, b, t = call("POST", "/alert/channels", table=table,
                          body=new_body(channel_id="c1", config={"webhook_url": SLACK_URL + "/other"}))
        assert resp["statusCode"] == 409 and b["code"] == "CONFLICT"
        assert t.items[("cust-1", "c1")]["config"]["webhook_url"] == SLACK_URL, "기존 값이 남아야 한다"

    def test_unavailable_type_is_refused_with_the_reason(self, monkeypatch):
        """보낼 수 없는 유형을 받으면 저장만 되고 발송은 매번 실패한다 — 그건 이력에만 남는다 (L3)."""
        monkeypatch.delenv("ALERT_EMAIL_SENDER", raising=False)
        resp, b, t = call("POST", "/alert/channels",
                          body=new_body(type="email", config={"addresses": "a@mz.co.kr"}))
        assert resp["statusCode"] == 400 and b["code"] == "TYPE_UNAVAILABLE"
        assert "ALERT_EMAIL_SENDER" in b["message"] and t.items == {}

    def test_available_type_is_accepted_once_configured(self, monkeypatch):
        monkeypatch.setenv("ALERT_EMAIL_SENDER", "alerts@mz.co.kr")
        resp, _, _ = call("POST", "/alert/channels",
                          body=new_body(type="email", config={"addresses": "a@mz.co.kr"}))
        assert resp["statusCode"] == 201

    def test_malformed_json_is_a_400(self):
        from api_handler.routes import notification_channels as nc
        ev = _event("POST", "/alert/channels")
        ev["body"] = "{not json"
        ev["requestContext"]["authorizer"] = {"jwt": {"claims": {"email": ADMIN}}}
        with patch.object(nc, "notification_channel_table", return_value=FakeTable()), \
             patch.dict("os.environ", {"ADMIN_EMAILS": ADMIN}):
            from api_handler.lambda_handler import lambda_handler
            resp = lambda_handler(ev, None)
        assert resp["statusCode"] == 400


class TestGlobalChannelsAreAdminOnly:
    """고객사 지정이 없으면 모든 고객사의 알림을 받는다 — 전역 정비창과 같은 폭발 반경."""

    def test_member_cannot_create(self):
        resp, b, table = call("POST", "/alert/channels",
                              body=new_body(customer_id=""), email=MEMBER)
        assert resp["statusCode"] == 403 and b["code"] == "FORBIDDEN"
        assert table.items == {}

    def test_admin_can_create(self):
        resp, b, table = call("POST", "/alert/channels",
                              body=new_body(customer_id=""), email=ADMIN)
        assert resp["statusCode"] == 201 and b["is_global"] is True
        # 도메인에서는 ""이지만 표에는 센티넬로 들어간다 (빈 키는 DynamoDB가 거절한다)
        assert {k[0] for k in table.items} == {"__global__"}
        assert b["customer_id"] == ""

    def test_global_channel_round_trips_through_list_and_delete(self):
        table = FakeTable()
        _, created, _ = call("POST", "/alert/channels",
                             body=new_body(customer_id=""), email=ADMIN, table=table)
        _, listed, _ = call("GET", "/alert/channels", table=table, qs={"customer_id": ""})
        assert [c["channel_id"] for c in listed["channels"]] == [created["channel_id"]]
        resp, _, _ = call("DELETE", f"/alert/channels/{created['channel_id']}", table=table,
                          qs={"customer_id": ""}, path_params={"id": created["channel_id"]},
                          email=ADMIN)
        assert resp["statusCode"] == 204 and table.items == {}

    def test_sentinel_cannot_be_used_as_a_customer_id(self):
        """센티넬을 고객사 ID로 쓰면 전역 채널로 위장할 수 있다."""
        resp, b, _ = call("POST", "/alert/channels",
                          body=new_body(customer_id="__global__"), email=ADMIN)
        assert resp["statusCode"] == 400 and b["code"] == "VALIDATION_ERROR"

    def test_member_can_create_a_customer_channel(self):
        resp, _, _ = call("POST", "/alert/channels", body=new_body(), email=MEMBER)
        assert resp["statusCode"] == 201

    def test_member_cannot_delete_a_global_channel(self):
        table = FakeTable([stored(customer_id="")])
        resp, _, _ = call("DELETE", "/alert/channels/c1", table=table, qs={"customer_id": ""},
                          path_params={"id": "c1"}, email=MEMBER)
        assert resp["statusCode"] == 403
        assert len(table.items) == 1


class TestUpdate:
    def test_keeps_the_credential_when_it_is_not_resent(self):
        """화면은 가림 문자열만 갖고 있다. 이름만 고쳤는데 발송이 멈추면 안 된다."""
        table = FakeTable([stored()])
        resp, b, _ = call("PUT", "/alert/channels/c1", table=table, body={"name": "새 이름"},
                          qs={"customer_id": "cust-1"}, path_params={"id": "c1"})
        assert resp["statusCode"] == 200 and b["name"] == "새 이름"
        assert table.items[("cust-1", "c1")]["config"]["webhook_url"] == SLACK_URL

    def test_redacted_placeholder_also_means_unchanged(self):
        table = FakeTable([stored()])
        resp, _, _ = call("PUT", "/alert/channels/c1", table=table,
                          body={"name": "x", "config": {"webhook_url": "(설정됨)"}},
                          qs={"customer_id": "cust-1"}, path_params={"id": "c1"})
        assert resp["statusCode"] == 200, resp["body"]
        assert table.items[("cust-1", "c1")]["config"]["webhook_url"] == SLACK_URL

    def test_a_new_credential_replaces_the_old_one(self):
        table = FakeTable([stored()])
        fresh = "https://hooks.slack.com/services/T1/B1/rotated"
        call("PUT", "/alert/channels/c1", table=table,
             body={"name": "x", "config": {"webhook_url": fresh}},
             qs={"customer_id": "cust-1"}, path_params={"id": "c1"})
        assert table.items[("cust-1", "c1")]["config"]["webhook_url"] == fresh

    def test_can_change_conditions_and_disable(self):
        table = FakeTable([stored()])
        _, b, _ = call("PUT", "/alert/channels/c1", table=table,
                       body={"name": "운영팀", "enabled": False, "match": {"severity": ["SEV-1"]}},
                       qs={"customer_id": "cust-1"}, path_params={"id": "c1"})
        assert b["enabled"] is False and b["match"] == {"severity": ["SEV-1"]}

    def test_keeps_the_id(self):
        table = FakeTable([stored()])
        _, b, _ = call("PUT", "/alert/channels/c1", table=table, body={"name": "x"},
                       qs={"customer_id": "cust-1"}, path_params={"id": "c1"})
        assert b["channel_id"] == "c1" and len(table.items) == 1

    def test_missing_channel_is_a_404(self):
        resp, _, _ = call("PUT", "/alert/channels/nope", body={"name": "x"},
                          qs={"customer_id": "cust-1"}, path_params={"id": "nope"})
        assert resp["statusCode"] == 404


class TestDelete:
    def test_removes_the_row(self):
        table = FakeTable([stored()])
        resp, _, _ = call("DELETE", "/alert/channels/c1", table=table,
                          qs={"customer_id": "cust-1"}, path_params={"id": "c1"})
        assert resp["statusCode"] == 204 and table.items == {}

    def test_missing_channel_is_a_404(self):
        resp, _, _ = call("DELETE", "/alert/channels/nope", qs={"customer_id": "cust-1"},
                          path_params={"id": "nope"})
        assert resp["statusCode"] == 404


class TestList:
    def test_customer_query_includes_global_channels(self):
        """전역 채널도 그 고객사에 적용되므로 함께 보여준다."""
        table = FakeTable([stored(), stored(channel_id="g1", customer_id="", name="NOC")])
        _, b, _ = call("GET", "/alert/channels", table=table, qs={"customer_id": "cust-1"})
        assert {c["channel_id"] for c in b["channels"]} == {"c1", "g1"}

    def test_other_customers_are_not_returned(self):
        table = FakeTable([stored(), stored(channel_id="x1", customer_id="cust-2")])
        _, b, _ = call("GET", "/alert/channels", table=table, qs={"customer_id": "cust-1"})
        assert [c["channel_id"] for c in b["channels"]] == ["c1"]

    def test_a_row_with_a_removed_type_does_not_break_the_list(self):
        table = FakeTable([stored(), stored(channel_id="old", type="pager-that-no-longer-exists")])
        resp, b, _ = call("GET", "/alert/channels", table=table)
        assert resp["statusCode"] == 200
        assert [c["channel_id"] for c in b["channels"]] == ["c1"]

    def test_storage_failure_is_surfaced(self):
        from api_handler.routes import notification_channels as nc
        table = MagicMock()
        table.query.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "x"}}, "Query")
        with patch.object(nc, "notification_channel_table", return_value=table), \
             patch.dict("os.environ", {"ADMIN_EMAILS": ADMIN}):
            from api_handler.lambda_handler import lambda_handler
            ev = _event("GET", "/alert/channels", qs={"customer_id": "cust-1"})
            ev["requestContext"]["authorizer"] = {"jwt": {"claims": {"email": ADMIN}}}
            resp = lambda_handler(ev, None)
        assert resp["statusCode"] == 503


class TestTypeCatalogue:
    def test_lists_types_with_their_fields(self):
        resp, b, _ = call("GET", "/alert/channel-types")
        assert resp["statusCode"] == 200
        by_type = {t["type"]: t for t in b["types"]}
        assert {"slack", "email", "webhook"} <= set(by_type)
        slack = by_type["slack"]
        assert slack["label"] == "Slack" and slack["rate_limit_per_sec"] == 1.0
        field = slack["fields"][0]
        assert field["name"] == "webhook_url" and field["secret"] is True

    def test_exposes_the_condition_axes_and_severities(self):
        _, b, _ = call("GET", "/alert/channel-types")
        assert b["match_fields"] == ["severity", "resource_type", "account_id"]
        assert b["severities"][0] == "SEV-1"

    def test_catalogue_carries_no_values_only_shapes(self):
        """카탈로그는 필드의 '모양'만 준다 — 저장된 값이 섞여 나가면 안 된다."""
        _, b, _ = call("GET", "/alert/channel-types")
        assert SLACK_URL not in json.dumps(b, ensure_ascii=False)

    def test_email_is_marked_unavailable_without_a_sender(self, monkeypatch):
        """dev에 `AlertEmailSender`가 비어 있었다 — 카탈로그에는 뜨는데 절대 못 보내던 유형 (review-phase2 L3)."""
        monkeypatch.delenv("ALERT_EMAIL_SENDER", raising=False)
        _, b, _ = call("GET", "/alert/channel-types")
        by_type = {t["type"]: t for t in b["types"]}
        assert by_type["email"]["available"] is False
        assert "ALERT_EMAIL_SENDER" in by_type["email"]["unavailable_reason"]
        assert by_type["slack"]["available"] is True and by_type["slack"]["unavailable_reason"] == ""

    def test_email_becomes_available_with_a_sender(self, monkeypatch):
        monkeypatch.setenv("ALERT_EMAIL_SENDER", "alerts@mz.co.kr")
        _, b, _ = call("GET", "/alert/channel-types")
        assert {t["type"]: t["available"] for t in b["types"]}["email"] is True
