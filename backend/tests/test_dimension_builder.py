"""
dimension_builder 단위 테스트 — 리소스 유형별 디멘션 구성
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from moto import mock_aws
import boto3


# ──────────────────────────────────────────────
# _extract_elb_dimension
# ──────────────────────────────────────────────

class TestExtractElbDimension:
    def test_ALB_ARN에서_app_prefix_추출(self):
        from common.dimension_builder import _extract_elb_dimension

        arn = "arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:loadbalancer/app/my-alb/1a2b3c4d5e6f7890"
        result = _extract_elb_dimension(arn)
        assert result == "app/my-alb/1a2b3c4d5e6f7890"

    def test_NLB_ARN에서_net_prefix_추출(self):
        from common.dimension_builder import _extract_elb_dimension

        arn = "arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:loadbalancer/net/my-nlb/abcdef1234567890"
        result = _extract_elb_dimension(arn)
        assert result == "net/my-nlb/abcdef1234567890"

    def test_TG_ARN에서_targetgroup_prefix_유지(self):
        from common.dimension_builder import _extract_elb_dimension

        arn = "arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:targetgroup/my-tg/1234567890abcdef"
        result = _extract_elb_dimension(arn)
        assert result == "targetgroup/my-tg/1234567890abcdef"

    def test_일반_ID는_그대로_반환(self):
        from common.dimension_builder import _extract_elb_dimension

        resource_id = "i-0abcdef1234567890"
        result = _extract_elb_dimension(resource_id)
        assert result == resource_id


# ──────────────────────────────────────────────
# _build_dimensions
# ──────────────────────────────────────────────

class TestBuildDimensionsEC2:
    def test_EC2_단일_InstanceId_디멘션(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "InstanceId"}
        dims = _build_dimensions(alarm_def, "i-0abc1234", "EC2", {})

        assert dims == [{"Name": "InstanceId", "Value": "i-0abc1234"}]

    def test_EC2_extra_dimensions_추가됨(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {
            "dimension_key": "InstanceId",
            "extra_dimensions": [{"Name": "path", "Value": "/"}],
        }
        dims = _build_dimensions(alarm_def, "i-0abc1234", "EC2", {})

        assert {"Name": "InstanceId", "Value": "i-0abc1234"} in dims
        assert {"Name": "path", "Value": "/"} in dims


class TestBuildDimensionsRDS:
    def test_RDS_단일_DBInstanceIdentifier_디멘션(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "DBInstanceIdentifier"}
        dims = _build_dimensions(alarm_def, "my-rds-instance", "RDS", {})

        assert dims == [{"Name": "DBInstanceIdentifier", "Value": "my-rds-instance"}]


class TestBuildDimensionsALB:
    def test_ALB_LoadBalancer_단일_디멘션_ARN_변환(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "LoadBalancer"}
        arn = "arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:loadbalancer/app/my-alb/abc123"
        dims = _build_dimensions(alarm_def, arn, "ALB", {})

        assert len(dims) == 1
        assert dims[0]["Name"] == "LoadBalancer"
        assert dims[0]["Value"] == "app/my-alb/abc123"

    def test_NLB_LoadBalancer_단일_디멘션_ARN_변환(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "LoadBalancer"}
        arn = "arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:loadbalancer/net/my-nlb/def456"
        dims = _build_dimensions(alarm_def, arn, "NLB", {})

        assert len(dims) == 1
        assert dims[0]["Name"] == "LoadBalancer"
        assert dims[0]["Value"] == "net/my-nlb/def456"


class TestBuildDimensionsTG:
    def test_TG_TargetGroup_plus_LoadBalancer_복합_디멘션(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "TargetGroup"}
        tg_arn = "arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:targetgroup/my-tg/111aaa"
        lb_arn = "arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:loadbalancer/app/my-alb/222bbb"
        resource_tags = {"_lb_arn": lb_arn}

        dims = _build_dimensions(alarm_def, tg_arn, "TG", resource_tags)

        assert len(dims) == 2
        tg_dim = next(d for d in dims if d["Name"] == "TargetGroup")
        lb_dim = next(d for d in dims if d["Name"] == "LoadBalancer")
        assert tg_dim["Value"] == "targetgroup/my-tg/111aaa"
        assert lb_dim["Value"] == "app/my-alb/222bbb"


class TestBuildDimensionsECS:
    def test_ECS_ServiceName_ClusterName_복합(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "ServiceName"}
        dims = _build_dimensions(
            alarm_def, "my-service", "ECS",
            {"_cluster_name": "my-cluster"},
        )

        assert {"Name": "ServiceName", "Value": "my-service"} in dims
        assert {"Name": "ClusterName", "Value": "my-cluster"} in dims

    def test_ECS_ClusterName_없으면_ServiceName만(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "ServiceName"}
        dims = _build_dimensions(alarm_def, "my-service", "ECS", {})

        assert len(dims) == 1
        assert dims[0] == {"Name": "ServiceName", "Value": "my-service"}


class TestBuildDimensionsWAF:
    def test_WAF_WebACL_Rule_Region_세개_디멘션(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "WebACL"}
        tags = {"_waf_rule": "MyRule", "_waf_region": "ap-northeast-2"}
        dims = _build_dimensions(alarm_def, "my-webacl", "WAF", tags)

        names = [d["Name"] for d in dims]
        assert "WebACL" in names
        assert "Rule" in names
        assert "Region" in names

        assert next(d for d in dims if d["Name"] == "WebACL")["Value"] == "my-webacl"
        assert next(d for d in dims if d["Name"] == "Rule")["Value"] == "MyRule"
        assert next(d for d in dims if d["Name"] == "Region")["Value"] == "ap-northeast-2"

    def test_WAF_Rule_기본값_ALL(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "WebACL"}
        with patch.dict(os.environ, {"AWS_REGION": "ap-northeast-2"}):
            dims = _build_dimensions(alarm_def, "my-webacl", "WAF", {})

        rule_dim = next(d for d in dims if d["Name"] == "Rule")
        assert rule_dim["Value"] == "ALL"


class TestBuildDimensionsS3:
    def test_S3_BucketName_FilterId_Request_Metrics(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "BucketName"}
        dims = _build_dimensions(alarm_def, "my-bucket", "S3", {})

        assert {"Name": "BucketName", "Value": "my-bucket"} in dims
        filter_dim = next(d for d in dims if d["Name"] == "FilterId")
        assert filter_dim["Value"] == "EntireBucket"

    def test_S3_BucketName_StorageType_needs_storage_type(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "BucketName", "needs_storage_type": True}
        dims = _build_dimensions(
            alarm_def, "my-bucket", "S3",
            {"_storage_type": "StandardStorage"},
        )

        names = [d["Name"] for d in dims]
        assert "StorageType" in names
        assert "FilterId" not in names


class TestBuildDimensionsSageMaker:
    def test_SageMaker_EndpointName_VariantName_복합(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "EndpointName"}
        dims = _build_dimensions(
            alarm_def, "my-endpoint", "SageMaker",
            {"_variant_name": "AllTraffic"},
        )

        assert {"Name": "EndpointName", "Value": "my-endpoint"} in dims
        assert {"Name": "VariantName", "Value": "AllTraffic"} in dims

    def test_SageMaker_VariantName_없으면_EndpointName만(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "EndpointName"}
        dims = _build_dimensions(alarm_def, "my-endpoint", "SageMaker", {})

        assert len(dims) == 1
        assert dims[0] == {"Name": "EndpointName", "Value": "my-endpoint"}


class TestBuildDimensionsCloudFront:
    def test_CloudFront_DistributionId_plus_Region_Global(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "DistributionId"}
        dims = _build_dimensions(alarm_def, "EXXXABC123", "CloudFront", {})

        assert {"Name": "DistributionId", "Value": "EXXXABC123"} in dims
        assert {"Name": "Region", "Value": "Global"} in dims


class TestBuildDimensionsOpenSearch:
    def test_OpenSearch_ClientId_추가됨(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "DomainName"}
        dims = _build_dimensions(
            alarm_def, "my-domain", "OpenSearch",
            {"_client_id": "123456789012"},
        )

        assert {"Name": "DomainName", "Value": "my-domain"} in dims
        assert {"Name": "ClientId", "Value": "123456789012"} in dims

    def test_OpenSearch_ClientId_없으면_단일_디멘션(self):
        from common.dimension_builder import _build_dimensions

        alarm_def = {"dimension_key": "DomainName"}
        dims = _build_dimensions(alarm_def, "my-domain", "OpenSearch", {})

        assert len(dims) == 1
        assert dims[0] == {"Name": "DomainName", "Value": "my-domain"}


# ──────────────────────────────────────────────
# _resolve_tg_namespace
# ──────────────────────────────────────────────

class TestResolveTgNamespace:
    def test_network_lb_type은_NetworkELB_반환(self):
        from common.dimension_builder import _resolve_tg_namespace

        alarm_def = {"namespace": "AWS/ApplicationELB"}
        result = _resolve_tg_namespace(alarm_def, {"_lb_type": "network"})
        assert result == "AWS/NetworkELB"

    def test_application_lb_type은_alarm_def_namespace_반환(self):
        from common.dimension_builder import _resolve_tg_namespace

        alarm_def = {"namespace": "AWS/ApplicationELB"}
        result = _resolve_tg_namespace(alarm_def, {"_lb_type": "application"})
        assert result == "AWS/ApplicationELB"

    def test_lb_type_없으면_alarm_def_namespace_반환(self):
        from common.dimension_builder import _resolve_tg_namespace

        alarm_def = {"namespace": "AWS/ApplicationELB"}
        result = _resolve_tg_namespace(alarm_def, {})
        assert result == "AWS/ApplicationELB"


# ──────────────────────────────────────────────
# _select_best_dimensions
# ──────────────────────────────────────────────

class TestSelectBestDimensions:
    def test_빈_목록이면_빈_리스트_반환(self):
        from common.dimension_builder import _select_best_dimensions

        result = _select_best_dimensions([], "LoadBalancer")
        assert result == []

    def test_primary_dim_only_조합_우선_선택(self):
        from common.dimension_builder import _select_best_dimensions

        metrics = [
            {"Dimensions": [
                {"Name": "LoadBalancer", "Value": "app/alb/abc"},
                {"Name": "AvailabilityZone", "Value": "ap-northeast-2a"},
            ]},
            {"Dimensions": [
                {"Name": "LoadBalancer", "Value": "app/alb/abc"},
            ]},
        ]
        result = _select_best_dimensions(metrics, "LoadBalancer")
        assert result == [{"Name": "LoadBalancer", "Value": "app/alb/abc"}]

    def test_AZ_없는_조합_중_최소_디멘션_선택(self):
        from common.dimension_builder import _select_best_dimensions

        metrics = [
            {"Dimensions": [
                {"Name": "LoadBalancer", "Value": "app/alb/abc"},
                {"Name": "AvailabilityZone", "Value": "ap-northeast-2a"},
            ]},
            {"Dimensions": [
                {"Name": "LoadBalancer", "Value": "app/alb/abc"},
                {"Name": "TargetGroup", "Value": "targetgroup/tg/111"},
            ]},
            {"Dimensions": [
                {"Name": "LoadBalancer", "Value": "app/alb/abc"},
                {"Name": "TargetGroup", "Value": "targetgroup/tg/111"},
                {"Name": "OtherDim", "Value": "val"},
            ]},
        ]
        result = _select_best_dimensions(metrics, "LoadBalancer")
        # AZ 없는 것 중 가장 작은 것 선택
        assert len(result) == 2
        assert not any(d["Name"] == "AvailabilityZone" for d in result)

    def test_모두_AZ_포함이면_최소_디멘션_선택(self):
        from common.dimension_builder import _select_best_dimensions

        metrics = [
            {"Dimensions": [
                {"Name": "LoadBalancer", "Value": "app/alb/abc"},
                {"Name": "AvailabilityZone", "Value": "ap-northeast-2a"},
                {"Name": "Extra", "Value": "v"},
            ]},
            {"Dimensions": [
                {"Name": "LoadBalancer", "Value": "app/alb/abc"},
                {"Name": "AvailabilityZone", "Value": "ap-northeast-2b"},
            ]},
        ]
        result = _select_best_dimensions(metrics, "LoadBalancer")
        assert len(result) == 2  # 가장 작은 것


# ──────────────────────────────────────────────
# _get_disk_dimensions
# ──────────────────────────────────────────────

class TestGetDiskDimensions:
    @mock_aws
    def test_root_path_발견_시_dimension_반환(self):
        from common.dimension_builder import _get_disk_dimensions
        from common._clients import _get_cw_client

        _get_cw_client.cache_clear()
        cw = boto3.client("cloudwatch", region_name="ap-northeast-2")

        cw.put_metric_data(
            Namespace="CWAgent",
            MetricData=[{
                "MetricName": "disk_used_percent",
                "Dimensions": [
                    {"Name": "InstanceId", "Value": "i-0abc1234"},
                    {"Name": "path", "Value": "/"},
                    {"Name": "device", "Value": "xvda1"},
                    {"Name": "fstype", "Value": "ext4"},
                ],
                "Value": 50.0,
                "Unit": "Percent",
            }],
        )

        result = _get_disk_dimensions("i-0abc1234", cw=cw)
        assert len(result) == 1
        dim_names = [d["Name"] for d in result[0]]
        assert "path" in dim_names
        path_val = next(d["Value"] for d in result[0] if d["Name"] == "path")
        assert path_val == "/"
        _get_cw_client.cache_clear()

    @mock_aws
    def test_메트릭_없으면_빈_리스트_반환(self):
        from common.dimension_builder import _get_disk_dimensions
        from common._clients import _get_cw_client

        _get_cw_client.cache_clear()
        cw = boto3.client("cloudwatch", region_name="ap-northeast-2")

        result = _get_disk_dimensions("i-nonexistent", cw=cw)
        assert result == []
        _get_cw_client.cache_clear()

    @mock_aws
    def test_extra_paths_포함_필터링(self):
        from common.dimension_builder import _get_disk_dimensions
        from common._clients import _get_cw_client

        _get_cw_client.cache_clear()
        cw = boto3.client("cloudwatch", region_name="ap-northeast-2")

        for path in ["/", "/data"]:
            cw.put_metric_data(
                Namespace="CWAgent",
                MetricData=[{
                    "MetricName": "disk_used_percent",
                    "Dimensions": [
                        {"Name": "InstanceId", "Value": "i-0abc1234"},
                        {"Name": "path", "Value": path},
                        {"Name": "device", "Value": "xvda1"},
                        {"Name": "fstype", "Value": "ext4"},
                    ],
                    "Value": 50.0,
                    "Unit": "Percent",
                }],
            )

        result = _get_disk_dimensions("i-0abc1234", extra_paths={"/data"}, cw=cw)
        paths_found = {
            next(d["Value"] for d in dims if d["Name"] == "path")
            for dims in result
        }
        assert "/" in paths_found
        assert "/data" in paths_found
        _get_cw_client.cache_clear()

    @mock_aws
    def test_default_includes_data_disk_and_excludes_boot_paths(self):
        from common.dimension_builder import _get_disk_dimensions
        from common._clients import _get_cw_client

        _get_cw_client.cache_clear()
        cw = boto3.client("cloudwatch", region_name="ap-northeast-2")

        for path, device, fstype in [
            ("/", "xvda1", "xfs"),
            ("/data", "xvdb", "ext4"),
            ("/boot/efi", "xvda128", "vfat"),
        ]:
            cw.put_metric_data(
                Namespace="CWAgent",
                MetricData=[{
                    "MetricName": "disk_used_percent",
                    "Dimensions": [
                        {"Name": "InstanceId", "Value": "i-0abc1234"},
                        {"Name": "path", "Value": path},
                        {"Name": "device", "Value": device},
                        {"Name": "fstype", "Value": fstype},
                    ],
                    "Value": 50.0,
                    "Unit": "Percent",
                }],
            )

        result = _get_disk_dimensions("i-0abc1234", cw=cw)
        paths_found = {
            next(d["Value"] for d in dims if d["Name"] == "path")
            for dims in result
        }
        assert paths_found == {"/", "/data"}
        _get_cw_client.cache_clear()
