"""
Tag_Resolver 모듈 - Requirements 2.1, 2.2, 2.3, 2.4, 2.5

태그 → 환경 변수 → 하드코딩 기본값 순으로 임계치를 조회하는 모듈.
향후 DB 교체를 고려한 인터페이스 제공.
"""

import functools
import logging
import os

import boto3
from botocore.exceptions import ClientError

from common import HARDCODED_DEFAULTS

logger = logging.getLogger(__name__)


def is_threshold_off(resource_tags: dict, metric_name: str) -> bool:
    """
    Threshold_{metric_name} 태그 값이 'off'(대소문자 무관)인지 판별.
    """
    return resource_tags.get(f"Threshold_{metric_name}", "").strip().lower() == "off"


def get_threshold(resource_tags: dict, metric_name: str) -> float:
    """
    리소스 태그에서 임계치를 조회.

    조회 우선순위: 태그 값 → 환경 변수 기본값 → 시스템 하드코딩 기본값.
    어떤 경우에도 유효한 양의 숫자(> 0)를 반환하며,
    절대 None을 반환하거나 예외를 발생시키지 않는다.

    Args:
        resource_tags: 리소스에 부착된 태그 딕셔너리
        metric_name: 메트릭 이름
            'CPU' | 'Memory' | 'Connections' | 'FreeMemoryGB' | 'FreeStorageGB'
            | 'RequestCount' | 'HealthyHostCount'
            | 'Disk_root' | 'Disk_data' | 'Disk_{path_key}' (Disk 계열)

    Returns:
        유효한 양의 숫자 임계치 값
    """
    # Disk 계열은 환경변수/하드코딩 폴백 시 'Disk' 기본 키 사용
    base_metric = "Disk" if metric_name.startswith("Disk_") else metric_name

    # 1단계: 태그에서 조회 (Threshold_{metric_name})
    tag_key = f"Threshold_{metric_name}"
    tag_value = resource_tags.get(tag_key)
    if tag_value is not None:
        try:
            val = float(tag_value)
            if val > 0:
                return val
            else:
                logger.warning(
                    "Invalid threshold tag %s=%r (not positive): falling back to env var",
                    tag_key, tag_value,
                )
        except (ValueError, TypeError):
            logger.warning(
                "Invalid threshold tag %s=%r (non-numeric): falling back to env var",
                tag_key, tag_value,
            )

    # 2단계: 환경 변수에서 조회 (DEFAULT_{BASE_METRIC}_THRESHOLD)
    env_key = f"DEFAULT_{base_metric.upper()}_THRESHOLD"
    env_value = os.environ.get(env_key)
    if env_value is not None:
        try:
            val = float(env_value)
            if val > 0:
                return val
            else:
                logger.warning(
                    "Invalid env var %s=%r (not positive): falling back to hardcoded default",
                    env_key, env_value,
                )
        except (ValueError, TypeError):
            logger.warning(
                "Invalid env var %s=%r (non-numeric): falling back to hardcoded default",
                env_key, env_value,
            )

    # 3단계: 시스템 하드코딩 기본값 (최종 폴백)
    default = HARDCODED_DEFAULTS.get(base_metric)
    if default is not None:
        return default

    logger.warning(
        "Unknown metric_name %r not in HARDCODED_DEFAULTS: returning 80.0",
        metric_name,
    )
    return 80.0


def get_disk_thresholds(resource_tags: dict) -> dict[str, float]:
    """
    태그에서 Threshold_Disk_* 패턴을 모두 스캔하여 {path: threshold} 딕셔너리 반환.

    예: {"Threshold_Disk_root": "85", "Threshold_Disk_data": "90"}
        → {"/": 85.0, "/data": 90.0}

    태그가 없으면 빈 딕셔너리 반환 (Collector에서 CWAgent 메트릭 skip 처리).
    """
    result = {}
    for key, value in resource_tags.items():
        if not key.startswith("Threshold_Disk_"):
            continue
        suffix = key[len("Threshold_Disk_"):]
        if not suffix:
            continue
        try:
            val = float(value)
            if val > 0:
                path = tag_suffix_to_disk_path(suffix)
                result[path] = val
            else:
                logger.warning("Invalid Disk threshold tag %s=%r (not positive): skipping", key, value)
        except (ValueError, TypeError):
            logger.warning("Invalid Disk threshold tag %s=%r (non-numeric): skipping", key, value)
    return result


def disk_path_to_tag_suffix(path: str) -> str:
    """
    경로를 태그 suffix로 변환.
    '/' → 'root', '/data' → 'data', '/var/log' → 'var_log'
    """
    if path == "/":
        return "root"
    # 선행 슬래시 제거 후 내부 슬래시를 언더스코어로
    return path.lstrip("/").replace("/", "_")


def tag_suffix_to_disk_path(suffix: str) -> str:
    """
    태그 suffix를 경로로 역변환.
    'root' → '/', 'data' → '/data', 'var_log' → '/var_log'
    참고: 언더스코어는 슬래시로 복원하지 않음 (단순 경로명 매핑)
    """
    if suffix == "root":
        return "/"
    return f"/{suffix}"


def has_monitoring_tag(resource_tags: dict) -> bool:
    """
    Monitoring=on 태그 존재 여부 반환.

    Args:
        resource_tags: 리소스에 부착된 태그 딕셔너리

    Returns:
        Monitoring=on 태그가 있으면 True, 없으면 False
    """
    return resource_tags.get("Monitoring", "").lower() == "on"


def get_resource_tags(resource_id: str, resource_type: str) -> dict:
    """
    AWS API를 통해 리소스 태그 조회.

    Args:
        resource_id: 리소스 ID
        resource_type: 리소스 유형 ('EC2' | 'RDS' | 'ELB' | 'TG')

    Returns:
        태그 딕셔너리 (키-값 쌍). API 오류 시 빈 딕셔너리 반환.
    """
    try:
        if resource_type == "EC2":
            return _get_ec2_tags(resource_id)
        elif resource_type in ("RDS", "AuroraRDS", "DocDB"):
            return _get_rds_tags(resource_id)
        elif resource_type in ("ELB", "TG", "ALB", "NLB"):
            return _get_elbv2_tags(resource_id)
        elif resource_type == "ElastiCache":
            return _get_elasticache_tags(resource_id)
        elif resource_type == "NAT":
            return _get_ec2_tags_by_resource(resource_id)
        elif resource_type == "Lambda":
            return _get_lambda_tags(resource_id)
        elif resource_type == "VPN":
            return _get_vpn_tags(resource_id)
        elif resource_type == "APIGW":
            return _get_apigw_tags(resource_id)
        elif resource_type == "ACM":
            return _get_acm_tags(resource_id)
        elif resource_type == "Backup":
            return _get_backup_tags(resource_id)
        elif resource_type == "MQ":
            return _get_mq_tags(resource_id)
        elif resource_type == "CLB":
            return _get_clb_tags(resource_id)
        elif resource_type == "OpenSearch":
            return _get_opensearch_tags(resource_id)
        elif resource_type == "SQS":
            return _get_sqs_tags(resource_id)
        elif resource_type == "ECS":
            return _get_ecs_tags(resource_id)
        elif resource_type == "MSK":
            return _get_msk_tags(resource_id)
        elif resource_type == "DynamoDB":
            return _get_dynamodb_tags(resource_id)
        elif resource_type == "CloudFront":
            return _get_cloudfront_tags(resource_id)
        elif resource_type == "WAF":
            return _get_waf_tags(resource_id)
        elif resource_type == "Route53":
            return _get_route53_tags(resource_id)
        elif resource_type == "DX":
            return _get_dx_tags(resource_id)
        elif resource_type == "EFS":
            return _get_efs_tags(resource_id)
        elif resource_type == "S3":
            return _get_s3_tags(resource_id)
        elif resource_type == "SageMaker":
            return _get_sagemaker_tags(resource_id)
        elif resource_type == "SNS":
            return _get_sns_tags(resource_id)
        else:
            logger.warning("Unsupported resource_type %r for resource %s", resource_type, resource_id)
            return {}
    except ClientError as e:
        logger.error(
            "AWS API error fetching tags for %s (%s): %s",
            resource_id, resource_type, e,
        )
        return {}
    except Exception as e:
        logger.error(
            "Unexpected error fetching tags for %s (%s): %s",
            resource_id, resource_type, e,
        )
        return {}


@functools.lru_cache(maxsize=None)
def _get_ec2_client():
    return boto3.client("ec2")


@functools.lru_cache(maxsize=None)
def _get_rds_client():
    return boto3.client("rds")


@functools.lru_cache(maxsize=None)
def _get_elbv2_client():
    return boto3.client("elbv2")


def _get_ec2_tags(instance_id: str) -> dict:
    """EC2 인스턴스 태그 조회"""
    ec2 = _get_ec2_client()
    response = ec2.describe_instances(InstanceIds=[instance_id])
    reservations = response.get("Reservations", [])
    if not reservations:
        return {}
    instances = reservations[0].get("Instances", [])
    if not instances:
        return {}
    raw_tags = instances[0].get("Tags", [])
    return {tag["Key"]: tag["Value"] for tag in raw_tags}


def _get_rds_tags(db_instance_id: str) -> dict:
    """RDS DB 인스턴스 태그 조회"""
    rds = _get_rds_client()
    response = rds.describe_db_instances(DBInstanceIdentifier=db_instance_id)
    db_instances = response.get("DBInstances", [])
    if not db_instances:
        return {}
    db_arn = db_instances[0].get("DBInstanceArn", "")
    if not db_arn:
        return {}
    tag_response = rds.list_tags_for_resource(ResourceName=db_arn)
    raw_tags = tag_response.get("TagList", [])
    return {tag["Key"]: tag["Value"] for tag in raw_tags}


def _get_elbv2_tags(resource_arn: str) -> dict:
    """ALB / TargetGroup 태그 조회 (ELBv2 공통)"""
    elbv2 = _get_elbv2_client()
    response = elbv2.describe_tags(ResourceArns=[resource_arn])
    tag_descriptions = response.get("TagDescriptions", [])
    if not tag_descriptions:
        return {}
    raw_tags = tag_descriptions[0].get("Tags", [])
    return {tag["Key"]: tag["Value"] for tag in raw_tags}


@functools.lru_cache(maxsize=None)
def _get_elasticache_client():
    return boto3.client("elasticache")


def _get_elasticache_tags(resource_id: str) -> dict:
    """ElastiCache 클러스터 태그 조회.

    describe_cache_clusters로 ARN을 얻은 뒤 list_tags_for_resource 호출.
    """
    client = _get_elasticache_client()
    resp = client.describe_cache_clusters(CacheClusterId=resource_id)
    clusters = resp.get("CacheClusters", [])
    if not clusters:
        return {}
    arn = clusters[0].get("ARN", "")
    if not arn:
        return {}
    tag_resp = client.list_tags_for_resource(ResourceName=arn)
    return {t["Key"]: t["Value"] for t in tag_resp.get("TagList", [])}


def _get_ec2_tags_by_resource(resource_id: str) -> dict:
    """EC2 describe_tags로 리소스 ID 기반 태그 조회 (NAT Gateway 등)."""
    ec2 = _get_ec2_client()
    resp = ec2.describe_tags(
        Filters=[{"Name": "resource-id", "Values": [resource_id]}]
    )
    return {t["Key"]: t["Value"] for t in resp.get("Tags", [])}


# ──────────────────────────────────────────────
# 신규 리소스 태그 조회 헬퍼 (코딩 거버넌스 §1)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_lambda_client():
    return boto3.client("lambda")


@functools.lru_cache(maxsize=None)
def _get_apigw_client():
    return boto3.client("apigateway")


@functools.lru_cache(maxsize=None)
def _get_apigwv2_client():
    return boto3.client("apigatewayv2")


@functools.lru_cache(maxsize=None)
def _get_acm_client():
    return boto3.client("acm")


@functools.lru_cache(maxsize=None)
def _get_backup_client():
    return boto3.client("backup")


@functools.lru_cache(maxsize=None)
def _get_mq_client():
    return boto3.client("mq")


@functools.lru_cache(maxsize=None)
def _get_classic_elb_client():
    return boto3.client("elb")


@functools.lru_cache(maxsize=None)
def _get_opensearch_client():
    return boto3.client("opensearch")


def _get_lambda_tags(function_name: str) -> dict:
    """Lambda 함수 태그 조회. get_function으로 ARN 획득 후 list_tags."""
    client = _get_lambda_client()
    resp = client.get_function(FunctionName=function_name)
    arn = resp.get("Configuration", {}).get("FunctionArn", "")
    if not arn:
        return {}
    tag_resp = client.list_tags(Resource=arn)
    return tag_resp.get("Tags", {})


def _get_vpn_tags(vpn_id: str) -> dict:
    """VPN Connection 태그 조회. EC2 describe_vpn_connections."""
    ec2 = _get_ec2_client()
    resp = ec2.describe_vpn_connections(VpnConnectionIds=[vpn_id])
    vpns = resp.get("VpnConnections", [])
    if not vpns:
        return {}
    return {t["Key"]: t["Value"] for t in vpns[0].get("Tags", [])}


def _get_apigw_tags(resource_id: str) -> dict:
    """APIGW 태그 조회. REST API (apigateway) 또는 v2 API (apigatewayv2) 시도."""
    # v2 API 먼저 시도 (ApiId로 조회)
    try:
        v2 = _get_apigwv2_client()
        resp = v2.get_api(ApiId=resource_id)
        return resp.get("Tags", {})
    except ClientError:
        pass
    # REST API 폴백 (이름 기반이므로 get_rest_apis로 검색)
    try:
        client = _get_apigw_client()
        paginator = client.get_paginator("get_rest_apis")
        for page in paginator.paginate():
            for api in page.get("items", []):
                if api.get("name") == resource_id:
                    region = boto3.session.Session().region_name or "us-east-1"
                    arn = f"arn:aws:apigateway:{region}::/restapis/{api['id']}"
                    tag_resp = client.get_tags(resourceArn=arn)
                    return tag_resp.get("tags", {})
    except ClientError as e:
        logger.error("APIGW get_tags failed for %s: %s", resource_id, e)
    return {}


def _get_acm_tags(certificate_arn: str) -> dict:
    """ACM 인증서 태그 조회."""
    client = _get_acm_client()
    resp = client.list_tags_for_certificate(CertificateArn=certificate_arn)
    return {t["Key"]: t["Value"] for t in resp.get("Tags", [])}


def _get_backup_tags(vault_name: str) -> dict:
    """Backup Vault 태그 조회."""
    client = _get_backup_client()
    resp = client.describe_backup_vault(BackupVaultName=vault_name)
    vault_arn = resp.get("BackupVaultArn", "")
    if not vault_arn:
        return {}
    tag_resp = client.list_tags(ResourceArn=vault_arn)
    return tag_resp.get("Tags", {})


def _get_mq_tags(broker_name: str) -> dict:
    """MQ Broker 태그 조회. list_brokers로 ID 획득 후 describe_broker."""
    client = _get_mq_client()
    paginator = client.get_paginator("list_brokers")
    for page in paginator.paginate():
        for b in page.get("BrokerSummaries", []):
            if b["BrokerName"] == broker_name:
                resp = client.describe_broker(BrokerId=b["BrokerId"])
                return resp.get("Tags", {})
    return {}


def _get_clb_tags(lb_name: str) -> dict:
    """Classic Load Balancer 태그 조회."""
    client = _get_classic_elb_client()
    resp = client.describe_tags(LoadBalancerNames=[lb_name])
    descriptions = resp.get("TagDescriptions", [])
    if not descriptions:
        return {}
    return {t["Key"]: t["Value"] for t in descriptions[0].get("Tags", [])}


def _get_opensearch_tags(domain_name: str) -> dict:
    """OpenSearch 도메인 태그 조회."""
    client = _get_opensearch_client()
    resp = client.describe_domains(DomainNames=[domain_name])
    domains = resp.get("DomainStatusList", [])
    if not domains:
        return {}
    domain_arn = domains[0].get("ARN", "")
    if not domain_arn:
        return {}
    tag_resp = client.list_tags(ARN=domain_arn)
    return {t["Key"]: t["Value"] for t in tag_resp.get("TagList", [])}


# ──────────────────────────────────────────────
# 12개 신규 리소스 태그 조회 헬퍼 (Task 7)
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_sqs_client():
    return boto3.client("sqs")


@functools.lru_cache(maxsize=None)
def _get_ecs_client():
    return boto3.client("ecs")


@functools.lru_cache(maxsize=None)
def _get_kafka_client():
    return boto3.client("kafka")


@functools.lru_cache(maxsize=None)
def _get_dynamodb_client():
    return boto3.client("dynamodb")


@functools.lru_cache(maxsize=None)
def _get_cloudfront_client():
    return boto3.client("cloudfront")


@functools.lru_cache(maxsize=None)
def _get_wafv2_client():
    return boto3.client("wafv2")


@functools.lru_cache(maxsize=None)
def _get_route53_client():
    return boto3.client("route53")


@functools.lru_cache(maxsize=None)
def _get_dx_client():
    return boto3.client("directconnect")


@functools.lru_cache(maxsize=None)
def _get_efs_client():
    return boto3.client("efs")


@functools.lru_cache(maxsize=None)
def _get_s3_client():
    return boto3.client("s3")


@functools.lru_cache(maxsize=None)
def _get_sagemaker_client():
    return boto3.client("sagemaker")


@functools.lru_cache(maxsize=None)
def _get_sns_client():
    return boto3.client("sns")


def _get_sqs_tags(queue_url: str) -> dict:
    """SQS 큐 태그 조회. QueueUrl 기반."""
    client = _get_sqs_client()
    resp = client.list_queue_tags(QueueUrl=queue_url)
    return resp.get("Tags", {})


def _get_ecs_tags(resource_arn: str) -> dict:
    """ECS 서비스/클러스터 태그 조회."""
    client = _get_ecs_client()
    resp = client.list_tags_for_resource(resourceArn=resource_arn)
    return {t["key"]: t["value"] for t in resp.get("tags", [])}


def _get_msk_tags(resource_arn: str) -> dict:
    """MSK 클러스터 태그 조회."""
    client = _get_kafka_client()
    resp = client.list_tags_for_resource(ResourceArn=resource_arn)
    return resp.get("Tags", {})


def _get_dynamodb_tags(resource_arn: str) -> dict:
    """DynamoDB 테이블 태그 조회."""
    client = _get_dynamodb_client()
    resp = client.list_tags_of_resource(ResourceArn=resource_arn)
    return {t["Key"]: t["Value"] for t in resp.get("Tags", [])}


def _get_cloudfront_tags(resource_arn: str) -> dict:
    """CloudFront 배포 태그 조회."""
    client = _get_cloudfront_client()
    resp = client.list_tags_for_resource(Resource=resource_arn)
    items = resp.get("Tags", {}).get("Items", [])
    return {t["Key"]: t["Value"] for t in items}


def _get_waf_tags(resource_arn: str) -> dict:
    """WAF WebACL 태그 조회."""
    client = _get_wafv2_client()
    resp = client.list_tags_for_resource(ResourceARN=resource_arn)
    tag_info = resp.get("TagInfoForResource", {})
    return {t["Key"]: t["Value"] for t in tag_info.get("TagList", [])}


def _get_route53_tags(health_check_id: str) -> dict:
    """Route53 Health Check 태그 조회."""
    client = _get_route53_client()
    resp = client.list_tags_for_resource(
        ResourceType="healthcheck", ResourceId=health_check_id
    )
    resource_tag_set = resp.get("ResourceTagSet", {})
    return {t["Key"]: t["Value"] for t in resource_tag_set.get("Tags", [])}


def _get_dx_tags(resource_arn: str) -> dict:
    """Direct Connect 연결 태그 조회. DX는 소문자 key/value 사용."""
    client = _get_dx_client()
    resp = client.describe_tags(resourceArns=[resource_arn])
    tags_list = resp.get("resourceTags", [])
    if not tags_list:
        return {}
    return {t["key"]: t["value"] for t in tags_list[0].get("tags", [])}


def _get_efs_tags(file_system_id: str) -> dict:
    """EFS 파일 시스템 태그 조회. describe_file_systems의 Tags 필드 사용."""
    client = _get_efs_client()
    resp = client.describe_file_systems(FileSystemId=file_system_id)
    file_systems = resp.get("FileSystems", [])
    if not file_systems:
        return {}
    return {t["Key"]: t["Value"] for t in file_systems[0].get("Tags", [])}


def _get_s3_tags(bucket_name: str) -> dict:
    """S3 버킷 태그 조회."""
    client = _get_s3_client()
    resp = client.get_bucket_tagging(Bucket=bucket_name)
    return {t["Key"]: t["Value"] for t in resp.get("TagSet", [])}


def _get_sagemaker_tags(resource_arn: str) -> dict:
    """SageMaker 엔드포인트 태그 조회."""
    client = _get_sagemaker_client()
    resp = client.list_tags(ResourceArn=resource_arn)
    return {t["Key"]: t["Value"] for t in resp.get("Tags", [])}


def _get_sns_tags(resource_arn: str) -> dict:
    """SNS 토픽 태그 조회."""
    client = _get_sns_client()
    resp = client.list_tags_for_resource(ResourceArn=resource_arn)
    return {t["Key"]: t["Value"] for t in resp.get("Tags", [])}
