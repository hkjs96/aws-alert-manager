"""
멀티 어카운트 리소스 디스커버리.

ApiHandler와 DailyMonitor 양쪽에서 사용한다.
account 객체에 role_arn이 비어있거나 account_id가 현재 세션과 같으면
AssumeRole을 건너뛰고 현재 세션을 그대로 사용한다.
"""

import logging
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
            all_resources.extend(_discover_docdb(session, account_id, region, customer_id))
            all_resources.extend(_discover_clb(session, account_id, region, customer_id))
            all_resources.extend(_discover_sqs(session, account_id, region, customer_id))
            all_resources.extend(_discover_dynamodb(session, account_id, region, customer_id))
            all_resources.extend(_discover_efs(session, account_id, region, customer_id))
            all_resources.extend(_discover_opensearch(session, account_id, region, customer_id))
            all_resources.extend(_discover_ecs(session, account_id, region, customer_id))

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
                    instance_id = instance["InstanceId"]
                    name = tags.get("Name", instance_id)
                    resources.append({
                        "resource_id": instance_id,
                        "name": name,
                        "type": "EC2",
                        "arn": f"arn:aws:ec2:{region}:{account_id}:instance/{instance_id}",
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
                    "arn": db["DBInstanceArn"],
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
                    "arn": lb_arn,
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
                    "arn": tg_arn,
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

                cluster_arn = arn or f"arn:aws:elasticache:{region}:{account_id}:cluster:{cluster_id}"
                resources.append({
                    "resource_id": cluster_id,
                    "name": cluster_id,
                    "type": "ElastiCache",
                    "arn": cluster_arn,
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
                    "arn": f"arn:aws:ec2:{region}:{account_id}:natgateway/{nat_id}",
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
                "arn": f"arn:aws:s3:::{bucket_name}",
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


def _discover_docdb(session, account_id, region, customer_id):
    """DocumentDB 인스턴스를 인벤토리로 수집한다 (RDS API, engine==docdb)."""
    resources = []
    try:
        rds = session.client("rds")
        paginator = rds.get_paginator("describe_db_instances")
        for page in paginator.paginate():
            for db in page.get("DBInstances", []):
                if db.get("Engine", "").lower() != "docdb":
                    continue
                if db.get("DBInstanceStatus") in ("deleting", "deleted"):
                    continue
                db_id = db["DBInstanceIdentifier"]
                arn = db.get("DBInstanceArn", "")
                tags = {}
                if arn:
                    try:
                        resp = rds.list_tags_for_resource(ResourceName=arn)
                        tags = {t["Key"]: t["Value"] for t in resp.get("TagList", [])}
                    except ClientError as e:
                        logger.error("DocDB list_tags failed for %s: %s", db_id, e)
                resources.append({
                    "resource_id": db_id,
                    "name": db_id,
                    "type": "DocDB",
                    "arn": arn,
                    "account_id": account_id,
                    "region": region,
                    "customer_id": customer_id,
                    "monitoring": has_monitoring_tag(tags),
                    "status": "active",
                    "tags": tags
                })
    except ClientError as e:
        logger.error("DocDB discovery failed in %s/%s: %s", account_id, region, e)
    return resources


def _discover_clb(session, account_id, region, customer_id):
    """Classic Load Balancer(ELB)를 인벤토리로 수집한다."""
    resources = []
    try:
        elb = session.client("elb")
        paginator = elb.get_paginator("describe_load_balancers")
        for page in paginator.paginate():
            for lb in page.get("LoadBalancerDescriptions", []):
                lb_name = lb["LoadBalancerName"]
                tags = {}
                try:
                    resp = elb.describe_tags(LoadBalancerNames=[lb_name])
                    descs = resp.get("TagDescriptions", [])
                    if descs:
                        tags = {t["Key"]: t["Value"] for t in descs[0].get("Tags", [])}
                except ClientError as e:
                    logger.error("CLB describe_tags failed for %s: %s", lb_name, e)
                arn = f"arn:aws:elasticloadbalancing:{region}:{account_id}:loadbalancer/{lb_name}"
                resources.append({
                    "resource_id": lb_name,
                    "name": lb_name,
                    "type": "CLB",
                    "arn": arn,
                    "account_id": account_id,
                    "region": region,
                    "customer_id": customer_id,
                    "monitoring": has_monitoring_tag(tags),
                    "status": "active",
                    "tags": tags
                })
    except ClientError as e:
        logger.error("CLB discovery failed in %s/%s: %s", account_id, region, e)
    return resources


def _discover_sqs(session, account_id, region, customer_id):
    """SQS 큐를 인벤토리로 수집한다."""
    resources = []
    try:
        sqs = session.client("sqs")
        paginator = sqs.get_paginator("list_queues")
        for page in paginator.paginate():
            for url in page.get("QueueUrls", []):
                queue_name = url.rsplit("/", 1)[-1]
                tags = {}
                try:
                    resp = sqs.list_queue_tags(QueueUrl=url)
                    tags = resp.get("Tags", {})
                except ClientError as e:
                    logger.error("SQS list_queue_tags failed for %s: %s", url, e)
                arn = f"arn:aws:sqs:{region}:{account_id}:{queue_name}"
                resources.append({
                    "resource_id": queue_name,
                    "name": queue_name,
                    "type": "SQS",
                    "arn": arn,
                    "account_id": account_id,
                    "region": region,
                    "customer_id": customer_id,
                    "monitoring": has_monitoring_tag(tags),
                    "status": "active",
                    "tags": tags
                })
    except ClientError as e:
        logger.error("SQS discovery failed in %s/%s: %s", account_id, region, e)
    return resources


def _discover_dynamodb(session, account_id, region, customer_id):
    """DynamoDB 테이블을 인벤토리로 수집한다."""
    resources = []
    try:
        ddb = session.client("dynamodb")
        paginator = ddb.get_paginator("list_tables")
        for page in paginator.paginate():
            for table_name in page.get("TableNames", []):
                try:
                    desc = ddb.describe_table(TableName=table_name)
                    arn = desc["Table"]["TableArn"]
                except ClientError as e:
                    logger.error("DynamoDB describe_table failed for %s: %s", table_name, e)
                    continue
                tags = {}
                try:
                    resp = ddb.list_tags_of_resource(ResourceArn=arn)
                    tags = {t["Key"]: t["Value"] for t in resp.get("Tags", [])}
                except ClientError as e:
                    logger.error("DynamoDB list_tags failed for %s: %s", table_name, e)
                resources.append({
                    "resource_id": table_name,
                    "name": table_name,
                    "type": "DynamoDB",
                    "arn": arn,
                    "account_id": account_id,
                    "region": region,
                    "customer_id": customer_id,
                    "monitoring": has_monitoring_tag(tags),
                    "status": "active",
                    "tags": tags
                })
    except ClientError as e:
        logger.error("DynamoDB discovery failed in %s/%s: %s", account_id, region, e)
    return resources


def _discover_efs(session, account_id, region, customer_id):
    """EFS 파일시스템을 인벤토리로 수집한다."""
    resources = []
    try:
        efs = session.client("efs")
        paginator = efs.get_paginator("describe_file_systems")
        for page in paginator.paginate():
            for fs in page.get("FileSystems", []):
                fs_id = fs["FileSystemId"]
                tags = {t["Key"]: t["Value"] for t in fs.get("Tags", [])}
                arn = fs.get("FileSystemArn") or \
                    f"arn:aws:elasticfilesystem:{region}:{account_id}:file-system/{fs_id}"
                resources.append({
                    "resource_id": fs_id,
                    "name": tags.get("Name", fs_id),
                    "type": "EFS",
                    "arn": arn,
                    "account_id": account_id,
                    "region": region,
                    "customer_id": customer_id,
                    "monitoring": has_monitoring_tag(tags),
                    "status": "active",
                    "tags": tags
                })
    except ClientError as e:
        logger.error("EFS discovery failed in %s/%s: %s", account_id, region, e)
    return resources


def _discover_opensearch(session, account_id, region, customer_id):
    """OpenSearch 도메인을 인벤토리로 수집한다. _client_id(account)를 tags에 저장."""
    resources = []
    try:
        client = session.client("opensearch")
        names_resp = client.list_domain_names()
    except ClientError as e:
        logger.error("OpenSearch discovery failed in %s/%s: %s", account_id, region, e)
        return resources

    domain_names = [d["DomainName"] for d in names_resp.get("DomainNames", [])]
    for i in range(0, len(domain_names), 5):
        batch = domain_names[i:i + 5]
        try:
            resp = client.describe_domains(DomainNames=batch)
        except ClientError as e:
            logger.error("OpenSearch describe_domains failed: %s", e)
            continue
        for domain in resp.get("DomainStatusList", []):
            if domain.get("Deleted", False):
                continue
            domain_name = domain["DomainName"]
            arn = domain.get("ARN", "")
            tags = {}
            if arn:
                try:
                    tags_resp = client.list_tags(ARN=arn)
                    tags = {t["Key"]: t["Value"] for t in tags_resp.get("TagList", [])}
                except ClientError as e:
                    logger.error("OpenSearch list_tags failed for %s: %s", domain_name, e)
            tags["_client_id"] = account_id
            resources.append({
                "resource_id": domain_name,
                "name": domain_name,
                "type": "OpenSearch",
                "arn": arn,
                "account_id": account_id,
                "region": region,
                "customer_id": customer_id,
                "monitoring": has_monitoring_tag(tags),
                "status": "active",
                "tags": tags
            })
    return resources


def _discover_ecs(session, account_id, region, customer_id):
    """ECS 서비스를 인벤토리로 수집한다 (클러스터별 순회)."""
    resources = []
    try:
        ecs = session.client("ecs")
        cluster_paginator = ecs.get_paginator("list_clusters")
        cluster_pages = list(cluster_paginator.paginate())
    except ClientError as e:
        logger.error("ECS discovery failed in %s/%s: %s", account_id, region, e)
        return resources

    for cluster_page in cluster_pages:
        for cluster_arn in cluster_page.get("clusterArns", []):
            cluster_name = cluster_arn.rsplit("/", 1)[-1]
            _discover_ecs_services(
                ecs, cluster_arn, cluster_name,
                account_id, region, customer_id, resources,
            )
    return resources


def _discover_ecs_services(ecs, cluster_arn, cluster_name, account_id, region,
                           customer_id, resources):
    """단일 ECS 클러스터의 서비스를 수집한다. _cluster_name을 tags에 저장(compound dim)."""
    try:
        svc_paginator = ecs.get_paginator("list_services")
        svc_pages = svc_paginator.paginate(cluster=cluster_arn)
    except ClientError as e:
        logger.error("ECS list_services failed for %s: %s", cluster_arn, e)
        return

    for svc_page in svc_pages:
        svc_arns = svc_page.get("serviceArns", [])
        if not svc_arns:
            continue
        try:
            desc = ecs.describe_services(cluster=cluster_arn, services=svc_arns)
        except ClientError as e:
            logger.error("ECS describe_services failed for %s: %s", cluster_arn, e)
            continue
        for svc in desc.get("services", []):
            svc_arn = svc.get("serviceArn", "")
            svc_name = svc.get("serviceName", "")
            tags = {}
            try:
                tags_resp = ecs.list_tags_for_resource(resourceArn=svc_arn)
                tags = {t["key"]: t["value"] for t in tags_resp.get("tags", [])}
            except ClientError as e:
                logger.error("ECS list_tags failed for %s: %s", svc_arn, e)
            tags["_cluster_name"] = cluster_name
            tags["_ecs_launch_type"] = svc.get("launchType", "")
            resources.append({
                "resource_id": svc_name,
                "name": svc_name,
                "type": "ECS",
                "arn": svc_arn,
                "account_id": account_id,
                "region": region,
                "customer_id": customer_id,
                "monitoring": has_monitoring_tag(tags),
                "status": "active",
                "tags": tags
            })
