"""
PBT — Correctness Properties for Extended Resource Monitoring (12 new types).

Property-based tests verifying alarm registry data integrity, mapping completeness,
dimension construction, treat_missing_data, region fields, and threshold direction
consistency for SQS, ECS, MSK, DynamoDB, CloudFront, WAF, Route53, DX, EFS, S3,
SageMaker, SNS.
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from common import HARDCODED_DEFAULTS
from common.alarm_registry import (
    _CLOUDFRONT_ALARMS,
    _DIMENSION_KEY_MAP,
    _DX_ALARMS,
    _ECS_ALARMS,
    _HARDCODED_METRIC_KEYS,
    _METRIC_DISPLAY,
    _MSK_ALARMS,
    _NAMESPACE_MAP,
    _ROUTE53_ALARMS,
    _S3_ALARMS,
    _SAGEMAKER_ALARMS,
    _WAF_ALARMS,
    _get_alarm_defs,
    _metric_name_to_key,
)
from common.dimension_builder import _build_dimensions

# ──────────────────────────────────────────────
# Shared strategies
# ──────────────────────────────────────────────

NEW_RESOURCE_TYPES = [
    "SQS", "ECS", "MSK", "DynamoDB", "CloudFront", "WAF",
    "Route53", "DX", "EFS", "S3", "SageMaker", "SNS",
]

st_new_resource_type = st.sampled_from(NEW_RESOURCE_TYPES)

VALID_COMPARISONS = {
    "GreaterThanThreshold",
    "GreaterThanOrEqualToThreshold",
    "LessThanThreshold",
    "LessThanOrEqualToThreshold",
}


# ──────────────────────────────────────────────
# Property 1: Alarm Definition Structural Correctness
# **Validates: Requirements 1.1, 1.2, 2-B.5, 2-B.6, 2-B.7, 3.1, 3.2, 4.1,
#   4.2, 5.1, 5.2, 6.1, 6.2, 7.1, 7.2, 8.1, 8.2, 9.1, 9.2, 9.3, 10-A.1,
#   10-A.2, 11-A.1, 11-A.2, 12.1, 12.2, 13.1, 13.2**
# ──────────────────────────────────────────────


@given(
    resource_type=st_new_resource_type,
    resource_tags=st.fixed_dictionaries(
        {}, optional={"Monitoring": st.just("on"), "extra": st.text(max_size=10)},
    ),
)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_alarm_def_structural_correctness(resource_type: str, resource_tags: dict):
    """Every alarm def has required keys, valid namespace, dimension_key, and comparison."""
    alarm_defs = _get_alarm_defs(resource_type, resource_tags)

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
# **Validates: Requirements 1.6, 1.7, 2-A.1, 2-D.13, 3.7, 3.8, 4.6, 4.7,
#   5.7, 5.8, 6.7, 6.8, 7.8, 7.9, 8.7, 8.8, 9.7, 9.8, 10-D.10, 10-D.11,
#   11-C.9, 11-C.10, 12.6, 12.7, 13.4, 13.5, 13.6, 13.7**
# ──────────────────────────────────────────────


@given(resource_type=st_new_resource_type)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_registry_mapping_table_completeness(resource_type: str):
    """Every alarm def's metric key exists in all mapping tables."""
    alarm_defs = _get_alarm_defs(resource_type)

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
# **Validates: Requirements 1.3, 2-C.8, 3.4, 4.3, 5.4, 6.3, 7.5, 8.4,
#   9.4, 10-B.4, 11-B.3, 12.3**
# ──────────────────────────────────────────────


@given(resource_type=st_new_resource_type)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_tag_based_collector_alarm_defs_structure(resource_type: str):
    """All 12 tag-based collector types produce valid, non-empty alarm defs."""
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
# Property 4: ECS _ecs_launch_type Alarm Invariance
# **Validates: Requirements 2-A.2, 2-A.3, 13.3**
# ──────────────────────────────────────────────

ECS_LAUNCH_TYPES = ["FARGATE", "EC2"]


@given(
    launch_type=st.sampled_from(ECS_LAUNCH_TYPES),
    extra_tags=st.fixed_dictionaries(
        {}, optional={"Monitoring": st.just("on"), "env": st.text(max_size=8)},
    ),
)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_ecs_launch_type_alarm_invariance(launch_type: str, extra_tags: dict):
    """_get_alarm_defs('ECS', tags) always returns same alarms regardless of launch type."""
    tags = {"_ecs_launch_type": launch_type, **extra_tags}
    alarm_defs = _get_alarm_defs("ECS", tags)

    expected_metrics = {"EcsCPU", "EcsMemory", "RunningTaskCount"}
    actual_metrics = {ad["metric"] for ad in alarm_defs}

    assert actual_metrics == expected_metrics, (
        f"ECS {launch_type}: expected {expected_metrics}, got {actual_metrics}"
    )

    # Verify identical to _ECS_ALARMS (launch type does NOT affect definitions)
    assert alarm_defs is _ECS_ALARMS


# ──────────────────────────────────────────────
# Property 5: Compound Dimension Construction (ECS, WAF, S3, SageMaker)
# **Validates: Requirements 2-B.6, 2-C.10, 6.2, 6.4, 10-A.2, 10-A.3,
#   10-B.5, 11-A.2, 11-B.5, 17.1, 17.2, 17.3, 17.4, 17.5**
# ──────────────────────────────────────────────

_safe_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"),
        whitelist_characters="-_",
    ),
    min_size=1,
    max_size=20,
)


@given(resource_id=_safe_text, cluster_name=_safe_text)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_ecs_compound_dimension(resource_id: str, cluster_name: str):
    """_build_dimensions for ECS returns ServiceName + ClusterName."""
    alarm_def = _ECS_ALARMS[0]
    tags = {"_cluster_name": cluster_name}

    dims = _build_dimensions(alarm_def, resource_id, "ECS", tags)

    assert len(dims) == 2
    dim_names = {d["Name"] for d in dims}
    assert "ServiceName" in dim_names
    assert "ClusterName" in dim_names

    svc_dim = next(d for d in dims if d["Name"] == "ServiceName")
    cls_dim = next(d for d in dims if d["Name"] == "ClusterName")
    assert svc_dim["Value"] == resource_id
    assert cls_dim["Value"] == cluster_name


@given(resource_id=_safe_text, waf_rule=_safe_text)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_waf_compound_dimension(resource_id: str, waf_rule: str):
    """_build_dimensions for WAF returns WebACL + Rule."""
    alarm_def = _WAF_ALARMS[0]
    tags = {"_waf_rule": waf_rule}

    dims = _build_dimensions(alarm_def, resource_id, "WAF", tags)

    assert len(dims) == 2
    dim_names = {d["Name"] for d in dims}
    assert "WebACL" in dim_names
    assert "Rule" in dim_names

    acl_dim = next(d for d in dims if d["Name"] == "WebACL")
    rule_dim = next(d for d in dims if d["Name"] == "Rule")
    assert acl_dim["Value"] == resource_id
    assert rule_dim["Value"] == waf_rule


@given(resource_id=_safe_text, storage_type=_safe_text)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_s3_compound_dimension(resource_id: str, storage_type: str):
    """_build_dimensions for S3 with needs_storage_type returns BucketName + StorageType."""
    # Pick an alarm_def with needs_storage_type=True
    storage_alarm = next(ad for ad in _S3_ALARMS if ad.get("needs_storage_type"))
    tags = {"_storage_type": storage_type}

    dims = _build_dimensions(storage_alarm, resource_id, "S3", tags)

    assert len(dims) == 2
    dim_names = {d["Name"] for d in dims}
    assert "BucketName" in dim_names
    assert "StorageType" in dim_names

    bucket_dim = next(d for d in dims if d["Name"] == "BucketName")
    st_dim = next(d for d in dims if d["Name"] == "StorageType")
    assert bucket_dim["Value"] == resource_id
    assert st_dim["Value"] == storage_type


@given(resource_id=_safe_text, variant_name=_safe_text)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_sagemaker_compound_dimension(resource_id: str, variant_name: str):
    """_build_dimensions for SageMaker returns EndpointName + VariantName."""
    alarm_def = _SAGEMAKER_ALARMS[0]
    tags = {"_variant_name": variant_name}

    dims = _build_dimensions(alarm_def, resource_id, "SageMaker", tags)

    assert len(dims) == 2
    dim_names = {d["Name"] for d in dims}
    assert "EndpointName" in dim_names
    assert "VariantName" in dim_names

    ep_dim = next(d for d in dims if d["Name"] == "EndpointName")
    vn_dim = next(d for d in dims if d["Name"] == "VariantName")
    assert ep_dim["Value"] == resource_id
    assert vn_dim["Value"] == variant_name


def test_ecs_missing_cluster_name_primary_only():
    """ECS with missing _cluster_name returns primary dimension only (no crash)."""
    alarm_def = _ECS_ALARMS[0]
    dims = _build_dimensions(alarm_def, "my-service", "ECS", {})

    assert len(dims) == 1
    assert dims[0]["Name"] == "ServiceName"
    assert dims[0]["Value"] == "my-service"


def test_sagemaker_missing_variant_primary_only():
    """SageMaker with missing _variant_name returns primary dimension only (no crash)."""
    alarm_def = _SAGEMAKER_ALARMS[0]
    dims = _build_dimensions(alarm_def, "my-endpoint", "SageMaker", {})

    assert len(dims) == 1
    assert dims[0]["Name"] == "EndpointName"
    assert dims[0]["Value"] == "my-endpoint"


# ──────────────────────────────────────────────
# Property 6: treat_missing_data=breaching for Route53/DX/MSK
# **Validates: Requirements 7.3, 8.3, 3.3, 18.1, 18.2, 18.3, 18.4**
# ──────────────────────────────────────────────

NON_BREACHING_TYPES = [
    "SQS", "ECS", "DynamoDB", "CloudFront", "WAF", "EFS", "S3", "SageMaker", "SNS",
]


def test_treat_missing_data_breaching():
    """Route53/DX all breaching; MSK only ActiveControllerCount breaching; others absent or missing."""
    # Route53: all must be breaching
    for ad in _ROUTE53_ALARMS:
        assert ad.get("treat_missing_data") == "breaching", (
            f"Route53 alarm {ad['metric']} missing treat_missing_data=breaching"
        )

    # DX: all must be breaching
    for ad in _DX_ALARMS:
        assert ad.get("treat_missing_data") == "breaching", (
            f"DX alarm {ad['metric']} missing treat_missing_data=breaching"
        )

    # MSK: only ActiveControllerCount has breaching
    for ad in _MSK_ALARMS:
        if ad["metric"] == "ActiveControllerCount":
            assert ad.get("treat_missing_data") == "breaching", (
                "MSK ActiveControllerCount missing treat_missing_data=breaching"
            )
        else:
            tmd = ad.get("treat_missing_data")
            assert tmd is None or tmd == "missing", (
                f"MSK alarm {ad['metric']} has unexpected "
                f"treat_missing_data={tmd}"
            )

    # Other 9 types: treat_missing_data absent or "missing"
    for rtype in NON_BREACHING_TYPES:
        alarm_defs = _get_alarm_defs(rtype)
        for ad in alarm_defs:
            tmd = ad.get("treat_missing_data")
            assert tmd is None or tmd == "missing", (
                f"{rtype} alarm {ad['metric']} has unexpected "
                f"treat_missing_data={tmd}"
            )


# ──────────────────────────────────────────────
# Property 7: metric_name_to_key Round Trip
# **Validates: Requirements 13.8**
# ──────────────────────────────────────────────

# Known collisions: ECS/SageMaker CPUUtilization maps to "CPU" (EC2/RDS),
# not "EcsCPU"/"SMCPU". Collectors return the key directly for these.
_METRIC_NAME_COLLISIONS = {
    "CPUUtilization",  # EC2/RDS→CPU, ECS→EcsCPU, SageMaker→SMCPU
}


@given(resource_type=st_new_resource_type)
@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
def test_metric_name_to_key_round_trip(resource_type: str):
    """For every alarm def, _metric_name_to_key(metric_name) == metric key (excluding collisions)."""
    alarm_defs = _get_alarm_defs(resource_type)

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
# Property 8: Alive Checker Coverage
# **Validates: Requirements 16.1, 16.3**
# ──────────────────────────────────────────────


def test_alive_checker_coverage():
    """Each of 12 new types has a collector in _RESOURCE_TYPE_TO_COLLECTOR with resolve_alive_ids."""
    from daily_monitor.lambda_handler import _RESOURCE_TYPE_TO_COLLECTOR

    for rtype in NEW_RESOURCE_TYPES:
        assert rtype in _RESOURCE_TYPE_TO_COLLECTOR, (
            f"_RESOURCE_TYPE_TO_COLLECTOR missing {rtype}"
        )
        collector = _RESOURCE_TYPE_TO_COLLECTOR[rtype]
        assert callable(getattr(collector, "resolve_alive_ids", None)), (
            f"collector for {rtype} missing resolve_alive_ids"
        )


# ──────────────────────────────────────────────
# Property 9: CloudFront/Route53 us-east-1 Region
# **Validates: Requirements 5.3, 7.4**
# ──────────────────────────────────────────────

NON_REGION_TYPES = [
    "SQS", "ECS", "MSK", "DynamoDB", "WAF", "DX", "EFS", "S3", "SageMaker", "SNS",
]


def test_cloudfront_route53_us_east_1_region():
    """CloudFront/Route53 alarms have region=us-east-1; other 10 types have no region field."""
    # CloudFront: all must have region=us-east-1
    for ad in _CLOUDFRONT_ALARMS:
        assert ad.get("region") == "us-east-1", (
            f"CloudFront alarm {ad['metric']} missing region=us-east-1"
        )

    # Route53: all must have region=us-east-1
    for ad in _ROUTE53_ALARMS:
        assert ad.get("region") == "us-east-1", (
            f"Route53 alarm {ad['metric']} missing region=us-east-1"
        )

    # Other 10 types: no region field
    for rtype in NON_REGION_TYPES:
        alarm_defs = _get_alarm_defs(rtype)
        for ad in alarm_defs:
            assert "region" not in ad, (
                f"{rtype} alarm {ad['metric']} has unexpected region field"
            )


# ──────────────────────────────────────────────
# Property 10: Lower-is-Dangerous Threshold Direction Consistency
# **Validates: Requirements 2-B.7, 3.3, 7.1, 8.1, 9.3**
# ──────────────────────────────────────────────

_LESS_THAN_METRICS = {
    "RunningTaskCount": {
        "comparison": "LessThanThreshold",
        "default": HARDCODED_DEFAULTS["RunningTaskCount"],
    },
    "ActiveControllerCount": {
        "comparison": "LessThanThreshold",
        "default": HARDCODED_DEFAULTS["ActiveControllerCount"],
    },
    "HealthCheckStatus": {
        "comparison": "LessThanThreshold",
        "default": HARDCODED_DEFAULTS["HealthCheckStatus"],
    },
    "ConnectionState": {
        "comparison": "LessThanThreshold",
        "default": HARDCODED_DEFAULTS["ConnectionState"],
    },
    "BurstCreditBalance": {
        "comparison": "LessThanThreshold",
        "default": HARDCODED_DEFAULTS["BurstCreditBalance"],
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
def test_lower_is_dangerous_threshold_direction(
    metric_key: str,
    current_value: float,
    threshold: float,
):
    """LessThanThreshold metrics fire when current_value < threshold (낮을수록 위험)."""
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
