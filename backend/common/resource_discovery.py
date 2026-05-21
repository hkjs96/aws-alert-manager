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
from botocore.exceptions import ClientError

from common.tag_resolver import has_monitoring_tag

logger = logging.getLogger(__name__)


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
            all_resources.extend(_discover_alb(session, account_id, region, customer_id))
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


def _discover_alb(session, account_id, region, customer_id):
    resources = []
    try:
        elbv2 = session.client("elbv2")
        paginator = elbv2.get_paginator("describe_load_balancers")
        for page in paginator.paginate():
            for lb in page.get("LoadBalancers", []):
                lb_arn = lb["LoadBalancerArn"]
                lb_type = lb.get("Type", "application")
                if lb_type != "application":
                    continue

                tags_resp = elbv2.describe_tags(ResourceArns=[lb_arn])
                tags = {}
                if tags_resp.get("TagDescriptions"):
                    tags = {t["Key"]: t["Value"] for t in tags_resp["TagDescriptions"][0].get("Tags", [])}

                resources.append({
                    "resource_id": lb_arn,
                    "name": lb.get("LoadBalancerName", lb_arn),
                    "type": "ALB",
                    "account_id": account_id,
                    "region": region,
                    "customer_id": customer_id,
                    "monitoring": has_monitoring_tag(tags),
                    "status": "active",
                    "tags": tags
                })
    except ClientError as e:
        logger.error("ALB discovery failed in %s/%s: %s", account_id, region, e)
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
