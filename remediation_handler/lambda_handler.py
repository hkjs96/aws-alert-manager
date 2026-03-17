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


# Lambda 환경에서 root logger 레벨 설정 (모든 모듈에 적용)

logging.getLogger().setLevel(logging.INFO)

logger = logging.getLogger(__name__)


from common import MONITORED_API_EVENTS

from common.sns_notifier import (
    send_error_alert,

    send_lifecycle_alert,
    send_remediation_alert,

)

from common.tag_resolver import get_resource_tags, has_monitoring_tag



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



# ──────────────────────────────────────────────

# API → (resource_type, id_extractor) 매핑

# ──────────────────────────────────────────────


def _extract_ec2_instance_id(params: dict) -> Optional[str]:

    ids = params.get("instancesSet", {}).get("items", [])

    return ids[0].get("instanceId") if ids else params.get("instanceId")



def _extract_rds_id(params: dict) -> Optional[str]:

    return params.get("dBInstanceIdentifier")



def _extract_elb_id(params: dict) -> Optional[str]:

    return params.get("loadBalancerArn") or params.get("loadBalancerName")



def _extract_tag_resource_id(params: dict) -> Optional[str]:

    """CreateTags / DeleteTags: resourcesSet 또는 resourceIdList 첫 번째 항목"""

    items = params.get("resourcesSet", {}).get("items", [])

    if items:

        return items[0].get("resourceId")

    lst = params.get("resourceIdList", [])

    return lst[0] if lst else None



def _extract_rds_tag_resource_id(params: dict) -> Optional[str]:

    """AddTagsToResource / RemoveTagsFromResource: resourceName에서 DB identifier 추출.

    resourceName은 ARN 형태: arn:aws:rds:region:account:db:my-db-id"""

    arn = params.get("resourceName", "")

    if ":db:" in arn:

        return arn.split(":db:")[-1]

    return arn if arn else None



def _extract_elb_tag_resource_id(params: dict) -> Optional[str]:

    """AddTags / RemoveTags: resourceArns 첫 번째 항목"""

    arns = params.get("resourceArns", [])

    return arns[0] if arns else None



_API_MAP: dict[str, tuple[str, callable]] = {

    # MODIFY

    "ModifyInstanceAttribute":      ("EC2", _extract_ec2_instance_id),

    "ModifyInstanceType":           ("EC2", _extract_ec2_instance_id),

    "ModifyDBInstance":             ("RDS", _extract_rds_id),

    "ModifyLoadBalancerAttributes": ("ELB", _extract_elb_id),

    "ModifyListener":               ("ELB", _extract_elb_id),

    # DELETE

    "TerminateInstances":           ("EC2", _extract_ec2_instance_id),

    "DeleteDBInstance":             ("RDS", _extract_rds_id),

    "DeleteLoadBalancer":           ("ELB", _extract_elb_id),

    # TAG_CHANGE

    "CreateTags":                   ("EC2", _extract_tag_resource_id),

    "DeleteTags":                   ("EC2", _extract_tag_resource_id),

    "AddTagsToResource":            ("RDS", _extract_rds_tag_resource_id),

    "RemoveTagsFromResource":       ("RDS", _extract_rds_tag_resource_id),

    "AddTags":                      ("ELB", _extract_elb_tag_resource_id),

    "RemoveTags":                   ("ELB", _extract_elb_tag_resource_id),

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

        parsed = parse_cloudtrail_event(event)

    except Exception as e:

        logger.error("Failed to parse CloudTrail event: %s | event=%s", e, event)

        send_error_alert(context="parse_cloudtrail_event", error=e)

        return {"status": "parse_error"}


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

        else:

            logger.warning("Unknown event_category: %s", parsed.event_category)

    except Exception as e:

        # perform_remediation 내부에서 이미 send_error_alert를 호출했으므로

        # 여기서는 로그만 기록하고 status=error 반환

        logger.error(

            "Unhandled error processing event %s for %s: %s",

            parsed.event_name, parsed.resource_id, e,

        )

        return {"status": "error"}


    return {"status": "ok"}



# ──────────────────────────────────────────────

# 이벤트 파싱

# ──────────────────────────────────────────────


def parse_cloudtrail_event(event: dict) -> ParsedEvent:
    """

    EventBridge 래핑 CloudTrail 이벤트에서 필요한 필드 추출.


    EventBridge 구조:

    {

      "detail": {

        "eventName": "...",

        "requestParameters": {...}

      }

    }


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


    resource_type, id_extractor = _API_MAP[event_name]

    resource_id = id_extractor(request_params)

    if not resource_id:

        raise ValueError(

            f"Cannot extract resource_id for {event_name}: params={request_params}"

        )


    event_category = _get_event_category(event_name)

    if not event_category:

        raise ValueError(f"Cannot determine event_category for {event_name!r}")


    change_summary = (

        f"{event_name} on {resource_type} {resource_id}"

        f" (params: {_summarize_params(request_params)})"

    )


    return ParsedEvent(

        resource_id=resource_id,

        resource_type=resource_type,

        event_name=event_name,

        event_category=event_category,

        change_summary=change_summary,

        request_params=request_params,

    )



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

    return {"EC2": "STOPPED", "RDS": "STOPPED", "ELB": "DELETED"}.get(

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


    if resource_type == "ELB":

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

    Requirements: 8.1, 8.2, 8.3
    """
    from common.alarm_manager import delete_alarms_for_resource

    # 태그 조회 없이 바로 알람 삭제 (삭제된 리소스는 태그 조회 불가)
    deleted = delete_alarms_for_resource(parsed.resource_id, parsed.resource_type)
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

# TAG_CHANGE 처리

# ──────────────────────────────────────────────


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
        if threshold_involved:
            tags = get_resource_tags(parsed.resource_id, parsed.resource_type)
            if has_monitoring_tag(tags):
                logger.info(
                    "Threshold tag changed on monitored %s %s: syncing alarms",
                    parsed.resource_type, parsed.resource_id,
                )
                from common.alarm_manager import sync_alarms_for_resource
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
        return

    # 태그 추가 이벤트인지 삭제 이벤트인지 판별
    is_add = parsed.event_name in ("CreateTags", "AddTagsToResource", "AddTags")

    if is_add:
        monitoring_value = tag_kvs.get("Monitoring", "")
        if monitoring_value.lower() == "on":
            logger.info(
                "Monitoring=on tag ADDED to %s %s: creating CloudWatch Alarms",
                parsed.resource_type, parsed.resource_id,
            )
            tags = get_resource_tags(parsed.resource_id, parsed.resource_type)
            if not tags:
                logger.warning(
                    "get_resource_tags returned empty for %s %s, using tags from CloudTrail event",
                    parsed.resource_type, parsed.resource_id,
                )
                tags = tag_kvs
            from common.alarm_manager import create_alarms_for_resource
            created = create_alarms_for_resource(
                parsed.resource_id, parsed.resource_type, tags,
            )
            logger.info("Created alarms: %s", created)
        else:
            logger.info(
                "Monitoring tag set to %r (not 'on') on %s %s: deleting alarms",
                monitoring_value, parsed.resource_type, parsed.resource_id,
            )
            from common.alarm_manager import delete_alarms_for_resource
            delete_alarms_for_resource(parsed.resource_id, parsed.resource_type)
            name_tags = get_resource_tags(parsed.resource_id, parsed.resource_type)
            name_tag = name_tags.get("Name", "") if name_tags else ""
            message = (
                f"{parsed.resource_type} 리소스 {parsed.resource_id}의 "
                f"Monitoring 태그가 '{monitoring_value}'로 변경되어 모니터링 대상에서 제외되었습니다."
            )
            send_lifecycle_alert(
                resource_id=parsed.resource_id,
                resource_type=parsed.resource_type,
                event_type="MONITORING_REMOVED",
                message_text=message,
                tag_name=name_tag,
            )
    else:
        # 태그 삭제 이벤트: DeleteTags, RemoveTagsFromResource, RemoveTags
        logger.info(
            "Monitoring tag REMOVED from %s %s: deleting CloudWatch Alarms",
            parsed.resource_type, parsed.resource_id,
        )
        from common.alarm_manager import delete_alarms_for_resource
        delete_alarms_for_resource(parsed.resource_id, parsed.resource_type)
        name_tags = get_resource_tags(parsed.resource_id, parsed.resource_type)
        name_tag = name_tags.get("Name", "") if name_tags else ""
        message = (
            f"{parsed.resource_type} 리소스 {parsed.resource_id}의 "
            f"Monitoring 태그가 제거되어 모니터링 대상에서 제외되었습니다."
        )
        send_lifecycle_alert(
            resource_id=parsed.resource_id,
            resource_type=parsed.resource_type,
            event_type="MONITORING_REMOVED",
            message_text=message,
            tag_name=name_tag,
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

