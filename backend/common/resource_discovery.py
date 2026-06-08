"""
멀티 어카운트 리소스 디스커버리.

ApiHandler와 DailyMonitor 양쪽에서 사용한다.
account 객체에 role_arn이 비어있거나 account_id가 현재 세션과 같으면
AssumeRole을 건너뛰고 현재 세션을 그대로 사용한다.
"""

import logging
import os
from typing import List

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from common.tag_resolver import has_monitoring_tag

logger = logging.getLogger(__name__)


def query_inventory_by_accounts(table, account_ids) -> List[dict]:
    """account_id-index GSI로 대상 계정의 인벤토리 항목만 조회한다.

    전체 테이블 Scan을 피하기 위함. 정리(cleanup) 대상은 동기화 중인 계정뿐이므로
    그 계정들만 조회하면 충분하다.
    """
    items: List[dict] = []
    for acc in {a for a in account_ids if a}:
        kwargs = {
            "IndexName": "account_id-index",
            "KeyConditionExpression": Key("account_id").eq(acc),
        }
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
    return items


def _get_current_account_id() -> str:
    return boto3.client("sts").get_caller_identity().get("Account", "")


def _get_session_for_account(account: dict, region: str):
    role_arn = account.get("role_arn") or ""
    account_id = account.get("account_id") or ""

    if account_id and account_id == _get_current_account_id():
        return boto3.Session(region_name=region)

    if not role_arn:
        return boto3.Session(region_name=region)

    sts = boto3.client("sts")
    try:
        resp = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=f"InventoryDiscovery-{account_id}",
        )
        creds = resp["Credentials"]
        return boto3.Session(
            region_name=region,
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    except ClientError as e:
        logger.error("AssumeRole failed for account %s: %s", account_id, e)
        return None


def _discovered_keys(discovered: List[dict]) -> set:
    """(resource_id, account_id) 키 집합. resource_id가 없으면 id로 폴백."""
    keys = set()
    for r in discovered:
        rid = r.get("resource_id") or r.get("id")
        acc = r.get("account_id")
        if rid and acc:
            keys.add((rid, acc))
    return keys


def cleanup_stale_inventory(table, db_items: List[dict], discovered: List[dict], *, log=logger) -> int:
    """디스커버리 결과에 없는 인벤토리 항목을 삭제하고 삭제 개수를 반환한다.

    안전 계약: 디스커버리가 리소스를 1개 이상 반환한 계정만 삭제 대상이다.
    AssumeRole 실패·스로틀·일시 오류로 특정 계정의 디스커버리가 통째로 비면
    그 계정의 인벤토리는 지우지 않고 보존한다(전멸 방지). 알람 스냅샷
    항목(resource_id가 'alarm#'로 시작)과 entity_type이 resource가 아닌
    항목은 절대 건드리지 않는다.
    """
    discovered_keys = _discovered_keys(discovered)
    deletable_accounts = {acc for _, acc in discovered_keys}
    if not deletable_accounts:
        return 0

    removed = 0
    for item in db_items:
        if item.get("entity_type", "resource") != "resource":
            continue
        res_id = item.get("resource_id", "")
        acc_id = item.get("account_id", "")
        if res_id.startswith("alarm#"):
            continue
        if acc_id not in deletable_accounts:
            continue
        if (res_id, acc_id) in discovered_keys:
            continue
        try:
            table.delete_item(Key={"resource_id": res_id, "account_id": acc_id})
            removed += 1
        except ClientError as exc:
            log.error("Failed to delete stale inventory item %s: %s", res_id, exc)
    return removed


def discover_resources(accounts: List[dict]) -> List[dict]:
    all_resources = []
    for account in accounts:
        regions = account.get("regions") or ["ap-northeast-2"]
        customer_id = account.get("customer_id")
        account_id = account.get("account_id")

        for region in regions:
            session = _get_session_for_account(account, region)
            if not session:
                continue

            all_resources.extend(_discover_ec2(session, account_id, region, customer_id))
            all_resources.extend(_discover_rds(session, account_id, region, customer_id))
            all_resources.extend(_discover_load_balancers(session, account_id, region, customer_id))
            all_resources.extend(_discover_target_groups(session, account_id, region, customer_id))
            all_resources.extend(_discover_elasticache(session, account_id, region, customer_id))
            all_resources.extend(_discover_nat(session, account_id, region, customer_id))
            all_resources.extend(_discover_lambda(session, account_id, region, customer_id))

        session = _get_session_for_account(account, regions[0])
        if session:
            all_resources.extend(_discover_s3(session, account_id, customer_id))

    return all_resources


def _discover_ec2(session, account_id, region, customer_id):
    resources = []
    try:
        ec2 = session.client("ec2")
        paginator = ec2.get_paginator("describe_instances")
        for page in paginator.paginate(Filters=[{"Name": "instance-state-name", "Values": ["running", "stopped", "pending", "shutting-down"]}]):
            for reservation in page.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}
                    name = tags.get("Name", instance["InstanceId"])
                    resources.append({
                        "resource_id": instance["InstanceId"],
                        "name": name,
                        "type": "EC2",
                        "account_id": account_id,
                        "region": region,
                        "customer_id": customer_id,
                        "monitoring": has_monitoring_tag(tags),
                        "status": "active",
                        "tags": tags
                    })
    except ClientError as e:
        logger.error("EC2 discovery failed in %s/%s: %s", account_id, region, e)
    return resources


def _discover_rds(session, account_id, region, customer_id):
    resources = []
    try:
        rds = session.client("rds")
        paginator = rds.get_paginator("describe_db_instances")
        for page in paginator.paginate():
            for db in page.get("DBInstances", []):
                db_id = db["DBInstanceIdentifier"]
                engine = db.get("Engine", "")
                if engine.lower() == "docdb":
                    continue

                resource_type = "AuroraRDS" if "aurora" in engine.lower() else "RDS"

                tags_resp = rds.list_tags_for_resource(ResourceName=db["DBInstanceArn"])
                tags = {t["Key"]: t["Value"] for t in tags_resp.get("TagList", [])}

                resources.append({
                    "resource_id": db_id,
                    "name": db_id,
                    "type": resource_type,
                    "account_id": account_id,
                    "region": region,
                    "customer_id": customer_id,
                    "monitoring": has_monitoring_tag(tags),
                    "status": "active",
                    "tags": tags
                })
    except ClientError as e:
        logger.error("RDS discovery failed in %s/%s: %s", account_id, region, e)
    return resources


def _discover_load_balancers(session, account_id, region, customer_id):
    """ALB(application) + NLB(network)를 인벤토리로 수집한다. gateway 등은 제외."""
    resources = []
    try:
        elbv2 = session.client("elbv2")
        paginator = elbv2.get_paginator("describe_load_balancers")
        for page in paginator.paginate():
            for lb in page.get("LoadBalancers", []):
                lb_arn = lb["LoadBalancerArn"]
                lb_type = lb.get("Type", "application")
                if lb_type == "application":
                    res_type = "ALB"
                elif lb_type == "network":
                    res_type = "NLB"
                else:
                    continue

                tags_resp = elbv2.describe_tags(ResourceArns=[lb_arn])
                tags = {}
                if tags_resp.get("TagDescriptions"):
                    tags = {t["Key"]: t["Value"] for t in tags_resp["TagDescriptions"][0].get("Tags", [])}

                resources.append({
                    "resource_id": lb_arn,
                    "name": lb.get("LoadBalancerName", lb_arn),
                    "type": res_type,
                    "account_id": account_id,
                    "region": region,
                    "customer_id": customer_id,
                    "monitoring": has_monitoring_tag(tags),
                    "status": "active",
                    "tags": tags
                })
    except ClientError as e:
        logger.error("LB discovery failed in %s/%s: %s", account_id, region, e)
    return resources


def _discover_target_groups(session, account_id, region, customer_id):
    """ALB/NLB의 Target Group을 인벤토리로 수집한다."""
    resources = []
    try:
        elbv2 = session.client("elbv2")
        paginator = elbv2.get_paginator("describe_target_groups")
        for page in paginator.paginate():
            for tg in page.get("TargetGroups", []):
                tg_arn = tg["TargetGroupArn"]
                tags_resp = elbv2.describe_tags(ResourceArns=[tg_arn])
                tags = {}
                if tags_resp.get("TagDescriptions"):
                    tags = {t["Key"]: t["Value"] for t in tags_resp["TagDescriptions"][0].get("Tags", [])}

                resources.append({
                    "resource_id": tg_arn,
                    "name": tg.get("TargetGroupName", tg_arn),
                    "type": "TG",
                    "account_id": account_id,
                    "region": region,
                    "customer_id": customer_id,
                    "monitoring": has_monitoring_tag(tags),
                    "status": "active",
                    "tags": tags
                })
    except ClientError as e:
        logger.error("TargetGroup discovery failed in %s/%s: %s", account_id, region, e)
    return resources


def _discover_elasticache(session, account_id, region, customer_id):
    """ElastiCache(Redis/Valkey) 클러스터를 인벤토리로 수집한다."""
    resources = []
    try:
        ec = session.client("elasticache")
        paginator = ec.get_paginator("describe_cache_clusters")
        for page in paginator.paginate():
            for cluster in page.get("CacheClusters", []):
                # Redis와 Valkey(Redis 호환)는 동일 메트릭 → 함께 수집. Memcached 제외.
                if cluster.get("Engine", "").lower() not in ("redis", "valkey"):
                    continue
                cluster_id = cluster["CacheClusterId"]

                tags = {}
                arn = cluster.get("ARN")
                if arn:
                    try:
                        tags_resp = ec.list_tags_for_resource(ResourceName=arn)
                        tags = {t["Key"]: t["Value"] for t in tags_resp.get("TagList", [])}
                    except ClientError as e:
                        logger.error("ElastiCache list_tags failed for %s: %s", cluster_id, e)

                resources.append({
                    "resource_id": cluster_id,
                    "name": cluster_id,
                    "type": "ElastiCache",
                    "account_id": account_id,
                    "region": region,
                    "customer_id": customer_id,
                    "monitoring": has_monitoring_tag(tags),
                    "status": "active",
                    "tags": tags
                })
    except ClientError as e:
        logger.error("ElastiCache discovery failed in %s/%s: %s", account_id, region, e)
    return resources


def _discover_nat(session, account_id, region, customer_id):
    """NAT Gateway를 인벤토리로 수집한다. (삭제 중/삭제된 것은 제외, 태그는 응답에 포함)"""
    resources = []
    try:
        ec2 = session.client("ec2")
        paginator = ec2.get_paginator("describe_nat_gateways")
        for page in paginator.paginate():
            for nat in page.get("NatGateways", []):
                if nat.get("State") in ("deleting", "deleted", "failed"):
                    continue
                nat_id = nat["NatGatewayId"]
                tags = {t["Key"]: t["Value"] for t in nat.get("Tags", [])}
                resources.append({
                    "resource_id": nat_id,
                    "name": tags.get("Name", nat_id),
                    "type": "NAT",
                    "account_id": account_id,
                    "region": region,
                    "customer_id": customer_id,
                    "monitoring": has_monitoring_tag(tags),
                    "status": "active",
                    "tags": tags
                })
    except ClientError as e:
        logger.error("NAT discovery failed in %s/%s: %s", account_id, region, e)
    return resources


def _discover_lambda(session, account_id, region, customer_id):
    resources = []
    try:
        lambda_client = session.client("lambda")
        paginator = lambda_client.get_paginator("list_functions")
        for page in paginator.paginate():
            for fn in page.get("Functions", []):
                fn_name = fn["FunctionName"]
                fn_arn = fn["FunctionArn"]

                tags_resp = lambda_client.list_tags(Resource=fn_arn)
                tags = tags_resp.get("Tags", {})

                resources.append({
                    "resource_id": fn_name,
                    "name": fn_name,
                    "type": "Lambda",
                    "account_id": account_id,
                    "region": region,
                    "customer_id": customer_id,
                    "monitoring": has_monitoring_tag(tags),
                    "status": "active",
                    "tags": tags,
                    "arn": fn_arn
                })
    except ClientError as e:
        logger.error("Lambda discovery failed in %s/%s: %s", account_id, region, e)
    return resources


def _discover_s3(session, account_id, customer_id):
    resources = []
    try:
        s3 = session.client("s3")
        resp = s3.list_buckets()
        for bucket in resp.get("Buckets", []):
            bucket_name = bucket["Name"]

            try:
                region_resp = s3.get_bucket_location(Bucket=bucket_name)
                region = region_resp.get("LocationConstraint") or "us-east-1"
                if region == "EU":
                    region = "eu-west-1"
            except ClientError:
                region = "unknown"

            tags = {}
            try:
                tags_resp = s3.get_bucket_tagging(Bucket=bucket_name)
                tags = {t["Key"]: t["Value"] for t in tags_resp.get("TagSet", [])}
            except ClientError:
                pass

            resources.append({
                "resource_id": bucket_name,
                "name": bucket_name,
                "type": "S3",
                "account_id": account_id,
                "region": region,
                "customer_id": customer_id,
                "monitoring": has_monitoring_tag(tags),
                "status": "active",
                "tags": tags
            })
    except ClientError as e:
        logger.error("S3 discovery failed in %s: %s", account_id, e)
    return resources
