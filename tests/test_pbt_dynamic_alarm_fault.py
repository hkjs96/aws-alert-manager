"""
Bug Condition Exploration Test - 하드코딩 목록 외 Threshold 태그 알람 미생성

Property 1 (Bug Condition): create_alarms_for_resource()가 하드코딩 목록
(_EC2_ALARMS, _RDS_ALARMS, _ELB_ALARMS)에 없는 Threshold_{MetricName} 태그를
무시하여 동적 메트릭 알람이 생성되지 않는 버그.

**Validates: Requirements 1.1, 1.2, 2.1, 2.2**

EXPECTED: These tests FAIL on unfixed code because create_alarms_for_resource()
only iterates _get_alarm_defs() hardcoded list and ignores extra Threshold_* tags.
"""

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from common.alarm_manager import (
    _get_cw_client,
    create_alarms_for_resource,
)

# ──────────────────────────────────────────────
# 하드코딩 메트릭 목록 (alarm_manager.py 기준)
# ──────────────────────────────────────────────

_HARDCODED_METRICS = {
    "EC2": {"CPU", "Memory", "Disk"},
    "RDS": {"CPU", "FreeMemoryGB", "FreeStorageGB", "Connections"},
    "ALB": {"RequestCount"},
    "NLB": {"ProcessedBytes", "ActiveFlowCount", "NewFlowCount"},
    "TG": {"RequestCount", "HealthyHostCount"},
}

# resource_type별 CloudWatch 네임스페이스 + 디멘션 키
_NAMESPACE_MAP = {
    "EC2": ("AWS/EC2", "InstanceId"),
    "RDS": ("AWS/RDS", "DBInstanceIdentifier"),
    "ALB": ("AWS/ApplicationELB", "LoadBalancer"),
    "NLB": ("AWS/NetworkELB", "LoadBalancer"),
    "TG": ("AWS/ApplicationELB", "TargetGroup"),
}

# resource_type별 샘플 resource_id
_RESOURCE_IDS = {
    "EC2": "i-0abc123def456789a",
    "RDS": "db-test-dynamic",
    "ALB": "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/1234567890abcdef",
    "NLB": "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/my-nlb/1234567890abcdef",
    "TG": "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/my-tg/1234567890abcdef",
}

_ENV = {
    "ENVIRONMENT": "prod",
    "SNS_TOPIC_ARN_ALERT": "",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_SESSION_TOKEN": "testing",
}

# ──────────────────────────────────────────────
# Hypothesis 전략
# ──────────────────────────────────────────────

# 하드코딩 목록에 없는 메트릭 이름 (AWS 태그 허용 문자만 사용)
# 실제 CloudWatch 메트릭으로 존재할 법한 이름들
_DYNAMIC_METRIC_NAMES = [
    "NetworkIn",
    "NetworkOut",
    "ReadLatency",
    "WriteLatency",
    "DiskReadOps",
    "DiskWriteOps",
    "StatusCheckFailed",
    "NetworkPacketsIn",
    "NetworkPacketsOut",
    "ProcessedBytes",
    "ActiveConnectionCount",
    "NewConnectionCount",
    "ConsumedReadCapacityUnits",
    "BurstBalance",
    "ReadIOPS",
    "WriteIOPS",
]

resource_types = st.sampled_from(["EC2", "RDS", "ALB", "NLB", "TG"])


def _dynamic_metrics_for_type(resource_type: str) -> list[str]:
    """해당 resource_type의 하드코딩 목록에 없는 메트릭만 필터링."""
    hardcoded = _HARDCODED_METRICS[resource_type]
    return [m for m in _DYNAMIC_METRIC_NAMES if m not in hardcoded]


dynamic_metric_names = st.one_of(
    st.tuples(st.just("EC2"), st.sampled_from(_dynamic_metrics_for_type("EC2"))),
    st.tuples(st.just("RDS"), st.sampled_from(_dynamic_metrics_for_type("RDS"))),
    st.tuples(st.just("ALB"), st.sampled_from(_dynamic_metrics_for_type("ALB"))),
    st.tuples(st.just("NLB"), st.sampled_from(_dynamic_metrics_for_type("NLB"))),
    st.tuples(st.just("TG"), st.sampled_from(_dynamic_metrics_for_type("TG"))),
)

# 양의 숫자 임계치
positive_thresholds = st.floats(min_value=0.1, max_value=99999.0, allow_nan=False, allow_infinity=False)


# ──────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────

def _register_metric_and_create_alarms(
    resource_type: str,
    metric_name: str,
    threshold: float,
) -> list[str]:
    """moto CW에 메트릭 등록 후 create_alarms_for_resource 호출."""
    resource_id = _RESOURCE_IDS[resource_type]
    namespace, dimension_key = _NAMESPACE_MAP[resource_type]

    # ALB/NLB/TG dimension 값은 ARN에서 추출
    if resource_type in ("ALB", "NLB", "TG"):
        dim_value = resource_id.split("loadbalancer/", 1)[1] if "loadbalancer/" in resource_id else resource_id.split("targetgroup/", 1)[1]
    else:
        dim_value = resource_id

    cw = boto3.client("cloudwatch", region_name="us-east-1")
    cw.put_metric_data(
        Namespace=namespace,
        MetricData=[
            {
                "MetricName": metric_name,
                "Dimensions": [
                    {"Name": dimension_key, "Value": dim_value},
                ],
                "Value": 42.0,
                "Unit": "None",
            }
        ],
    )

    thr_str = str(int(threshold)) if threshold == int(threshold) else str(threshold)
    tags = {
        "Monitoring": "on",
        "Name": "test-dynamic-resource",
        f"Threshold_{metric_name}": thr_str,
    }

    return create_alarms_for_resource(resource_id, resource_type, tags)


# ──────────────────────────────────────────────
# 테스트
# ──────────────────────────────────────────────

class TestDynamicAlarmFaultCondition:
    """
    하드코딩 목록 외 Threshold 태그에 대해 알람이 생성되지 않는 버그 탐색.

    BUG: create_alarms_for_resource()가 _get_alarm_defs() 하드코딩 목록만
    순회하므로 태그에서 발견된 추가 메트릭은 무시된다.
    """

    @given(data=dynamic_metric_names, threshold=positive_thresholds)
    @settings(max_examples=20, deadline=None)
    @mock_aws
    def test_dynamic_metric_alarm_created(self, data, threshold):
        """
        **Property 1: Bug Condition** - 하드코딩 목록 외 Threshold 태그 알람 미생성

        하드코딩 목록에 없는 Threshold_{MetricName} 태그가 있고 CloudWatch에
        해당 메트릭 데이터가 존재할 때, create_alarms_for_resource()는 해당
        메트릭에 대한 알람을 생성해야 한다.

        **Validates: Requirements 1.1, 1.2, 2.1, 2.2**
        """
        resource_type, metric_name = data

        _get_cw_client.cache_clear()

        with pytest.MonkeyPatch.context() as mp:
            for k, v in _ENV.items():
                mp.setenv(k, v)

            result = _register_metric_and_create_alarms(
                resource_type, metric_name, threshold,
            )

        dynamic_alarm_found = any(metric_name in name for name in result)
        assert dynamic_alarm_found, (
            f"동적 메트릭 '{metric_name}' 알람이 생성되지 않음.\n"
            f"resource_type={resource_type}, threshold={threshold}\n"
            f"생성된 알람: {result}\n"
            f"원인: create_alarms_for_resource()가 _get_alarm_defs() "
            f"하드코딩 목록만 순회하여 Threshold_{metric_name} 태그 무시"
        )
