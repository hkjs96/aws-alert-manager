"""
리소스 타입 레지스트리 (`common/resource_types`) — docs/specs/resource-type-registry P2

고정하는 것:
1. 파생 뷰가 손으로 유지하던 마지막 상태(P0.2 스냅숏)와 같다 — 뷰 전환이 동작을 바꾸지 않았다는 증명.
2. 레지스트리 불변식 — 타입·별칭 충돌 없음, 이벤트는 한 타입에만, 수집기 모듈은 실제로 import된다, 종류는 넷 중 하나.
3. 소비처가 정말 뷰를 읽는다 — `common`·`daily_monitor`·`remediation_handler`·`tag_cache`.
4. CFN 템플릿의 CloudTrail EventPattern == 레지스트리의 이벤트 집합 (요구사항 R8 — 3곳 동기화가 1곳 + 테스트).
"""

import importlib
import json
from pathlib import Path

import pytest
import yaml

from common import MONITORED_API_EVENTS, SUPPORTED_RESOURCE_TYPES, resource_types as R
from common import tag_cache
from common.alarm_registry import _ALARM_DEFS_BY_TYPE, _GLOBAL_SERVICE_REGION

SNAPSHOT = json.loads(
    (Path(__file__).parent / "fixtures" / "registry_snapshot_2026-09.json").read_text(encoding="utf-8"))
TEMPLATE = Path(__file__).resolve().parents[2] / "infrastructure" / "backend" / "template.yaml"


# ── 1. 파생 == 스냅숏

def test_types_match_the_snapshot_in_order():
    assert R.types() == SNAPSHOT["SUPPORTED_RESOURCE_TYPES"]
    assert SUPPORTED_RESOURCE_TYPES == R.types(), "common.SUPPORTED_RESOURCE_TYPES는 레지스트리 뷰다"


def test_monitored_api_events_match_the_snapshot():
    derived = {k: set(v) for k, v in R.monitored_api_events().items()}
    assert derived == {k: set(v) for k, v in SNAPSHOT["MONITORED_API_EVENTS"].items()}
    assert MONITORED_API_EVENTS == R.monitored_api_events()
    assert list(MONITORED_API_EVENTS) == list(R.KINDS), "종류 순서는 옛 상수 그대로"


def test_event_to_type_matches_the_old_api_map():
    assert R.event_to_type() == SNAPSHOT["_API_MAP_event_to_type"]


def test_type_to_collector_matches_the_snapshot_including_aliases():
    assert {t: f"common.collectors.{m}" for t, m in R.type_to_collector().items()} == SNAPSHOT["_RESOURCE_TYPE_TO_COLLECTOR"]


def test_collector_modules_match_the_snapshot():
    assert {f"common.collectors.{m}" for m in R.collector_modules()} == set(SNAPSHOT["_COLLECTOR_MODULES"])
    assert len(R.collector_modules()) == len(set(R.collector_modules()))


def test_tagged_services_match_the_snapshot():
    assert set(R.tagged_services()) == set(SNAPSHOT["TAGGED_SERVICES"])
    assert tag_cache.TAGGED_SERVICES == R.tagged_services()


def test_global_service_regions_match_the_registry_constant():
    assert R.global_service_regions() == _GLOBAL_SERVICE_REGION


def _plain(d: dict) -> dict:
    return {k: (f"<callable {getattr(v, '__name__', 'lambda')}>" if callable(v) else v) for k, v in d.items()}


@pytest.mark.parametrize("rt", SNAPSHOT["SUPPORTED_RESOURCE_TYPES"])
def test_alarm_definitions_are_byte_for_byte_the_snapshot(rt):
    """P2.4 — 정의가 타입별 모듈로 옮겨진 뒤에도 기본 변형의 정의는 이관 전과 같다(람다는 이름으로 비교)."""
    from common.alarm_registry import _get_alarm_defs_raw
    assert [_plain(d) for d in _get_alarm_defs_raw(rt, {})] == SNAPSHOT["alarm_defs_default"][rt]
    assert [_plain(d) for d in R.get(rt).alarms({})] == SNAPSHOT["alarm_defs_default"][rt]


def test_metric_display_matches_the_snapshot():
    """P2.4b — 표시명이 타입 스펙 + legacy로 옮겨진 뒤에도 옛 `_METRIC_DISPLAY`와 같다."""
    from common.alarm_registry import _METRIC_DISPLAY
    assert {k: list(v) for k, v in R.metric_display().items()} == SNAPSHOT["_METRIC_DISPLAY"]
    assert _METRIC_DISPLAY == R.metric_display()


def test_hardcoded_defaults_match_the_snapshot():
    from common import HARDCODED_DEFAULTS
    assert R.hardcoded_defaults() == SNAPSHOT["HARDCODED_DEFAULTS"]
    assert HARDCODED_DEFAULTS == R.hardcoded_defaults()


@pytest.mark.parametrize("spec", R.all_specs(), ids=lambda s: s.type)
def test_every_alarm_metric_key_has_a_display_and_a_default(spec):
    for k in spec.metric_keys():
        assert k in spec.display, f"{spec.type}: display for {k}"
        assert k in spec.defaults, f"{spec.type}: default threshold for {k}"


def test_shared_threshold_entries_all_have_reasons_and_cover_the_legacy_tag_keys():
    from common.tag_resolver import _LEGACY_TAG_MAP
    reasons = R.shared_threshold_reasons()
    assert reasons and all(v.strip() for v in reasons.values())
    assert set(_LEGACY_TAG_MAP.values()) <= set(reasons), "옛 친숙 태그 키는 전부 이유가 붙은 공유 항목이어야 한다"


def test_conflicting_values_across_specs_fail_loudly():
    with pytest.raises(ValueError, match="conflict on 'CPUUtilization'"):
        R.base._merge_unique([("A", {"CPUUtilization": ("x", ">", "%")}), ("B", {"CPUUtilization": ("y", ">", "%")})], "display")


def test_shared_entries_require_a_reason():
    with pytest.raises(ValueError, match="reason"):
        R.add_shared_thresholds(defaults={"Whatever": 1.0}, reason="")


# ── 2. 불변식

def test_every_alarm_type_has_a_spec_and_vice_versa():
    assert set(R.types()) == set(_ALARM_DEFS_BY_TYPE)


def test_aliases_never_collide_with_types():
    aliases = [a for s in R.all_specs() for a in s.aliases]
    assert len(aliases) == len(set(aliases))
    assert not set(aliases) & set(R.types())
    assert R.get("ELB").type == "ALB" and R.get("NATGateway").type == "NAT"


def test_unknown_type_is_a_clear_error():
    with pytest.raises(KeyError, match="unknown resource type"):
        R.get("Nope")


def test_registering_a_duplicate_fails_loudly():
    with pytest.raises(ValueError, match="already registered"):
        R.register(R.ResourceTypeSpec(type="EC2", label="dup", collector="ec2"))
    with pytest.raises(ValueError, match="already registered"):
        R.register(R.ResourceTypeSpec(type="Brand-New", label="x", collector="ec2", aliases=("ELB",)))


def test_each_event_belongs_to_exactly_one_target():
    seen = {}
    for spec in R.all_specs():
        for e in spec.events():
            assert e.kind in R.KINDS
            assert seen.setdefault(e.event, e.target) == e.target, f"{e.event} claimed twice"


@pytest.mark.parametrize("spec", R.all_specs(), ids=lambda s: s.type)
def test_collector_module_exists_and_implements_the_protocol(spec):
    mod = importlib.import_module(f"common.collectors.{spec.collector}")
    for fn in ("collect_monitored_resources", "get_metrics", "resolve_alive_ids"):
        assert callable(getattr(mod, fn, None)), f"{spec.collector}.{fn}"


@pytest.mark.parametrize("spec", R.all_specs(), ids=lambda s: s.type)
def test_spec_has_rgt_filters_and_alarms(spec):
    assert spec.rgt_filters, "부록 A — 29개 전부 유효한 필터가 있다"
    assert spec.alarms({}) or spec.type == "TG" and spec.alarms({}) is not None
    assert spec.label


@pytest.mark.parametrize("spec", [s for s in R.all_specs() if not s.rgt_prime], ids=lambda s: s.type)
def test_not_priming_the_tag_cache_needs_a_reason(spec):
    """예외에는 이유가 있어야 한다(R9) — 맵은 이유를 말해 주지 않았다."""
    assert "프라임 안 함" in spec.notes, spec.type


@pytest.mark.parametrize("spec", [s for s in R.all_specs() if not s.lifecycle], ids=lambda s: s.type)
def test_a_type_without_lifecycle_events_says_why(spec):
    assert "생명주기" in spec.notes or "이벤트" in spec.notes, spec.type


def test_shared_events_are_multi():
    assert {e.event for e in R.SHARED_LIFECYCLE} == {"TagResource", "UntagResource"}
    assert all(e.target == R.MULTI for e in R.SHARED_LIFECYCLE)


# ── 2b. 시연 — 타입 추가는 스펙 하나다 (요구사항 R3, AC 2)

@pytest.fixture
def scratch_registry(monkeypatch):
    """레지스트리를 복사해 두고 테스트 뒤 되돌린다 — 다른 테스트가 보는 전역 상태를 건드리지 않는다."""
    base = R.base
    for name in ("_SPECS", "_ALIASES", "_SHARED_DISPLAY", "_SHARED_DEFAULTS", "_SHARED_REASONS"):
        monkeypatch.setattr(base, name, dict(getattr(base, name)))
    yield base


def test_adding_a_type_is_one_spec_and_everything_follows(scratch_registry):
    """새 타입을 스펙 하나로 등록하면 타입 목록·수집기 맵·이벤트·표시명·기본치·RGT 서비스가 전부 따라온다."""
    defs = [{"metric": "IncomingRecords", "namespace": "AWS/Kinesis", "metric_name": "IncomingRecords",
             "dimension_key": "StreamName", "stat": "Sum", "comparison": "GreaterThanThreshold",
             "period": 300, "evaluation_periods": 1}]
    R.register(R.ResourceTypeSpec(
        type="Kinesis", label="Kinesis 스트림", collector="sqs",          # 시연이라 있는 수집기를 빌린다
        rgt_filters=("kinesis:stream",), rgt_prime=True,
        lifecycle=(R.Lifecycle("CreateStream", R.CREATE), R.Lifecycle("DeleteStream", R.DELETE)),
        alarm_defs=defs,
        display={"IncomingRecords": ("IncomingRecords", ">", "")},
        defaults={"IncomingRecords": 100000.0},
    ))
    assert R.types()[-1] == "Kinesis"
    assert R.type_to_collector()["Kinesis"] == "sqs"
    assert "CreateStream" in R.monitored_api_events()["CREATE"] and R.event_to_type()["DeleteStream"] == "Kinesis"
    assert "kinesis" in R.tagged_services()
    assert R.metric_display()["IncomingRecords"] == ("IncomingRecords", ">", "")
    assert R.hardcoded_defaults()["IncomingRecords"] == 100000.0
    assert R.get("Kinesis").alarms({}) == defs


def test_a_definition_without_display_or_default_fails_at_view_time(scratch_registry):
    """정의만 추가하고 표시명·기본치를 빠뜨리는 실수 — 조용히 '알람 이름 unknown'이 되던 것이 이제 크게 실패한다."""
    R.register(R.ResourceTypeSpec(
        type="Broken", label="x", collector="sqs", rgt_filters=("x:y",),
        alarm_defs=[{"metric": "Orphan", "namespace": "AWS/X", "metric_name": "Orphan", "dimension_key": "Id",
                     "stat": "Sum", "comparison": "GreaterThanThreshold", "period": 60, "evaluation_periods": 1}],
        notes="시연", lifecycle=(),
    ))
    with pytest.raises(ValueError, match="display missing.*Orphan"):
        R.metric_display()
    with pytest.raises(ValueError, match="default threshold missing.*Orphan"):
        R.hardcoded_defaults()


def test_a_type_cannot_redefine_a_shared_key(scratch_registry):
    R.register(R.ResourceTypeSpec(
        type="Rogue", label="x", collector="sqs", rgt_filters=("x:y",), lifecycle=(), notes="시연",
        alarm_defs=[], display={"CPUUtilization": ("CPUUtilization", ">", "cores")}, defaults={},
    ))
    with pytest.raises(ValueError, match="display conflict on 'CPUUtilization'"):
        R.metric_display()


# ── 3. 소비처가 뷰를 읽는다

def test_daily_monitor_maps_come_from_the_registry():
    from daily_monitor import lambda_handler as dm
    assert {t: m.__name__.rsplit(".", 1)[-1] for t, m in dm._RESOURCE_TYPE_TO_COLLECTOR.items()} == R.type_to_collector()
    assert [m.__name__.rsplit(".", 1)[-1] for m in dm._COLLECTOR_MODULES] == R.collector_modules()
    # 명시 import와 같은 모듈 객체여야 테스트의 patch.object(dm.ec2_collector, …)가 계속 먹는다
    assert dm._RESOURCE_TYPE_TO_COLLECTOR["EC2"] is dm.ec2_collector


def test_remediation_api_map_takes_its_types_from_the_registry():
    from remediation_handler import lambda_handler as rh
    assert {ev: t for ev, (t, _) in rh._API_MAP.items()} == R.event_to_type()
    assert all(callable(fn) for _, fn in rh._API_MAP.values())


def test_remediation_fails_loudly_when_an_extractor_is_missing(monkeypatch):
    from remediation_handler import lambda_handler as rh
    trimmed = dict(rh._EXTRACTORS)
    trimmed.pop("DeleteTopic")
    monkeypatch.setattr(rh, "_EXTRACTORS", trimmed)
    with pytest.raises(RuntimeError, match="DeleteTopic"):
        rh._build_api_map()


# ── 4. CFN 템플릿과의 정합 (R8)

def _template_event_names() -> list[set[str]]:
    class Loader(yaml.SafeLoader):
        pass

    def any_tag(loader, suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        return loader.construct_mapping(node)

    Loader.add_multi_constructor("!", any_tag)
    doc = yaml.load(TEMPLATE.read_text(encoding="utf-8"), Loader=Loader)
    found = []
    for res in doc["Resources"].values():
        pattern = (res.get("Properties") or {}).get("EventPattern") or {}
        names = ((pattern.get("detail") or {}).get("eventName")) if isinstance(pattern, dict) else None
        if names:
            found.append(set(names))
    return found


def test_template_cloudtrail_event_pattern_equals_the_registry_events():
    """3곳 동기화(__init__·템플릿·_API_MAP) → 1곳 + 이 테스트. 어긋나면 '이벤트가 안 온다'로만 드러나던 것."""
    expected = {e for events in R.monitored_api_events().values() for e in events}
    patterns = _template_event_names()
    assert patterns, "템플릿에 CloudTrail eventName EventPattern이 있어야 한다"
    assert any(p == expected for p in patterns), (
        f"템플릿 eventName 집합이 레지스트리와 다르다: only template={sorted(patterns[0] - expected)} "
        f"only registry={sorted(expected - patterns[0])}")
