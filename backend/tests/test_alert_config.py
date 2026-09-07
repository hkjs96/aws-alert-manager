"""
알림 정제 설정 (common/alert_config.py) 테스트 — tasks 1.4.4 / 1.4.6

정제 설정이 잘못되면 **알림이 전부 사라질 수 있다.** 그래서 고정하는 것:
- 우선순위 DB > 환경변수 > 코드 기본값, 부분 저장(있는 필드만 덮어씀)
- 범위 밖 값은 **로더가 클램프**(런타임은 계속 동작)하고 **API가 거절**(사람에게 알림)
- 끝나지 않는 정비창은 만들 수 없다 (최대 30일)
- 설정 읽기 실패는 환경변수로 폴백하되 정비창은 비운다 — 억제가 덜 되지 더 되지 않는다
"""

from datetime import datetime, timedelta, timezone

import pytest
from botocore.exceptions import ClientError

from fakes_ddb import FakeConfigTable
from common import alert_config as cfg
from common.alert_config import (
    CONFIG_POLICY,
    CONFIG_SILENCE,
    MAX_SILENCE_DAYS,
    POLICY_DEFAULT,
    ConfigError,
    load,
    load_cached,
    new_silence_id,
    policy_from_item,
    policy_to_dict,
    policy_to_item,
    silence_to_dict,
    silence_to_item,
    silences_from_items,
    validate_policy,
    validate_silence,
)
from common.alert_suppression import Silence, SuppressionPolicy

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
BASE = SuppressionPolicy(repeat_interval_sec=900, auto_pause_sec={"SEV-3": 120})


@pytest.fixture(autouse=True)
def _reset():
    cfg.reset_cache()
    yield
    cfg.reset_cache()


def silence_item(**over):
    item = {"config_type": CONFIG_SILENCE, "config_id": "s1",
            "starts_at": "2026-09-08T11:00:00Z", "ends_at": "2026-09-08T13:00:00Z",
            "customer_id": "cust-1", "resource_type": "", "reason": "패치 작업"}
    item.update(over)
    return item


class TestPolicyFromItem:
    def test_no_item_keeps_base(self):
        assert policy_from_item(BASE, None) is BASE

    def test_db_overrides_only_present_fields(self):
        p = policy_from_item(BASE, {"repeat_interval_sec": 1800})
        assert p.repeat_interval_sec == 1800
        assert p.auto_pause_sec == {"SEV-3": 120}          # 건드리지 않은 필드는 그대로
        assert p.flapping_per_day == BASE.flapping_per_day

    def test_auto_pause_replaces_map(self):
        p = policy_from_item(BASE, {"auto_pause_sec": {"SEV-1": 0, "SEV-4": 300}})
        assert p.auto_pause_sec == {"SEV-1": 0, "SEV-4": 300}

    def test_exempt_severities_normalized(self):
        p = policy_from_item(BASE, {"exempt_severities": ["SEV-2", " ", "SEV-1", "SEV-1"]})
        assert p.exempt_severities == ("SEV-1", "SEV-2")

    def test_out_of_range_is_clamped_not_rejected(self):
        """런타임은 이미 저장된 이상한 값 때문에 멈추면 안 된다."""
        p = policy_from_item(BASE, {"repeat_interval_sec": 10 ** 9, "group_wait_sec": -5,
                                    "flapping_per_day": 0})
        assert p.repeat_interval_sec == 86_400
        assert p.group_wait_sec == 0
        assert p.flapping_per_day == 1

    def test_auto_pause_values_are_clamped(self):
        p = policy_from_item(BASE, {"auto_pause_sec": {"SEV-3": 99_999}})
        assert p.auto_pause_sec == {"SEV-3": 3_600}

    def test_garbage_values_keep_base(self):
        p = policy_from_item(BASE, {"repeat_interval_sec": "nonsense",
                                    "flapping_window_days": None,
                                    "auto_pause_sec": {"SEV-3": "soon"},
                                    "exempt_severities": "SEV-1"})
        assert p.repeat_interval_sec == 900
        assert p.flapping_window_days == BASE.flapping_window_days
        assert p.auto_pause_sec == {}                       # 맵은 왔으나 값이 숫자가 아님 → 비움
        assert p.exempt_severities == BASE.exempt_severities  # 문자열은 배열이 아니므로 무시

    def test_round_trip_through_item(self):
        p = SuppressionPolicy(auto_pause_sec={"SEV-3": 300}, repeat_interval_sec=600,
                              exempt_severities=("SEV-1",), flapping_window_days=2.0,
                              flapping_per_day=5, flapping_quarantine_sec=1800, group_wait_sec=45)
        back = policy_from_item(SuppressionPolicy(), policy_to_item(p))
        assert policy_to_dict(back) == policy_to_dict(p)

    def test_item_has_no_float(self):
        """DynamoDB는 float를 거부한다 — flapping_window_days는 문자열로 저장한다."""
        item = policy_to_item(SuppressionPolicy(flapping_window_days=1.5))
        assert not any(isinstance(v, float) for v in item.values())
        assert policy_from_item(SuppressionPolicy(), item).flapping_window_days == 1.5


class TestSilences:
    def test_parsed(self):
        s = silences_from_items([silence_item()])
        assert len(s) == 1 and s[0].customer_id == "cust-1"
        assert s[0].starts_at == datetime(2026, 9, 8, 11, tzinfo=timezone.utc)

    def test_invalid_window_is_dropped(self):
        assert silences_from_items([silence_item(ends_at="2026-09-08T10:00:00Z")]) == ()
        assert silences_from_items([silence_item(ends_at="")]) == ()
        assert silences_from_items([silence_item(starts_at="nonsense")]) == ()

    def test_empty_input(self):
        assert silences_from_items([]) == () and silences_from_items(None) == ()

    def test_round_trip(self):
        s = Silence(starts_at=NOW, ends_at=NOW + timedelta(hours=2),
                    customer_id="c1", resource_type="EC2", reason="점검")
        item = silence_to_item(s, config_id="s9", created_by="a@b.com", created_at=NOW)
        assert silences_from_items([item])[0] == s
        assert item["ttl"] == int((s.ends_at + timedelta(days=7)).timestamp())

    def test_dict_marks_active_and_expired(self):
        item = silence_item()
        assert silence_to_dict(item, now=NOW)["active"] is True
        later = datetime(2026, 9, 8, 14, tzinfo=timezone.utc)
        d = silence_to_dict(item, now=later)
        assert d["active"] is False and d["expired"] is True

    def test_id_is_time_ordered(self):
        a = new_silence_id(NOW)
        b = new_silence_id(NOW + timedelta(seconds=1))
        assert a < b and a != b


class TestValidatePolicy:
    def test_keeps_unspecified_fields(self):
        p = validate_policy({"repeat_interval_sec": 600}, BASE)
        assert p.repeat_interval_sec == 600 and p.auto_pause_sec == {"SEV-3": 120}

    def test_rejects_out_of_range(self):
        for body in ({"repeat_interval_sec": 10 ** 7}, {"group_wait_sec": 1000},
                     {"flapping_per_day": 0}, {"flapping_window_days": 90},
                     {"auto_pause_sec": {"SEV-3": 99_999}}):
            with pytest.raises(ConfigError):
                validate_policy(body, BASE)

    def test_rejects_bad_types(self):
        for body in ({"repeat_interval_sec": "곧"}, {"auto_pause_sec": [1, 2]},
                     {"auto_pause_sec": {"SEV-3": "곧"}}, {"exempt_severities": "SEV-1"}):
            with pytest.raises(ConfigError):
                validate_policy(body, BASE)
        with pytest.raises(ConfigError):
            validate_policy("not a dict", BASE)      # type: ignore[arg-type]

    def test_accepts_boundaries(self):
        p = validate_policy({"repeat_interval_sec": 0, "group_wait_sec": 300,
                             "auto_pause_sec": {"SEV-3": 3600}}, BASE)
        assert p.repeat_interval_sec == 0 and p.group_wait_sec == 300


class TestValidateSilence:
    def test_defaults_start_to_now(self):
        s = validate_silence({"ends_at": "2026-09-08T14:00:00Z"}, now=NOW)
        assert s.starts_at == NOW and s.ends_at == datetime(2026, 9, 8, 14, tzinfo=timezone.utc)

    def test_requires_end(self):
        with pytest.raises(ConfigError):
            validate_silence({}, now=NOW)
        with pytest.raises(ConfigError):
            validate_silence({"ends_at": "nonsense"}, now=NOW)

    def test_rejects_inverted_and_past(self):
        with pytest.raises(ConfigError):
            validate_silence({"starts_at": "2026-09-08T14:00:00Z",
                              "ends_at": "2026-09-08T13:00:00Z"}, now=NOW)
        with pytest.raises(ConfigError):
            validate_silence({"ends_at": "2026-09-08T11:00:00Z"}, now=NOW)

    def test_rejects_never_ending_window(self):
        """끝나지 않는 정비창은 알림을 영원히 지운다."""
        with pytest.raises(ConfigError):
            validate_silence({"ends_at": (NOW + timedelta(days=MAX_SILENCE_DAYS + 1)).isoformat()},
                             now=NOW)

    def test_trims_and_caps_reason(self):
        s = validate_silence({"ends_at": "2026-09-08T14:00:00Z", "reason": " " + "x" * 500,
                              "customer_id": " c1 "}, now=NOW)
        assert len(s.reason) == 200 and s.customer_id == "c1"


class TestLoad:
    def _table(self, *, policy=None, silences=()):
        t = FakeConfigTable()
        if policy is not None:
            t.put_item(Item={"config_type": CONFIG_POLICY, "config_id": POLICY_DEFAULT, **policy})
        for i, s in enumerate(silences):
            t.put_item(Item={**s, "config_id": s.get("config_id", f"s{i}")})
        return t

    def test_merges_policy_and_silences(self):
        t = self._table(policy={"repeat_interval_sec": 1800}, silences=[silence_item()])
        policy, ok = load(t, BASE)
        assert ok is True
        assert policy.repeat_interval_sec == 1800
        assert len(policy.silences) == 1 and policy.silences[0].customer_id == "cust-1"

    def test_empty_table_keeps_base(self):
        policy, ok = load(self._table(), BASE)
        assert ok is True and policy.repeat_interval_sec == 900 and policy.silences == ()

    def test_paginates_silences(self):
        t = self._table(silences=[silence_item(config_id=f"s{i}") for i in range(7)])
        t.page_size = 3
        policy, ok = load(t, BASE)
        assert ok is True and len(policy.silences) == 7

    def test_client_error_falls_back_to_base_without_silences(self):
        class Broken:
            def get_item(self, **_):
                raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "GetItem")

        policy, ok = load(Broken(), BASE)
        assert ok is False and policy is BASE and policy.silences == ()


class TestLoadCached:
    def test_none_table_is_env_mode_not_failure(self):
        policy, ok = load_cached(None, BASE)
        assert policy is BASE and ok is True

    def test_ttl(self, monkeypatch):
        t = FakeConfigTable()
        t.put_item(Item={"config_type": CONFIG_POLICY, "config_id": POLICY_DEFAULT,
                         "repeat_interval_sec": 1800})
        clock = [1000.0]
        monkeypatch.setattr(cfg, "_monotonic", lambda: clock[0])

        assert load_cached(t, BASE)[0].repeat_interval_sec == 1800
        t.put_item(Item={"config_type": CONFIG_POLICY, "config_id": POLICY_DEFAULT,
                         "repeat_interval_sec": 60})
        clock[0] += cfg.CONFIG_CACHE_TTL_SEC - 1
        assert load_cached(t, BASE)[0].repeat_interval_sec == 1800     # 캐시 유효
        assert t.gets == 1
        clock[0] += 2
        assert load_cached(t, BASE)[0].repeat_interval_sec == 60       # 만료 후 재조회
        assert t.gets == 2

    def test_failure_is_not_cached(self, monkeypatch):
        class Broken:
            def get_item(self, **_):
                raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "GetItem")

        monkeypatch.setattr(cfg, "_monotonic", lambda: 1000.0)
        assert load_cached(Broken(), BASE)[1] is False
        t = FakeConfigTable()
        t.put_item(Item={"config_type": CONFIG_POLICY, "config_id": POLICY_DEFAULT,
                         "repeat_interval_sec": 30})
        assert load_cached(t, BASE)[0].repeat_interval_sec == 30       # 곧바로 다시 시도한다
