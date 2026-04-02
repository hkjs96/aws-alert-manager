"""
Remediation_Handler Lambda Handler

Requirements: 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4, 8.1~8.7, 6.3, 6.4

CloudTrail 이벤트를 수신하여:
- MODIFY  → Auto-Remediation (EC2 stop / RDS stop / ELB delete)
- DELETE  → Monitoring=on 태그 있으면 lifecycle SNS 알림
- TAG_CHANGE → Monitoring 태그 추가/제거 처리
"""

import logging
from dataclasses import dataclass
from typing import Optional

import boto3

from botocore.exceptions import ClientError

from common import MONITORED_API_EVENTS
from common.alarm_manager import (
    create_alarms_for_resource,
    delete_alarms_for_resource,
    sync_alarms_for_resource,
)
from common.sns_notifier import (
    send_error_alert,
    send_lifecycle_alert,
    send_remediation_alert,
)
from common.tag_resolver import get_resource_tags, has_monitoring_tag

# Lambda 환경에서 root logger 레벨 설정 (모든 모듈에 적용)
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)



# ──────────────────────────────────────────────

# 데이터 클래스

# ──────────────────────────────────────────────


@dataclass

class ParsedEvent:

    resource_id: str

    resource_type: str          # "EC2" | "RDS" | "ELB"

    event_name: str             # 원본 API 이름

    event_category: str         # "MODIFY" | "DELETE" | "TAG_CHANGE"

    change_summary: str         # 사람이 읽을 수 있는 변경 요약

    request_params: dict        # CloudTrail requestParameters

    _is_rds_fallback: bool = False  # RDS/Aurora 판별 실패 시 True (KI-008)



# ──────────────────────────────────────────────

# API → (resource_type, id_extractor) 매핑

# ──────────────────────────────────────────────


def _extract_ec2_instance_ids(params: dict) -> list[str]:
    """TerminateInstances / ModifyInstance: instancesSet에서 모든 ID 추출."""
    ids = params.get("instancesSet", {}).get("items", [])
    if ids:
        return [item.get("instanceId") for item in ids if item.get("instanceId")]
    single = params.get("instanceId")
    return [single] if single else []



def _extract_rds_ids(params: dict) -> list[str]:
    rid = params.get("dBInstanceIdentifier")
    return [rid] if rid else []



def _extract_elb_ids(params: dict) -> list[str]:
    rid = params.get("loadBalancerArn") or params.get("loadBalancerName")
    return [rid] if rid else []


def _extract_tg_ids(params: dict) -> list[str]:
    rid = params.get("targetGroupArn")
    return [rid] if rid else []


def _extract_run_instances_ids(resp: dict) -> list[str]:
    """RunInstances: responseElements.instancesSet.items[].instanceId"""
    items = resp.get("instancesSet", {}).get("items", [])
    return [item.get("instanceId") for item in items if item.get("instanceId")]


def _extract_create_db_ids(params: dict) -> list[str]:
    """CreateDBInstance: requestParameters.dBInstanceIdentifier"""
    rid = params.get("dBInstanceIdentifier")
    return [rid] if rid else []


def _extract_create_lb_ids(resp: dict) -> list[str]:
    """CreateLoadBalancer: responseElements.loadBalancers[].loadBalancerArn"""
    lbs = resp.get("loadBalancers", [])
    return [lb.get("loadBalancerArn") for lb in lbs if lb.get("loadBalancerArn")]


def _extract_create_tg_ids(resp: dict) -> list[str]:
    """CreateTargetGroup: responseElements.targetGroups[].targetGroupArn"""
    tgs = resp.get("targetGroups", [])
    return [tg.get("targetGroupArn") for tg in tgs if tg.get("targetGroupArn")]



def _extract_elasticache_ids(params: dict) -> list[str]:
    """CreateCacheCluster / DeleteCacheCluster / ModifyCacheCluster: cacheClusterId 추출."""
    rid = params.get("cacheClusterId")
    return [rid] if rid else []


def _extract_natgw_ids(params: dict) -> list[str]:
    """DeleteNatGateway: natGatewayId 추출."""
    rid = params.get("natGatewayId")
    return [rid] if rid else []


def _extract_natgw_create_ids(resp: dict) -> list[str]:
    """CreateNatGateway: responseElements.natGateway.natGatewayId 추출."""
    natgw = resp.get("natGateway", {})
    rid = natgw.get("natGatewayId")
    return [rid] if rid else []


def _extract_tag_resource_ids(params: dict) -> list[str]:
    """CreateTags / DeleteTags: resourcesSet 또는 resourceIdList 전체."""
    items = params.get("resourcesSet", {}).get("items", [])
    if items:
        return [item.get("resourceId") for item in items if item.get("resourceId")]
    lst = params.get("resourceIdList", [])
    return [rid for rid in lst if rid]



def _extract_rds_tag_resource_ids(params: dict) -> list[str]:
    """AddTagsToResource / RemoveTagsFromResource: resourceName에서 DB identifier 추출.
    resourceName은 ARN 형태: arn:aws:rds:region:account:db:my-db-id"""
    arn = params.get("resourceName", "")
    if ":db:" in arn:
        return [arn.split(":db:")[-1]]
    return [arn] if arn else []



def _extract_elb_tag_resource_ids(params: dict) -> list[str]:
    """AddTags / RemoveTags: resourceArns 전체."""
    arns = params.get("resourceArns", [])
    return [arn for arn in arns if arn]


# ──────────────────────────────────────────────
# 신규 리소스 ID 추출 함수
# ──────────────────────────────────────────────

def _extract_lambda_create_ids(resp: dict) -> list[str]:
    """CreateFunction: responseElements.functionName 추출."""
    rid = resp.get("functionName")
    return [rid] if rid else []


def _extract_lambda_ids(params: dict) -> list[str]:
    """DeleteFunction: requestParameters.functionName 추출."""
    rid = params.get("functionName")
    return [rid] if rid else []


def _extract_vpn_ids(params: dict) -> list[str]:
    """DeleteVpnConnection: vpnConnectionId 추출."""
    rid = params.get("vpnConnectionId")
    return [rid] if rid else []


def _extract_apigw_rest_create_ids(resp: dict) -> list[str]:
    """CreateRestApi: responseElements.name 추출."""
    rid = resp.get("name")
    return [rid] if rid else []


def _extract_apigw_rest_ids(params: dict) -> list[str]:
    """DeleteRestApi: restApiId 추출."""
    rid = params.get("restApiId")
    return [rid] if rid else []


def _extract_apigw_v2_create_ids(resp: dict) -> list[str]:
    """CreateApi (v2): responseElements.apiId 추출."""
    rid = resp.get("apiId")
    return [rid] if rid else []


def _extract_apigw_v2_ids(params: dict) -> list[str]:
    """DeleteApi (v2): apiId 추출."""
    rid = params.get("apiId")
    return [rid] if rid else []


def _extract_acm_ids(params: dict) -> list[str]:
    """DeleteCertificate: certificateArn 추출."""
    rid = params.get("certificateArn")
    return [rid] if rid else []


def _extract_backup_vault_ids(params: dict) -> list[str]:
    """CreateBackupVault / DeleteBackupVault: backupVaultName 추출."""
    rid = params.get("backupVaultName")
    return [rid] if rid else []


def _extract_mq_create_ids(resp: dict) -> list[str]:
    """CreateBroker: responseElements.brokerName 추출."""
    rid = resp.get("brokerName")
    return [rid] if rid else []


def _extract_mq_ids(params: dict) -> list[str]:
    """DeleteBroker: brokerId 추출."""
    rid = params.get("brokerId")
    return [rid] if rid else []


def _extract_opensearch_ids(params: dict) -> list[str]:
    """CreateDomain / DeleteDomain: domainName 추출."""
    rid = params.get("domainName")
    return [rid] if rid else []


def _extract_tag_resource_arn(params: dict) -> list[str]:
    """TagResource / UntagResource: resourceArn 추출 (Lambda, APIGW, ACM, Backup, MQ, OpenSearch 공통)."""
    rid = params.get("resourceArn") or params.get("resourceARN") or params.get("resource")
    return [rid] if rid else []


# ──────────────────────────────────────────────
# 12개 신규 리소스 ID 추출 함수
# ──────────────────────────────────────────────

def _extract_sqs_queue_name(params: dict) -> list[str]:
    """SQS CreateQueue/DeleteQueue/TagQueue/UntagQueue: queueUrl에서 큐 이름 추출."""
    url = params.get("queueUrl", "")
    if url:
        return [url.rstrip("/").split("/")[-1]]
    return []


def _extract_ecs_service_ids(params: dict) -> list[str]:
    """ECS CreateService/DeleteService: serviceName 추출."""
    rid = params.get("serviceName")
    return [rid] if rid else []


def _extract_msk_cluster_ids(params: dict) -> list[str]:
    """MSK CreateCluster/DeleteCluster: clusterName 추출."""
    rid = params.get("clusterName")
    return [rid] if rid else []


def _extract_dynamodb_table_ids(params: dict) -> list[str]:
    """DynamoDB CreateTable/DeleteTable: tableName 추출."""
    rid = params.get("tableName")
    return [rid] if rid else []


def _extract_cloudfront_create_ids(resp: dict) -> list[str]:
    """CreateDistribution: responseElements.distribution.id 추출."""
    dist = resp.get("distribution", {})
    rid = dist.get("id")
    return [rid] if rid else []


def _extract_cloudfront_delete_ids(params: dict) -> list[str]:
    """DeleteDistribution: requestParameters.id 추출."""
    rid = params.get("id")
    return [rid] if rid else []


def _extract_waf_create_ids(resp: dict) -> list[str]:
    """CreateWebACL: responseElements.summary.name 추출."""
    summary = resp.get("summary", {})
    rid = summary.get("name")
    return [rid] if rid else []


def _extract_waf_delete_ids(params: dict) -> list[str]:
    """DeleteWebACL: requestParameters.name 추출."""
    rid = params.get("name")
    return [rid] if rid else []


def _extract_route53_create_ids(resp: dict) -> list[str]:
    """CreateHealthCheck: responseElements.healthCheck.id 추출."""
    hc = resp.get("healthCheck", {})
    rid = hc.get("id")
    return [rid] if rid else []


def _extract_route53_delete_ids(params: dict) -> list[str]:
    """DeleteHealthCheck: requestParameters.healthCheckId 추출."""
    rid = params.get("healthCheckId")
    return [rid] if rid else []


def _extract_dx_connection_ids(params: dict) -> list[str]:
    """DX CreateConnection/DeleteConnection: connectionId 추출."""
    rid = params.get("connectionId")
    return [rid] if rid else []


def _extract_efs_file_system_ids(params: dict) -> list[str]:
    """EFS CreateFileSystem/DeleteFileSystem: fileSystemId 추출."""
    rid = params.get("fileSystemId")
    return [rid] if rid else []


def _extract_s3_bucket_ids(params: dict) -> list[str]:
    """S3 CreateBucket/DeleteBucket: bucketName 추출."""
    rid = params.get("bucketName")
    return [rid] if rid else []


def _extract_sagemaker_endpoint_ids(params: dict) -> list[str]:
    """SageMaker CreateEndpoint/DeleteEndpoint: endpointName 추출."""
    rid = params.get("endpointName")
    return [rid] if rid else []


def _extract_sns_topic_ids(params: dict) -> list[str]:
    """SNS CreateTopic/DeleteTopic: topicArn에서 토픽 이름 추출."""
    arn = params.get("topicArn", "")
    if arn:
        return [arn.split(":")[-1]]
    return []



_API_MAP: dict[str, tuple[str, callable]] = {

    # MODIFY

    "ModifyInstanceAttribute":      ("EC2", _extract_ec2_instance_ids),

    "ModifyInstanceType":           ("EC2", _extract_ec2_instance_ids),

    "ModifyDBInstance":             ("RDS", _extract_rds_ids),

    "ModifyLoadBalancerAttributes": ("ELB", _extract_elb_ids),

    "ModifyListener":               ("ELB", _extract_elb_ids),

    "ModifyCacheCluster":           ("ElastiCache", _extract_elasticache_ids),

    # DELETE

    "TerminateInstances":           ("EC2", _extract_ec2_instance_ids),

    "DeleteDBInstance":             ("RDS", _extract_rds_ids),

    "DeleteLoadBalancer":           ("ELB", _extract_elb_ids),
    "DeleteTargetGroup":            ("TG",  _extract_tg_ids),

    "DeleteCacheCluster":           ("ElastiCache", _extract_elasticache_ids),

    "DeleteNatGateway":             ("NAT", _extract_natgw_ids),

    # CREATE

    "RunInstances":                 ("EC2", _extract_run_instances_ids),

    "CreateDBInstance":             ("RDS", _extract_create_db_ids),

    "CreateLoadBalancer":           ("ELB", _extract_create_lb_ids),

    "CreateTargetGroup":            ("TG",  _extract_create_tg_ids),

    "CreateCacheCluster":           ("ElastiCache", _extract_elasticache_ids),

    "CreateNatGateway":             ("NAT", _extract_natgw_create_ids),

    # CREATE (신규 리소스)
    "CreateFunction20150331":       ("Lambda", _extract_lambda_create_ids),
    "CreateRestApi":                ("APIGW", _extract_apigw_rest_create_ids),
    "CreateApi":                    ("APIGW", _extract_apigw_v2_create_ids),
    "CreateBackupVault":            ("Backup", _extract_backup_vault_ids),
    "CreateBroker":                 ("MQ", _extract_mq_create_ids),
    "CreateDomain":                 ("OpenSearch", _extract_opensearch_ids),

    # DELETE (신규 리소스)
    "DeleteFunction20150331":       ("Lambda", _extract_lambda_ids),
    "DeleteVpnConnection":          ("VPN", _extract_vpn_ids),
    "DeleteRestApi":                ("APIGW", _extract_apigw_rest_ids),
    "DeleteApi":                    ("APIGW", _extract_apigw_v2_ids),
    "DeleteCertificate":            ("ACM", _extract_acm_ids),
    "DeleteBackupVault":            ("Backup", _extract_backup_vault_ids),
    "DeleteBroker":                 ("MQ", _extract_mq_ids),
    "DeleteDomain":                 ("OpenSearch", _extract_opensearch_ids),

    # TAG_CHANGE

    "CreateTags":                   ("EC2", _extract_tag_resource_ids),

    "DeleteTags":                   ("EC2", _extract_tag_resource_ids),

    "AddTagsToResource":            ("RDS", _extract_rds_tag_resource_ids),

    "RemoveTagsFromResource":       ("RDS", _extract_rds_tag_resource_ids),

    "AddTags":                      ("ELB", _extract_elb_tag_resource_ids),

    "RemoveTags":                   ("ELB", _extract_elb_tag_resource_ids),

    # TAG_CHANGE (신규 리소스 공통)
    "TagResource":                  ("MULTI", _extract_tag_resource_arn),
    "UntagResource":                ("MULTI", _extract_tag_resource_arn),

    # SQS 전용 태그 이벤트
    "TagQueue":                     ("SQS", _extract_sqs_queue_name),
    "UntagQueue":                   ("SQS", _extract_sqs_queue_name),

    # CREATE (12개 신규 리소스)
    "CreateQueue":                  ("SQS", _extract_sqs_queue_name),
    "CreateService":                ("ECS", _extract_ecs_service_ids),
    "CreateCluster":                ("MSK", _extract_msk_cluster_ids),
    "CreateTable":                  ("DynamoDB", _extract_dynamodb_table_ids),
    "CreateDistribution":           ("CloudFront", _extract_cloudfront_create_ids),
    "CreateWebACL":                 ("WAF", _extract_waf_create_ids),
    "CreateHealthCheck":            ("Route53", _extract_route53_create_ids),
    "CreateConnection":             ("DX", _extract_dx_connection_ids),
    "CreateFileSystem":             ("EFS", _extract_efs_file_system_ids),
    "CreateBucket":                 ("S3", _extract_s3_bucket_ids),
    "CreateEndpoint":               ("SageMaker", _extract_sagemaker_endpoint_ids),
    "CreateTopic":                  ("SNS", _extract_sns_topic_ids),

    # DELETE (12개 신규 리소스)
    "DeleteQueue":                  ("SQS", _extract_sqs_queue_name),
    "DeleteService":                ("ECS", _extract_ecs_service_ids),
    "DeleteCluster":                ("MSK", _extract_msk_cluster_ids),
    "DeleteTable":                  ("DynamoDB", _extract_dynamodb_table_ids),
    "DeleteDistribution":           ("CloudFront", _extract_cloudfront_delete_ids),
    "DeleteWebACL":                 ("WAF", _extract_waf_delete_ids),
    "DeleteHealthCheck":            ("Route53", _extract_route53_delete_ids),
    "DeleteConnection":             ("DX", _extract_dx_connection_ids),
    "DeleteFileSystem":             ("EFS", _extract_efs_file_system_ids),
    "DeleteBucket":                 ("S3", _extract_s3_bucket_ids),
    "DeleteEndpoint":               ("SageMaker", _extract_sagemaker_endpoint_ids),
    "DeleteTopic":                  ("SNS", _extract_sns_topic_ids),

}



def _get_event_category(event_name: str) -> Optional[str]:

    for category, names in MONITORED_API_EVENTS.items():

        if event_name in names:

            return category

    return None



# ──────────────────────────────────────────────

# 핸들러 진입점

# ──────────────────────────────────────────────


def lambda_handler(event, context):
    """

    Lambda 핸들러 진입점.


    EventBridge를 통해 CloudTrail 이벤트를 수신.

    파싱 오류 시 로그 + SNS 오류 알림 발송 후 정상 종료.
    """

    try:

        parsed_events = parse_cloudtrail_event(event)

    except Exception as e:

        logger.error("Failed to parse CloudTrail event: %s | event=%s", e, event)

        send_error_alert(context="parse_cloudtrail_event", error=e)

        return {"status": "parse_error"}

    has_error = False
    for parsed in parsed_events:
        logger.info(
            "Received %s event: resource=%s (%s) category=%s | request_params=%s",
            parsed.event_name, parsed.resource_id, parsed.resource_type, parsed.event_category,
            str(parsed.request_params)[:500],
        )


        try:

            if parsed.event_category == "MODIFY":

                _handle_modify(parsed)

            elif parsed.event_category == "DELETE":

                _handle_delete(parsed)

            elif parsed.event_category == "TAG_CHANGE":

                _handle_tag_change(parsed)

            elif parsed.event_category == "CREATE":

                _handle_create(parsed)

            else:

                logger.warning("Unknown event_category: %s", parsed.event_category)

        except Exception as e:

            # 에러 기록 후 다음 리소스 처리 계속

            logger.error(

                "Unhandled error processing event %s for %s: %s",

                parsed.event_name, parsed.resource_id, e,

            )
            has_error = True


    return {"status": "error" if has_error else "ok"}



# ──────────────────────────────────────────────

# 이벤트 파싱

# ──────────────────────────────────────────────


def _resolve_elb_type(resource_id: str) -> str:
    """ELB ARN에서 ALB/NLB 타입을 판별. 판별 불가 시 'ELB' 폴백."""
    if "/app/" in resource_id:
        return "ALB"
    if "/net/" in resource_id:
        return "NLB"
    return "ELB"


def _resolve_multi_tag_type(resource_arn: str) -> str:
    """TagResource/UntagResource ARN에서 서비스 타입 판별.

    ARN 패턴:
    - arn:aws:lambda:... → Lambda
    - arn:aws:apigateway:... → APIGW
    - arn:aws:acm:... → ACM
    - arn:aws:backup:... → Backup
    - arn:aws:mq:... → MQ
    - arn:aws:es:... → OpenSearch
    """
    _ARN_SERVICE_MAP = {
        ":lambda:": "Lambda",
        ":apigateway:": "APIGW",
        ":acm:": "ACM",
        ":backup:": "Backup",
        ":mq:": "MQ",
        ":es:": "OpenSearch",
        ":ecs:": "ECS",
        ":kafka:": "MSK",
        ":dynamodb:": "DynamoDB",
        ":cloudfront:": "CloudFront",
        ":wafv2:": "WAF",
        ":route53:": "Route53",
        ":directconnect:": "DX",
        ":elasticfilesystem:": "EFS",
        ":s3:": "S3",
        ":sagemaker:": "SageMaker",
        ":sns:": "SNS",
    }
    for pattern, rtype in _ARN_SERVICE_MAP.items():
        if pattern in resource_arn:
            return rtype
    logger.warning("Cannot resolve MULTI tag type from ARN: %s", resource_arn)
    return "UNKNOWN"


def _resolve_rds_aurora_type(db_instance_id: str) -> tuple[str, bool]:
    """describe_db_instances로 Engine 확인 후 AuroraRDS/RDS 판별.

    Returns:
        (resource_type, is_fallback) 튜플.
        성공 시 ("AuroraRDS", False) 또는 ("RDS", False).
        API 오류 시 ("RDS", True) 폴백.
    """
    try:
        rds = boto3.client("rds")
        resp = rds.describe_db_instances(DBInstanceIdentifier=db_instance_id)
        engine = resp["DBInstances"][0].get("Engine", "")
        if engine.lower() == "docdb":
            return ("DocDB", False)
        if "aurora" in engine.lower():
            return ("AuroraRDS", False)
        return ("RDS", False)
    except ClientError as e:
        logger.warning(
            "Failed to resolve RDS/Aurora type for %s: %s (fallback to RDS)",
            db_instance_id, e,
        )
        return ("RDS", True)


def parse_cloudtrail_event(event: dict) -> list[ParsedEvent]:
    """
    EventBridge 래핑 CloudTrail 이벤트에서 필요한 필드 추출.

    하나의 CloudTrail 이벤트가 여러 리소스를 포함할 수 있으므로
    (예: TerminateInstances로 EC2 여러 대 동시 삭제)
    ParsedEvent 리스트를 반환한다.

    Raises:
        ValueError: 필수 필드 누락 또는 지원하지 않는 API
    """
    detail = event.get("detail", {})
    event_name = detail.get("eventName")
    if not event_name:
        raise ValueError("Missing eventName in CloudTrail event detail")

    request_params = detail.get("requestParameters") or {}

    if event_name not in _API_MAP:
        raise ValueError(f"Unsupported eventName: {event_name!r}")

    resource_type, ids_extractor = _API_MAP[event_name]

    # CREATE 이벤트: responseElements에서 ID 추출 (일부 이벤트는 requestParameters 사용)
    event_category = _get_event_category(event_name)
    _CREATE_FROM_REQUEST_PARAMS = (
        "CreateDBInstance", "CreateCacheCluster",
        "CreateService", "CreateCluster", "CreateTable",
        "CreateBucket", "CreateEndpoint",
    )
    if event_category == "CREATE" and event_name not in _CREATE_FROM_REQUEST_PARAMS:
        extract_source = detail.get("responseElements") or {}
    else:
        extract_source = request_params

    resource_ids = ids_extractor(extract_source)

    if not resource_ids:
        raise ValueError(
            f"Cannot extract resource_id for {event_name}: params={extract_source}"
        )

    if not event_category:
        raise ValueError(f"Cannot determine event_category for {event_name!r}")

    results: list[ParsedEvent] = []
    for resource_id in resource_ids:
        rt = resource_type
        is_rds_fallback = False
        # ELB ARN 기반 ALB/NLB 타입 세분화
        if rt == "ELB":
            rt = _resolve_elb_type(resource_id)
        # RDS → AuroraRDS 세분화 (describe_db_instances Engine 확인)
        elif rt == "RDS":
            rt, is_rds_fallback = _resolve_rds_aurora_type(resource_id)
        # MULTI: TagResource/UntagResource ARN 기반 서비스 판별
        elif rt == "MULTI":
            rt = _resolve_multi_tag_type(resource_id)

        change_summary = (
            f"{event_name} on {rt} {resource_id}"
            f" (params: {_summarize_params(request_params)})"
        )
        results.append(ParsedEvent(
            resource_id=resource_id,
            resource_type=rt,
            event_name=event_name,
            event_category=event_category,
            change_summary=change_summary,
            request_params=request_params,
            _is_rds_fallback=is_rds_fallback,
        ))

    return results




def _summarize_params(params: dict) -> str:

    """requestParameters를 간략하게 요약 (최대 200자)."""

    summary = str(params)

    return summary[:200] + "..." if len(summary) > 200 else summary



# ──────────────────────────────────────────────

# MODIFY 처리 → Auto-Remediation

# ──────────────────────────────────────────────


def _handle_modify(parsed: ParsedEvent) -> None:
    """

    MODIFY 이벤트: Monitoring=on 태그 있는 리소스에 대해 remediation 수행.

    Requirements: 4.2, 4.3, 5.1~5.4
    """

    tags = get_resource_tags(parsed.resource_id, parsed.resource_type)

    if tags.get("Monitoring", "").lower() != "on":

        logger.info(

            "Skipping remediation for %s %s: no Monitoring=on tag",

            parsed.resource_type, parsed.resource_id,

        )
        return

    name_tag = tags.get("Name", "")

    perform_remediation(parsed.resource_type, parsed.resource_id, parsed.change_summary, tag_name=name_tag)



def perform_remediation(resource_type: str, resource_id: str, change_summary: str, tag_name: str = "") -> None:
    """

    리소스 유형별 Auto-Remediation 수행.

    EC2 → stop_instances, RDS → stop_db_instance, ELB → delete_load_balancer


    수행 전 CloudWatch Logs에 사전 로그 기록.

    완료 후 SNS 알림 발송.

    실패 시 로그 + SNS 즉시 알림.


    Requirements: 5.1, 5.2, 5.3, 5.4
    """

    # 사전 로그 기록 (remediation 액션보다 먼저)

    logger.warning(

        "REMEDIATION PRE-LOG: resource_id=%s type=%s change=%s action=%s",

        resource_id, resource_type, change_summary,

        _remediation_action_name(resource_type),

    )


    try:

        action_taken = _execute_remediation(resource_type, resource_id)

    except Exception as e:

        logger.error(

            "Remediation FAILED for %s %s: %s", resource_type, resource_id, e

        )

        send_error_alert(

            context=f"perform_remediation {resource_type} {resource_id}",

            error=e,

        )
        raise


    logger.info(

        "Remediation SUCCESS: %s %s action=%s",

        resource_type, resource_id, action_taken,

    )

    send_remediation_alert(

        resource_id=resource_id,

        resource_type=resource_type,

        change_summary=change_summary,

        action_taken=action_taken,

        tag_name=tag_name,

    )



def _remediation_action_name(resource_type: str) -> str:

    return {"EC2": "STOPPED", "RDS": "STOPPED", "AuroraRDS": "STOPPED", "DocDB": "STOPPED", "ELB": "DELETED", "ALB": "DELETED", "NLB": "DELETED"}.get(

        resource_type, "UNKNOWN"

    )



def _execute_remediation(resource_type: str, resource_id: str) -> str:
    """

    실제 AWS API 호출. 성공 시 action_taken 문자열 반환.

    Requirements: 5.1
    """

    if resource_type == "EC2":

        ec2 = boto3.client("ec2")

        ec2.stop_instances(InstanceIds=[resource_id])

        return "STOPPED"


    if resource_type == "RDS":

        rds = boto3.client("rds")

        rds.stop_db_instance(DBInstanceIdentifier=resource_id)

        return "STOPPED"


    if resource_type == "AuroraRDS":

        rds = boto3.client("rds")

        rds.stop_db_instance(DBInstanceIdentifier=resource_id)

        return "STOPPED"


    if resource_type == "DocDB":

        rds = boto3.client("rds")

        rds.stop_db_instance(DBInstanceIdentifier=resource_id)

        return "STOPPED"


    if resource_type == "ELB":

        elbv2 = boto3.client("elbv2")

        elbv2.delete_load_balancer(LoadBalancerArn=resource_id)

        return "DELETED"


    if resource_type in ("ALB", "NLB"):

        elbv2 = boto3.client("elbv2")

        elbv2.delete_load_balancer(LoadBalancerArn=resource_id)

        return "DELETED"


    raise ValueError(f"Unsupported resource_type for remediation: {resource_type!r}")



# ──────────────────────────────────────────────

# DELETE 처리 → lifecycle 알림

# ──────────────────────────────────────────────


def _handle_delete(parsed: ParsedEvent) -> None:
    """
    DELETE 이벤트: CloudWatch Alarm 삭제 + lifecycle SNS 알림.

    NOTE: 리소스가 이미 삭제된 후에는 태그 조회가 불가능하므로
    태그 확인 없이 무조건 알람 삭제를 시도한다.
    알람이 없으면 delete_alarms는 조용히 성공한다.

    KI-008: _resolve_rds_aurora_type() 실패 시 (is_rds_fallback=True)
    resource_type="" 으로 전체 prefix 검색하여 RDS/AuroraRDS 양쪽 알람 삭제.

    Requirements: 8.1, 8.2, 8.3, 13.1, 13.2, 13.3
    """

    # KI-008: 폴백 시 빈 resource_type으로 전체 prefix 검색
    delete_type = parsed.resource_type
    if parsed._is_rds_fallback:
        logger.warning(
            "RDS/Aurora type resolution failed for %s: "
            "searching all RDS-family prefixes for alarm cleanup",
            parsed.resource_id,
        )
        delete_type = ""

    # 태그 조회 없이 바로 알람 삭제 (삭제된 리소스는 태그 조회 불가)
    deleted = delete_alarms_for_resource(parsed.resource_id, delete_type)
    if deleted:
        logger.info("Deleted alarms for terminated resource %s: %s", parsed.resource_id, deleted)
    else:
        logger.info(
            "No alarms found for deleted resource %s %s (already removed or never monitored)",
            parsed.resource_type, parsed.resource_id,
        )

    # Monitoring=on 태그가 있었는지 확인 (lifecycle 알림 여부 결정)
    # 삭제 직전 태그 조회 시도 - 실패해도 알람 삭제는 이미 완료
    try:
        tags = get_resource_tags(parsed.resource_id, parsed.resource_type)
        was_monitored = tags.get("Monitoring", "").lower() == "on"
        name_tag = tags.get("Name", "")
    except Exception:
        # 리소스 삭제 후 태그 조회 실패 시, 알람이 있었다면 모니터링 대상이었던 것으로 간주
        was_monitored = bool(deleted)
        name_tag = ""

    if not was_monitored and not deleted:
        logger.info(
            "Ignoring DELETE lifecycle alert for %s %s: not a monitored resource",
            parsed.resource_type, parsed.resource_id,
        )
        return

    message = (
        f"{parsed.resource_type} 리소스 {parsed.resource_id}가 삭제되었습니다. "
        f"({parsed.event_name})"
    )
    logger.info("Sending lifecycle alert for deleted resource: %s %s", parsed.resource_type, parsed.resource_id)
    send_lifecycle_alert(
        resource_id=parsed.resource_id,
        resource_type=parsed.resource_type,
        event_type="RESOURCE_DELETED",
        message_text=message,
        tag_name=name_tag,
    )



# ──────────────────────────────────────────────

# CREATE 처리 → 알람 즉시 생성

# ──────────────────────────────────────────────


def _handle_create(parsed: ParsedEvent) -> None:
    """CREATE 이벤트: Monitoring=on 태그 있으면 알람 즉시 생성."""
    tags = get_resource_tags(parsed.resource_id, parsed.resource_type)
    if not tags:
        logger.warning(
            "get_resource_tags returned empty for newly created %s %s: skipping alarm creation",
            parsed.resource_type, parsed.resource_id,
        )
        return

    if not has_monitoring_tag(tags):
        logger.info(
            "Skipping alarm creation for %s %s: no Monitoring=on tag",
            parsed.resource_type, parsed.resource_id,
        )
        return

    created = create_alarms_for_resource(
        parsed.resource_id, parsed.resource_type, tags,
    )
    logger.info(
        "Created alarms for newly created %s %s: %s",
        parsed.resource_type, parsed.resource_id, created,
    )


# ──────────────────────────────────────────────

# TAG_CHANGE 처리

# ──────────────────────────────────────────────


def _remove_monitoring_and_notify(
    resource_id: str,
    resource_type: str,
    message_text: str,
) -> None:
    """알람 삭제 + MONITORING_REMOVED lifecycle 알림 발송 (공통 헬퍼)."""
    delete_alarms_for_resource(resource_id, resource_type)
    tags = get_resource_tags(resource_id, resource_type)
    name_tag = tags.get("Name", "") if tags else ""
    send_lifecycle_alert(
        resource_id=resource_id,
        resource_type=resource_type,
        event_type="MONITORING_REMOVED",
        message_text=message_text,
        tag_name=name_tag,
    )


def _handle_tag_change(parsed: ParsedEvent) -> None:
    """
    TAG_CHANGE 이벤트 처리.

    EC2: CreateTags/DeleteTags
    RDS: AddTagsToResource/RemoveTagsFromResource
    ELB: AddTags/RemoveTags

    - 태그 추가 + Monitoring=on → CloudWatch Alarm 자동 생성 + 로그
    - 태그 삭제 + Monitoring → CloudWatch Alarm 삭제 + SNS lifecycle 알림
    - 태그 추가 + Monitoring!=on → CloudWatch Alarm 삭제 + SNS lifecycle 알림

    Requirements: 8.4, 8.5, 8.6, 8.7
    """
    try:
        tag_keys, tag_kvs = _extract_tags_from_params(
            parsed.request_params, parsed.event_name,
        )
    except Exception as e:
        logger.error(
            "Failed to parse tag change params for %s %s: %s",
            parsed.resource_type, parsed.resource_id, e,
        )
        send_error_alert(
            context=f"handle_tag_change {parsed.resource_id}",
            error=e,
        )
        return

    monitoring_involved = "Monitoring" in tag_keys
    threshold_involved = any(k.startswith("Threshold_") for k in tag_keys)

    if not monitoring_involved:
        _handle_threshold_only_change(parsed, threshold_involved)
        return

    is_add = parsed.event_name in ("CreateTags", "AddTagsToResource", "AddTags")
    if is_add:
        _handle_monitoring_tag_add(parsed, tag_kvs)
    else:
        logger.info(
            "Monitoring tag REMOVED from %s %s: deleting CloudWatch Alarms",
            parsed.resource_type, parsed.resource_id,
        )
        _remove_monitoring_and_notify(
            parsed.resource_id, parsed.resource_type,
            f"{parsed.resource_type} 리소스 {parsed.resource_id}의 "
            f"Monitoring 태그가 제거되어 모니터링 대상에서 제외되었습니다.",
        )


def _handle_threshold_only_change(
    parsed: ParsedEvent,
    threshold_involved: bool,
) -> None:
    """Monitoring 태그 변경 없이 Threshold 태그만 변경된 경우 처리."""
    if threshold_involved:
        tags = get_resource_tags(parsed.resource_id, parsed.resource_type)
        if has_monitoring_tag(tags):
            logger.info(
                "Threshold tag changed on monitored %s %s: syncing alarms",
                parsed.resource_type, parsed.resource_id,
            )
            sync_alarms_for_resource(parsed.resource_id, parsed.resource_type, tags)
        else:
            logger.debug(
                "Threshold tag changed on %s %s but Monitoring=on not set: skipping",
                parsed.resource_type, parsed.resource_id,
            )
    else:
        logger.debug(
            "TAG_CHANGE for %s %s does not involve Monitoring or Threshold tags: skipping",
            parsed.resource_type, parsed.resource_id,
        )


def _handle_monitoring_tag_add(
    parsed: ParsedEvent,
    tag_kvs: dict[str, str],
) -> None:
    """Monitoring 태그 추가 이벤트 처리."""
    monitoring_value = tag_kvs.get("Monitoring", "")
    if monitoring_value.lower() == "on":
        logger.info(
            "Monitoring=on tag ADDED to %s %s: creating CloudWatch Alarms",
            parsed.resource_type, parsed.resource_id,
        )
        tags = get_resource_tags(parsed.resource_id, parsed.resource_type)
        if not tags:
            logger.warning(
                "get_resource_tags returned empty for %s %s, using CloudTrail event tags",
                parsed.resource_type, parsed.resource_id,
            )
            tags = tag_kvs
        created = create_alarms_for_resource(
            parsed.resource_id, parsed.resource_type, tags,
        )
        logger.info("Created alarms: %s", created)
    else:
        logger.info(
            "Monitoring tag set to %r (not 'on') on %s %s: deleting alarms",
            monitoring_value, parsed.resource_type, parsed.resource_id,
        )
        _remove_monitoring_and_notify(
            parsed.resource_id, parsed.resource_type,
            f"{parsed.resource_type} 리소스 {parsed.resource_id}의 "
            f"Monitoring 태그가 '{monitoring_value}'로 변경되어 모니터링 대상에서 제외되었습니다.",
        )




def _extract_tags_from_params(
    params: dict, event_name: str = "",
) -> tuple[set[str], dict[str, str]]:
    """
    CloudTrail requestParameters에서 태그 키 집합과 키-값 딕셔너리 추출.

    EC2 CreateTags/DeleteTags:
      tagSet.items: [{"key": "Monitoring", "value": "on"}, ...]

    RDS AddTagsToResource/RemoveTagsFromResource:
      tags: [{"key": "Monitoring", "value": "on"}, ...]

    ELB AddTags/RemoveTags:
      tags: [{"key": "Monitoring", "value": "on"}, ...]
    """
    # EC2: tagSet.items 구조
    items = params.get("tagSet", {}).get("items", [])

    # RDS/ELB: tags 리스트 구조 (tagSet이 없을 때)
    if not items:
        items = params.get("tags", [])

    # ELB RemoveTags: tagKeys 리스트 (키만 있음)
    if not items and event_name == "RemoveTags":
        tag_keys_list = params.get("tagKeys", [])
        tag_keys = set(tag_keys_list)
        return tag_keys, {k: "" for k in tag_keys}

    tag_keys = {item["key"] for item in items if "key" in item}
    tag_kvs = {
        item["key"]: item.get("value", "")
        for item in items if "key" in item
    }
    return tag_keys, tag_kvs

