"""
레지스트리 파생 뷰의 완전성 (docs/specs/resource-type-registry P1)

`_HARDCODED_METRIC_KEYS`·`_NAMESPACE_MAP`·`_DIMENSION_KEY_MAP`은 2026-09까지 손으로 유지됐고 이 파일이
"정의와 맞나"를 지켰다. 이제 셋은 알람 정의에서 **파생**된다. 그래서 지키는 것이 바뀐다:

1. 파생값이 손으로 유지하던 마지막 상태(P0.2 스냅숏 `fixtures/registry_snapshot_2026-09.json`)와 같다 —
   파생이 동작을 바꾸지 않았다는 증명. 의도한 차이는 `ACCEPTED_DIFFS`에 **이유와 함께** 적는다.
2. 조건부 정의 함수가 읽는 태그 키가 전부 `_ALARM_DEF_VARIANTS`에 열거돼 있다 — 새 분기가 파생에서
   조용히 빠지지 않게. 함수 소스를 직접 훑는다.
3. 파생의 전제: 기본 변형의 정의는 디멘션 키를 공유하고, 옵트인 정의는 기본 집합에 들지 않는다.
"""

import inspect
import json
import re
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from common import SUPPORTED_RESOURCE_TYPES
import common.alarm_registry as R
from common.alarm_registry import (
    _ALARM_DEF_VARIANTS,
    _ALARM_DEFS_BY_TYPE,
    _DIMENSION_KEY_MAP,
    _HARDCODED_METRIC_KEYS,
    _NAMESPACE_MAP,
    _get_alarm_defs,
    _get_hardcoded_metric_keys,
)
from common.resource_types.ec2 import APP_STATUS_METRIC_KEY

SNAPSHOT = json.loads(
    (Path(__file__).parent / "fixtures" / "registry_snapshot_2026-09.json").read_text(encoding="utf-8"))

#: 스냅숏과 다르기로 **결정한** 것. 이유 없는 차이는 실패다.
#: 형식: (표 이름, 타입) → {"remove": {…}, "add": {…}, "why": "…"}
ACCEPTED_DIFFS: dict[tuple[str, str], dict] = {
    ("_HARDCODED_METRIC_KEYS", "AuroraRDS"): {
        "remove": {"ServerlessDatabaseCapacity"},
        "why": "정의(_AURORA_SERVERLESS_CAPACITY)는 있지만 어떤 변형도 emit하지 않는다 — ACUUtilization이 "
               "비율로 대신한다(_get_aurora_alarm_defs 주석). 옛 표에만 있었고 이 정적 표의 런타임 소비처는 없다.",
    },
}

TYPES = sorted(SUPPORTED_RESOURCE_TYPES)


def _expected(map_name: str, rt: str):
    value = SNAPSHOT[map_name][rt]
    diff = ACCEPTED_DIFFS.get((map_name, rt))
    if diff is None:
        return value
    assert diff.get("why"), f"{map_name}[{rt}]: 의도한 차이에는 이유가 있어야 한다"
    return sorted((set(value) - diff.get("remove", set())) | diff.get("add", set()))


# ── 1. 파생 == 손 맵 마지막 상태

def test_alarm_types_are_exactly_the_supported_types():
    assert set(_ALARM_DEFS_BY_TYPE) == set(SUPPORTED_RESOURCE_TYPES)


@pytest.mark.parametrize("rt", TYPES)
def test_derived_metric_keys_match_the_hand_maintained_snapshot(rt):
    assert sorted(_HARDCODED_METRIC_KEYS[rt]) == _expected("_HARDCODED_METRIC_KEYS", rt)


@pytest.mark.parametrize("rt", TYPES)
def test_derived_namespaces_match_the_hand_maintained_snapshot(rt):
    assert _NAMESPACE_MAP[rt] == SNAPSHOT["_NAMESPACE_MAP"][rt], "순서까지 같아야 한다 — 탐색 순서다"


@pytest.mark.parametrize("rt", TYPES)
def test_derived_dimension_keys_match_the_hand_maintained_snapshot(rt):
    assert _DIMENSION_KEY_MAP[rt] == SNAPSHOT["_DIMENSION_KEY_MAP"][rt]


def test_every_accepted_diff_still_applies():
    """더 이상 필요 없는 예외는 지워야 한다 — 죽은 예외가 쌓이면 표가 다시 '이유를 말하지 않는 맵'이 된다."""
    for (map_name, rt), diff in ACCEPTED_DIFFS.items():
        snap = set(SNAPSHOT[map_name][rt])
        derived = set(getattr(R, map_name)[rt])
        assert diff.get("remove", set()) <= snap - derived, f"{map_name}[{rt}]: remove 예외가 더는 차이가 아니다"
        assert diff.get("add", set()) <= derived - snap, f"{map_name}[{rt}]: add 예외가 더는 차이가 아니다"


# ── 2. 조건 분기가 읽는 태그는 전부 변형에 열거돼 있다

def _tag_keys_read_by(fn) -> set[str]:
    """함수 소스에서 `resource_tags.get(<키>)`의 키를 뽑는다. 문자열·f-문자열·모듈 이름을 허용한다."""
    keys: set[str] = set()
    for token in re.findall(r"resource_tags\.get\(\s*([^,)]+)", inspect.getsource(fn)):
        token = token.strip()
        if re.fullmatch(r'f?"[^"]*"|f?\'[^\']*\'|[A-Za-z_]\w*', token):
            keys.add(str(eval(token, vars(R))))       # noqa: S307 — 우리 소스의 리터럴/모듈 이름만
        else:
            raise AssertionError(f"{fn.__name__}: 해석할 수 없는 태그 키 식 {token!r} — 리터럴이나 모듈 상수로 쓸 것")
    return keys


def test_every_conditional_type_declares_its_variants():
    conditional = {t for t, e in _ALARM_DEFS_BY_TYPE.items() if callable(e)}
    assert conditional == set(_ALARM_DEF_VARIANTS), \
        "태그 조건부 정의를 가진 타입은 정확히 _ALARM_DEF_VARIANTS의 키여야 한다"


@pytest.mark.parametrize("rt", sorted(_ALARM_DEF_VARIANTS))
def test_every_tag_a_conditional_def_reads_is_a_declared_variant_key(rt):
    read = _tag_keys_read_by(_ALARM_DEFS_BY_TYPE[rt])
    declared = {k for variant in _ALARM_DEF_VARIANTS[rt] for k in variant}
    assert read <= declared, f"{rt}: 분기가 읽는 태그 {sorted(read - declared)}가 변형에 없다 — 파생에서 빠진다"


def test_variants_actually_change_the_definitions():
    """변형이 아무것도 바꾸지 않으면 열거가 잘못된 것이다(태그 값이 분기 조건과 안 맞는 경우)."""
    for rt, variants in _ALARM_DEF_VARIANTS.items():
        outcomes = {tuple(d["metric"] for d in _get_alarm_defs(rt, v)) for v in variants}
        assert len(outcomes) > 1, f"{rt}: 변형 {len(variants)}개가 전부 같은 정의를 낸다"


# ── 3. 파생의 전제

def test_opt_in_defs_are_excluded_from_the_default_set_but_appear_with_their_tag():
    assert APP_STATUS_METRIC_KEY not in _HARDCODED_METRIC_KEYS["EC2"]
    with_tag = _get_hardcoded_metric_keys("EC2", {f"Threshold_{APP_STATUS_METRIC_KEY}": "1"})
    assert APP_STATUS_METRIC_KEY in with_tag
    assert APP_STATUS_METRIC_KEY not in _get_hardcoded_metric_keys("EC2", {})


@pytest.mark.parametrize("rt", TYPES)
def test_default_defs_share_one_dimension_key(rt):
    keys = {d["dimension_key"] for d in _get_alarm_defs(rt)}
    assert keys == {_DIMENSION_KEY_MAP[rt]}


@pytest.mark.parametrize("rt", TYPES)
def test_every_variant_namespace_is_in_the_namespace_map(rt):
    for variant in _ALARM_DEF_VARIANTS.get(rt, ({},)):
        for d in _get_alarm_defs(rt, variant):
            assert d["namespace"] in _NAMESPACE_MAP[rt], f"{rt}/{variant}: {d['namespace']}"


@given(rt=st.sampled_from(TYPES))
@settings(max_examples=60)
def test_alarm_defs_have_required_fields_in_every_variant(rt):
    required = {"metric", "namespace", "metric_name", "dimension_key", "stat", "comparison", "period",
                "evaluation_periods"}
    for variant in _ALARM_DEF_VARIANTS.get(rt, ({},)):
        for d in _get_alarm_defs(rt, variant):
            missing = required - d.keys()
            assert not missing, f"{rt}/{variant}: {missing}"


# ── 옛 동작 회귀 (그대로 유지)

def test_tg_nlb_excludes_alb_only_metrics():
    actual = {d["metric"] for d in _get_alarm_defs("TG", {"_lb_type": "network"})}
    assert {"RequestCountPerTarget", "TargetResponseTime"}.isdisjoint(actual)
    assert {"HealthyHostCount", "UnHealthyHostCount"} <= actual


def test_tg_alb_target_type_returns_empty():
    assert _get_alarm_defs("TG", {"_target_type": "alb"}) == []


def test_aurora_provisioned_writer_with_readers_gets_replica_lag():
    tags = {"_is_serverless_v2": "false", "_is_cluster_writer": "true", "_has_readers": "true"}
    actual = {d["metric"] for d in _get_alarm_defs("AuroraRDS", tags)}
    assert {"CPUUtilization", "FreeableMemory", "DatabaseConnections", "ReplicaLag"} <= actual


def test_unknown_resource_type_returns_empty():
    assert _get_alarm_defs("Unknown") == []
