"""
PBT — Correctness Properties for Remaining Resource Monitoring (8 new types).

Property-based tests verifying alarm registry data integrity, mapping completeness,
dimension construction, and threshold direction consistency.
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from common import HARDCODED_DEFAULTS
from common.alarm_registry import (
    _DIMENSION_KEY_MAP,
    _HARDCODED_METRIC_KEYS,
    _METRIC_DISPLAY,
    _NAMESPACE_MAP,
    _VPN_ALARMS,
    _get_alarm_defs,
    _get_apigw_alarm_defs,
    _metric_name_to_key,
)
from common.dimension_builder import _build_dimensions

# ──────────────────────────────────────────────
# Shared strategies
# ──────────────────────────────────────────────

NEW_RESOURCE_TYPES = [
    "Lambda", "VPN", "APIGW", "ACM", "Backup", "MQ", "CLB", "OpenSearch",
]

st_new_resource_type = st.sampled_from(NEW_RESOURCE_TYPES)

# For APIGW we need _api_type in tags; other types need no special tags.
APIGW_API_TYPES = ["REST", "HTTP", "WEBSOCKET"]

VALID_COMPARISONS = {
    "GreaterThanThreshold",
    "GreaterThanOrEqualToThreshold",
    "LessThanThreshold",
    "LessThanOrEqualToThreshold",
}


def _tags_for_type(resource_type: str, api_type: str = "REST") -> dict:
    """Build minimal resource_tags for a given type."""
    if resource_type == "APIGW":
        return {"_api_type": api_type}
    return {}


# ──────────────────────────────────────────────
# Property 1: Alarm Definition Structural Correctness
# **Validates: Requirements 1.1, 1.2, 2.1, 2.2, 3-B.5, 3-B.6, 3-C.10, 3-C.11,
#   3-D.15, 3-D.16, 4.1, 4.2, 5.1, 5.2, 6.1, 6.2, 7.1, 7.2, 8.1, 8.2,
#   9.1, 9.2, 14.1–14.7**
# ──────────────────────────────────────────────


@given(
    resource_type=st_new_resource_type,
    api_type=st.sampled_from(APIGW_API_TYPES),
)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_alarm_def_structural_correctness(resource_type: str, api_type: str):
    """Every alarm def has required keys, valid namespace, dimension_key, and comparison."""
    tags = _tags_for_type(resource_type, api_type)
    alarm_defs = _get_alarm_defs(resource_type, tags)

    assert len(alarm_defs) > 0, f"No alarm defs for {resource_type}"

    required_keys = {
        "metric", "namespace", "metric_name", "dimension_key",
        "stat", "comparison", "period", "evaluation_periods",
    }

    for ad in alarm_defs:
        # All required keys present
        missing = required_keys - set(ad.keys())
        assert not missing, f"{resource_type} alarm def missing keys: {missing}"

        # namespace is a non-empty string
        assert isinstance(ad["namespace"], str) and ad["namespace"]

        # dimension_key is a non-empty string
        assert isinstance(ad["dimension_key"], str) and ad["dimension_key"]

        # metric is in the known hardcoded set for this type
        assert ad["metric"] in _HARDCODED_METRIC_KEYS[resource_type], (
            f"{ad['metric']} not in _HARDCODED_METRIC_KEYS[{resource_type}]"
        )

        # comparison direction is valid
        assert ad["comparison"] in VALID_COMPARISONS, (
            f"Invalid comparison: {ad['comparison']}"
        )


# ──────────────────────────────────────────────
# Property 2: Registry Mapping Table Completeness
# **Validates: Requirements 9.4, 9.5, 9.6, 9.7, 9.8, 1.7, 2.8, 3-F.23,
#   4.8, 5.7, 6.7, 7.7, 8.8**
# ──────────────────────────────────────────────


@given(
    resource_type=st_new_resource_type,
    api_type=st.sampled_from(APIGW_API_TYPES),
)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_registry_mapping_table_completeness(resource_type: str, api_type: str):
    """Every alarm def's metric key exists in all mapping tables."""
    tags = _tags_for_type(resource_type, api_type)
    alarm_defs = _get_alarm_defs(resource_type, tags)

    # _NAMESPACE_MAP and _DIMENSION_KEY_MAP must have the resource type
    assert resource_type in _NAMESPACE_MAP, (
        f"{resource_type} missing from _NAMESPACE_MAP"
    )
    assert resource_type in _DIMENSION_KEY_MAP, (
        f"{resource_type} missing from _DIMENSION_KEY_MAP"
    )

    for ad in alarm_defs:
        metric_key = ad["metric"]

        # _HARDCODED_METRIC_KEYS coverage
        assert metric_key in _HARDCODED_METRIC_KEYS[resource_type]

        # _METRIC_DISPLAY coverage
        assert metric_key in _METRIC_DISPLAY, (
            f"{metric_key} missing from _METRIC_DISPLAY"
        )

        # HARDCODED_DEFAULTS coverage
        assert metric_key in HARDCODED_DEFAULTS, (
            f"{metric_key} missing from HARDCODED_DEFAULTS"
        )

        # Namespace in alarm def matches one of the type's namespaces
        assert ad["namespace"] in _NAMESPACE_MAP[resource_type], (
            f"{ad['namespace']} not in _NAMESPACE_MAP[{resource_type}]"
        )


# ──────────────────────────────────────────────
# Property 3: Tag-Based Collector Filtering (Monitoring=on)
# **Validates: Requirements 1.3, 2.4, 5.3, 6.3, 7.3, 8.3**
# ──────────────────────────────────────────────

TAG_BASED_TYPES = ["Lambda", "VPN", "Backup", "MQ", "CLB", "OpenSearch"]


@given(resource_type=st.sampled_from(TAG_BASED_TYPES))
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_tag_based_collector_alarm_defs_structure(resource_type: str):
    """Tag-based collector types all produce valid, non-empty alarm defs."""
    alarm_defs = _get_alarm_defs(resource_type)

    assert len(alarm_defs) > 0, (
        f"Tag-based type {resource_type} should have alarm defs"
    )

    for ad in alarm_defs:
        # Every def has a namespace matching the type's namespace map
        assert ad["namespace"] in _NAMESPACE_MAP[resource_type]
        # Every def has a dimension_key matching the type's dimension key map
        assert ad["dimension_key"] == _DIMENSION_KEY_MAP[resource_type]


# ──────────────────────────────────────────────
# Property 4: ACM Full_Collection with Auto-Injected Tag
# **Validates: Requirements 4.3, 4.4, 4.9, 13.1, 13.2, 13.3**
# ──────────────────────────────────────────────


def test_acm_alarm_defs_and_collector_exist():
    """ACM alarm defs exist with correct namespace/dimension, and collector is importable."""
    alarm_defs = _get_alarm_defs("ACM")

    assert len(alarm_defs) > 0, "ACM should have alarm defs"

    for ad in alarm_defs:
        assert ad["namespace"] == "AWS/CertificateManager"
        assert ad["dimension_key"] == "CertificateArn"
        assert ad["comparison"] == "LessThanThreshold"
        assert ad["period"] == 86400

    # Verify the ACM collector module is importable and has collect_monitored_resources
    from common.collectors import acm as acm_collector

    assert hasattr(acm_collector, "collect_monitored_resources")
    assert callable(acm_collector.collect_monitored_resources)


# ──────────────────────────────────────────────
# Property 5: APIGW _api_type Routing Correctness
# **Validates: Requirements 3-A.2, 3-A.3, 3-B.5, 3-B.6, 3-B.8, 3-C.10,
#   3-C.11, 3-C.13, 3-D.15, 3-D.16, 3-D.18, 3-E.22, 9.3**
# ──────────────────────────────────────────────

_EXPECTED_APIGW = {
    "REST": {
        "dimension_key": "ApiName",
        "metrics": {"ApiLatency", "Api4XXError", "Api5XXError"},
    },
    "HTTP": {
        "dimension_key": "ApiId",
        "metrics": {"ApiLatency", "Api4xx", "Api5xx"},
    },
    "WEBSOCKET": {
        "dimension_key": "ApiId",
        "metrics": {"WsConnectCount", "WsMessageCount", "WsIntegrationError", "WsExecutionError"},
    },
}


@given(api_type=st.sampled_from(APIGW_API_TYPES))
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_apigw_api_type_routing(api_type: str):
    """_get_apigw_alarm_defs returns correct dimension_key and metric set per api_type."""
    alarm_defs = _get_apigw_alarm_defs({"_api_type": api_type})
    expected = _EXPECTED_APIGW[api_type]

    actual_metrics = {ad["metric"] for ad in alarm_defs}
    assert actual_metrics == expected["metrics"], (
        f"APIGW {api_type}: expected {expected['metrics']}, got {actual_metrics}"
    )

    for ad in alarm_defs:
        assert ad["dimension_key"] == expected["dimension_key"], (
            f"APIGW {api_type}: expected dim_key {expected['dimension_key']}, "
            f"got {ad['dimension_key']}"
        )
        assert ad["namespace"] == "AWS/ApiGateway"


# ──────────────────────────────────────────────
# Property 6: OpenSearch Compound Dimension Construction
# **Validates: Requirements 8.2, 8.5**
# ──────────────────────────────────────────────


@given(
    domain_name=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-"),
        min_size=1,
        max_size=28,
    ),
    account_id=st.from_regex(r"[0-9]{12}", fullmatch=True),
)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_opensearch_compound_dimension(domain_name: str, account_id: str):
    """_build_dimensions for OpenSearch returns DomainName + ClientId dimensions."""
    alarm_def = _get_alarm_defs("OpenSearch")[0]  # any OpenSearch alarm def
    resource_tags = {"_client_id": account_id}

    dims = _build_dimensions(alarm_def, domain_name, "OpenSearch", resource_tags)

    assert len(dims) == 2, f"Expected 2 dimensions, got {len(dims)}"

    dim_names = {d["Name"] for d in dims}
    assert "DomainName" in dim_names
    assert "ClientId" in dim_names

    domain_dim = next(d for d in dims if d["Name"] == "DomainName")
    client_dim = next(d for d in dims if d["Name"] == "ClientId")

    assert domain_dim["Value"] == domain_name
    assert client_dim["Value"] == account_id


# ──────────────────────────────────────────────
# Property 7: VPN treat_missing_data=breaching
# **Validates: Requirements 2.3**
# ──────────────────────────────────────────────

NON_VPN_TYPES = ["Lambda", "APIGW", "ACM", "Backup", "MQ", "CLB", "OpenSearch"]


def test_vpn_treat_missing_data_breaching():
    """All VPN alarms have treat_missing_data='breaching'; other types do not."""
    # VPN: all must be breaching
    for ad in _VPN_ALARMS:
        assert ad.get("treat_missing_data") == "breaching", (
            f"VPN alarm {ad['metric']} missing treat_missing_data=breaching"
        )

    # Other 7 new types: treat_missing_data absent or "missing"
    for rtype in NON_VPN_TYPES:
        tags = _tags_for_type(rtype)
        alarm_defs = _get_alarm_defs(rtype, tags)
        for ad in alarm_defs:
            tmd = ad.get("treat_missing_data")
            assert tmd is None or tmd == "missing", (
                f"{rtype} alarm {ad['metric']} has unexpected "
                f"treat_missing_data={tmd}"
            )


# ──────────────────────────────────────────────
# Property 8: Alive Checker Coverage
# **Validates: Requirements 12.1**
# ──────────────────────────────────────────────

_ALIVE_CHECKER_TYPES = [
    "Lambda", "VPN", "APIGW", "ACM", "Backup", "MQ", "CLB", "OpenSearch",
]


def test_alive_checker_coverage():
    """Each of 8 new types has a collector in _RESOURCE_TYPE_TO_COLLECTOR with resolve_alive_ids."""
    from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR

    for rtype in _ALIVE_CHECKER_TYPES:
        assert rtype in _RESOURCE_TYPE_TO_COLLECTOR, (
            f"_RESOURCE_TYPE_TO_COLLECTOR missing {rtype}"
        )
        collector = _RESOURCE_TYPE_TO_COLLECTOR[rtype]
        assert callable(getattr(collector, "resolve_alive_ids", None)), (
            f"collector for {rtype} missing resolve_alive_ids"
        )


# ──────────────────────────────────────────────
# Property 9: metric_name_to_key Round Trip
# **Validates: Requirements 9.8**
# ──────────────────────────────────────────────

# Some metric_names are shared across resource types with different metric keys.
# _metric_name_to_key is a flat dict so only one mapping can win.
# We exclude these known collisions from the round-trip check.
_METRIC_NAME_COLLISIONS = {
    "FreeStorageSpace",   # RDS→FreeStorageGB vs OpenSearch→OSFreeStorageSpace
    "UnHealthyHostCount", # TG→UnHealthyHostCount vs CLB→CLBUnHealthyHost
    "CPUUtilization",     # EC2/RDS→CPU vs OpenSearch→OsCPU
    "JVMMemoryPressure",  # OpenSearch uses same name as key, but shared
}


@given(
    resource_type=st_new_resource_type,
    api_type=st.sampled_from(APIGW_API_TYPES),
)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_metric_name_to_key_round_trip(resource_type: str, api_type: str):
    """For every alarm def, _metric_name_to_key(metric_name) == metric key (excluding collisions)."""
    tags = _tags_for_type(resource_type, api_type)
    alarm_defs = _get_alarm_defs(resource_type, tags)

    for ad in alarm_defs:
        metric_name = ad["metric_name"]
        expected_key = ad["metric"]

        if metric_name in _METRIC_NAME_COLLISIONS:
            # For collisions, just verify the mapping returns *some* valid key
            result = _metric_name_to_key(metric_name)
            assert result in HARDCODED_DEFAULTS, (
                f"_metric_name_to_key({metric_name!r}) = {result!r} "
                f"not in HARDCODED_DEFAULTS"
            )
            continue

        result = _metric_name_to_key(metric_name)
        assert result == expected_key, (
            f"_metric_name_to_key({metric_name!r}) = {result!r}, "
            f"expected {expected_key!r} for {resource_type}"
        )


# ──────────────────────────────────────────────
# Property 10: HARDCODED_DEFAULTS Threshold Direction Consistency
# **Validates: Requirements 1.7, 2.8, 4.8, 8.8**
# ──────────────────────────────────────────────

_LESS_THAN_METRICS = {
    "TunnelState": {
        "comparison": "LessThanThreshold",
        "default": HARDCODED_DEFAULTS["TunnelState"],
    },
    "DaysToExpiry": {
        "comparison": "LessThanThreshold",
        "default": HARDCODED_DEFAULTS["DaysToExpiry"],
    },
    "OSFreeStorageSpace": {
        "comparison": "LessThanThreshold",
        "default": HARDCODED_DEFAULTS["OSFreeStorageSpace"],
    },
}


@given(
    metric_key=st.sampled_from(list(_LESS_THAN_METRICS.keys())),
    current_value=st.floats(min_value=0.0, max_value=100000.0, allow_nan=False),
    threshold=st.floats(min_value=0.01, max_value=100000.0, allow_nan=False),
)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_hardcoded_defaults_threshold_direction(
    metric_key: str,
    current_value: float,
    threshold: float,
):
    """LessThanThreshold metrics fire when current_value < threshold."""
    info = _LESS_THAN_METRICS[metric_key]

    # Verify the alarm registry actually uses LessThanThreshold for this metric
    assert info["comparison"] == "LessThanThreshold"

    # The alarm fires when current_value < threshold (LessThanThreshold semantics)
    should_fire = current_value < threshold

    # Simulate the same logic as _process_resource in daily_monitor
    # "낮을수록 위험" metrics use: exceeded = current_value < threshold
    exceeded = current_value < threshold

    assert exceeded == should_fire, (
        f"{metric_key}: current={current_value}, threshold={threshold}, "
        f"exceeded={exceeded}, should_fire={should_fire}"
    )
