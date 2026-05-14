"""
verify-alarms.py — extended-resources-e2e-test 스택 알람 검증 스크립트

1. CFN Outputs에서 리소스 ID 조회
2. 예상 알람 vs 실제 CloudWatch 알람 비교 → 누락 알람 목록 출력
3. 누락 알람이 있으면 create_alarms_for_resource로 강제 생성 (--force-create)
4. 트래픽 생성 (traffic-test.sh 실행, --skip-traffic으로 스킵 가능)
5. 대기 후 알람 상태 재검증 및 리소스 타입별 집계 리포트
"""

import argparse
import functools
import logging
import os
import subprocess
import sys
import time

import boto3
from botocore.exceptions import ClientError

# 프로젝트 루트를 sys.path에 추가 (common.* import용)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from common.alarm_manager import create_alarms_for_resource  # pylint: disable=wrong-import-position
from common.alarm_registry import _METRIC_DISPLAY  # pylint: disable=wrong-import-position
from common.alarm_search import _find_alarms_for_resource  # pylint: disable=wrong-import-position

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────

DEFAULT_STACK_NAME = "extended-resources-e2e-test"
DEFAULT_PROFILE = "jordy_poc"
DEFAULT_REGION = "ap-northeast-2"

# CloudFront/Route53 알람은 us-east-1에 생성됨
_GLOBAL_REGION = "us-east-1"
_GLOBAL_RESOURCE_TYPES = {"CloudFront", "Route53"}

# CFN Output 키 → (resource_type, resource_id_field)
_OUTPUT_RESOURCE_MAP: dict[str, tuple[str, str]] = {
    "SqsQueueName":              ("SQS",          "queue_name"),
    "EcsClusterName":            ("ECS",          "_cluster_name"),
    "EcsServiceName":            ("ECS",          "service_name"),
    "MskClusterName":            ("MSK",          "cluster_name"),
    "DynamoDBTableName":         ("DynamoDB",     "table_name"),
    "CloudFrontDistributionId":  ("CloudFront",   "distribution_id"),
    "WafWebAclName":             ("WAF",          "web_acl_name"),
    "Route53HealthCheckId":      ("Route53",      "health_check_id"),
    "EfsFileSystemId":           ("EFS",          "file_system_id"),
    "S3BucketName":              ("S3",           "bucket_name"),
    "SageMakerEndpointName":     ("SageMaker",    "endpoint_name"),
    "SnsTopicName":              ("SNS",          "topic_name"),
}

# 트래픽 테스트용 Output 키
_TRAFFIC_OUTPUT_KEYS = [
    "SqsQueueUrl",
    "DynamoDBTableName",
    "CloudFrontDomainName",
    "WafAlbDns",
    "S3BucketName",
    "SnsTopicArn",
]

# 예상 알람 메트릭 키 목록 (resource_type → metric keys)
EXPECTED_ALARMS: dict[str, list[str]] = {
    "SQS":         ["SQSMessagesVisible", "SQSOldestMessage", "SQSMessagesSent"],
    "ECS":         ["EcsCPU", "EcsMemory", "RunningTaskCount"],
    "MSK":         ["OffsetLag", "BytesInPerSec", "UnderReplicatedPartitions", "ActiveControllerCount"],
    "DynamoDB":    ["DDBReadCapacity", "DDBWriteCapacity", "ThrottledRequests", "DDBSystemErrors"],
    "CloudFront":  ["CF5xxErrorRate", "CF4xxErrorRate", "CFRequests", "CFBytesDownloaded"],
    "WAF":         ["WAFBlockedRequests", "WAFAllowedRequests", "WAFCountedRequests"],
    "Route53":     ["HealthCheckStatus"],
    "EFS":         ["BurstCreditBalance", "PercentIOLimit", "EFSClientConnections"],
    "S3":          ["S34xxErrors", "S35xxErrors", "S3BucketSizeBytes", "S3NumberOfObjects"],
    "SageMaker":   ["SMInvocations", "SMInvocationErrors", "SMModelLatency", "SMCPU"],
    "SNS":         ["SNSNotificationsFailed", "SNSMessagesPublished"],
}

# ──────────────────────────────────────────────
# boto3 클라이언트 싱글턴
# ──────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def _get_cfn_client(profile: str, region: str):
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("cloudformation")


@functools.lru_cache(maxsize=None)
def _get_cw_client(profile: str, region: str):
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("cloudwatch")


# ──────────────────────────────────────────────
# Step 1: CFN Outputs 조회
# ──────────────────────────────────────────────

def fetch_cfn_outputs(stack_name: str, profile: str, region: str) -> dict[str, str]:
    """CFN 스택 Outputs를 {key: value} 딕셔너리로 반환."""
    cfn = _get_cfn_client(profile, region)
    try:
        resp = cfn.describe_stacks(StackName=stack_name)
    except ClientError as e:
        logger.error("Failed to describe stack %s: %s", stack_name, e)
        raise

    stacks = resp.get("Stacks", [])
    if not stacks:
        raise RuntimeError(f"Stack not found: {stack_name}")

    outputs = {}
    for item in stacks[0].get("Outputs", []):
        outputs[item["OutputKey"]] = item["OutputValue"]
    return outputs


def print_cfn_outputs(stack_name: str, outputs: dict[str, str]) -> None:
    """CFN 스택 이름과 Outputs 키-값 쌍을 콘솔에 출력."""
    print("\n=== Step 1: Fetching CFN Outputs ===")
    print(f"Stack: {stack_name}")
    for k, v in outputs.items():
        print(f"  {k}: {v}")


# ──────────────────────────────────────────────
# Step 2: 알람 확인
# ──────────────────────────────────────────────

def _build_resource_list(outputs: dict[str, str]) -> list[tuple[str, str, dict]]:
    """
    CFN Outputs에서 (resource_type, resource_id, resource_tags) 목록 생성.
    ECS는 cluster_name 태그가 필요하므로 별도 처리.
    """
    resources: list[tuple[str, str, dict]] = []
    ecs_cluster = outputs.get("EcsClusterName", "")

    for output_key, (resource_type, _) in _OUTPUT_RESOURCE_MAP.items():
        value = outputs.get(output_key)
        if not value:
            logger.warning("Output key %s not found in stack outputs", output_key)
            continue

        # ECS: cluster_name 태그는 resource_id로 쓰지 않음 (service_name이 resource_id)
        if output_key == "EcsClusterName":
            continue

        tags: dict[str, str] = {
            "Monitoring": "on",
            "Name": value,
        }
        if resource_type == "ECS" and ecs_cluster:
            tags["_cluster_name"] = ecs_cluster

        # MSK: MskClusterName Output이 ARN을 반환하는 경우 cluster name만 추출
        if resource_type == "MSK" and value.startswith("arn:"):
            # arn:aws:kafka:...:cluster/{name}/{uuid} → {name}
            parts = value.split("/")
            if len(parts) >= 2:
                value = parts[1]
                tags["Name"] = value

        resources.append((resource_type, value, tags))

    return resources


def _check_single_resource(
    resource_type: str,
    resource_id: str,
    profile: str,
    region: str,
) -> tuple[int, int, list[str]]:
    """단일 리소스 알람 확인. (expected_count, found_count, missing_keys) 반환."""
    expected_keys = EXPECTED_ALARMS.get(resource_type, [])
    cw_region = _GLOBAL_REGION if resource_type in _GLOBAL_RESOURCE_TYPES else region
    cw = _get_cw_client(profile, cw_region)
    alarm_names = _find_alarms_for_resource(resource_id, resource_type, cw=cw)
    found_keys = _match_found_keys(alarm_names, expected_keys)
    missing_keys = [k for k in expected_keys if k not in found_keys]
    return len(expected_keys), len(expected_keys) - len(missing_keys), missing_keys


def _print_resource_alarm_status(
    resource_type: str,
    resource_id: str,
    expected: int,
    found: int,
    missing_keys: list[str],
) -> None:
    """단일 리소스 알람 상태 출력."""
    status = "✓" if not missing_keys else "✗"
    missing_str = f" (missing: {', '.join(missing_keys)})" if missing_keys else ""
    print(f"[{resource_type}] {resource_id}: {found}/{expected} alarms found {status}{missing_str}")


def check_alarms(
    resources: list[tuple[str, str, dict]],
    profile: str,
    region: str,
) -> dict[tuple[str, str], list[str]]:
    """각 리소스의 실제 알람을 조회하고 누락 메트릭 키 목록을 반환."""
    print("\n=== Step 2: Checking Alarms ===")
    missing_map: dict[tuple[str, str], list[str]] = {}
    total_expected = 0
    total_found = 0

    for resource_type, resource_id, _ in resources:
        exp, found, missing_keys = _check_single_resource(
            resource_type, resource_id, profile, region
        )
        total_expected += exp
        total_found += found
        _print_resource_alarm_status(resource_type, resource_id, exp, found, missing_keys)
        if missing_keys:
            missing_map[(resource_type, resource_id)] = missing_keys

    print(f"\nTotal: {total_found}/{total_expected} alarms found. Missing: {total_expected - total_found}")
    return missing_map


def _match_found_keys(alarm_names: list[str], expected_keys: list[str]) -> set[str]:
    """알람 이름 목록에서 expected_keys 중 포함된 것을 반환.

    알람 이름 포맷: [TYPE] label CW_metric_name > threshold (TagName: id)
    _METRIC_DISPLAY[key][0]이 실제 CW 메트릭 이름이므로 이를 기준으로 매칭.
    """
    found: set[str] = set()
    lower_names = [n.lower() for n in alarm_names]
    for key in expected_keys:
        # _METRIC_DISPLAY에서 CW 메트릭 이름 조회, 없으면 key 자체 사용
        cw_metric = _METRIC_DISPLAY.get(key, (key,))[0].lower()
        if any(cw_metric in name for name in lower_names):
            found.add(key)
    return found


# ──────────────────────────────────────────────
# Step 3: 누락 알람 강제 생성
# ──────────────────────────────────────────────

def _set_aws_env(profile: str, region: str) -> None:
    """AWS 환경변수 설정 및 _clients 캐시 클리어."""
    os.environ["AWS_PROFILE"] = profile
    os.environ["AWS_DEFAULT_REGION"] = region
    import common._clients as _clients_mod  # pylint: disable=import-outside-toplevel
    _clients_mod._get_cw_client.cache_clear()


def create_missing_alarms(
    missing_map: dict[tuple[str, str], list[str]],
    resources: list[tuple[str, str, dict]],
    profile: str,
    region: str,
) -> None:
    """누락 알람이 있는 리소스에 대해 create_alarms_for_resource 호출.

    alarm_builder 내부가 _clients._get_cw_client()를 직접 사용하므로
    환경변수 + 캐시 클리어 방식으로 리전을 전환한다.
    """
    print("\n=== Step 3: Creating Missing Alarms ===")
    if not missing_map:
        print("No missing alarms. Skipping.")
        return

    tags_by_id: dict[str, dict] = {rid: tags for _, rid, tags in resources}

    for (resource_type, resource_id) in missing_map:
        print(f"Creating alarms for {resource_type} {resource_id}...")
        tags = tags_by_id.get(resource_id, {"Monitoring": "on", "Name": resource_id})
        cw_region = _GLOBAL_REGION if resource_type in _GLOBAL_RESOURCE_TYPES else region
        _set_aws_env(profile, cw_region)
        try:
            created = create_alarms_for_resource(resource_id, resource_type, tags)
            for name in created:
                print(f"  Created: {name}")
        except ClientError as e:
            logger.error(
                "Failed to create alarms for %s %s: %s", resource_type, resource_id, e
            )

    # 원래 리전으로 복원
    _set_aws_env(profile, region)


# ──────────────────────────────────────────────
# Step 4: 트래픽 생성
# ──────────────────────────────────────────────

def run_traffic_test(outputs: dict[str, str], profile: str) -> None:
    """traffic-test.sh 실행."""
    print("\n=== Step 4: Running Traffic Test ===")
    script_path = os.path.join(_SCRIPT_DIR, "traffic-test.sh")

    args = [
        outputs.get("SqsQueueUrl", ""),
        outputs.get("DynamoDBTableName", ""),
        outputs.get("CloudFrontDomainName", ""),
        outputs.get("WafAlbDns", ""),
        outputs.get("S3BucketName", ""),
        outputs.get("SnsTopicArn", ""),
    ]

    missing = [k for k, v in zip(_TRAFFIC_OUTPUT_KEYS, args) if not v]
    if missing:
        logger.warning("Missing traffic test outputs: %s", missing)

    env = os.environ.copy()
    env["AWS_PROFILE"] = profile

    result = subprocess.run(
        ["bash", script_path] + args,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        logger.warning("traffic-test.sh exited with code %d", result.returncode)


# ──────────────────────────────────────────────
# Step 5: 알람 상태 리포트
# ──────────────────────────────────────────────

def _get_alarm_states(
    resource_type: str,
    resource_id: str,
    profile: str,
    region: str,
) -> dict[str, int]:
    """리소스의 알람 상태별 카운트 반환."""
    cw_region = _GLOBAL_REGION if resource_type in _GLOBAL_RESOURCE_TYPES else region
    cw = _get_cw_client(profile, cw_region)
    alarm_names = _find_alarms_for_resource(resource_id, resource_type, cw=cw)
    counts = {"OK": 0, "ALARM": 0, "INSUFFICIENT_DATA": 0}
    if not alarm_names:
        return counts

    for i in range(0, len(alarm_names), 100):
        batch = alarm_names[i:i + 100]
        try:
            resp = cw.describe_alarms(AlarmNames=batch)
            for alarm in resp.get("MetricAlarms", []):
                state = alarm.get("StateValue", "INSUFFICIENT_DATA")
                if state in counts:
                    counts[state] += 1
        except ClientError as e:
            logger.error(
                "Failed to describe alarms for %s %s: %s", resource_type, resource_id, e
            )
    return counts


def print_alarm_status_report(
    resources: list[tuple[str, str, dict]],
    profile: str,
    region: str,
    wait_seconds: int,
) -> None:
    """대기 후 알람 상태 리포트 출력."""
    if wait_seconds > 0:
        print(f"\nWaiting {wait_seconds}s for metrics to propagate...")
        time.sleep(wait_seconds)

    print(f"\n=== Step 5: Alarm Status Report (after {wait_seconds}s wait) ===")
    header = f"{'Resource Type':<14} | {'OK':>4} | {'ALARM':>7} | {'INSUFFICIENT_DATA':>18}"
    print(header)
    print("-" * len(header))

    totals = {"OK": 0, "ALARM": 0, "INSUFFICIENT_DATA": 0}
    seen: set[tuple[str, str]] = set()

    for resource_type, resource_id, _ in resources:
        key = (resource_type, resource_id)
        if key in seen:
            continue
        seen.add(key)

        counts = _get_alarm_states(resource_type, resource_id, profile, region)
        for state, cnt in counts.items():
            totals[state] += cnt
        print(
            f"{resource_type:<14} | {counts['OK']:>4} | {counts['ALARM']:>7} | "
            f"{counts['INSUFFICIENT_DATA']:>18}"
        )

    print("-" * len(header))
    print(
        f"Total: {totals['OK']} OK, {totals['ALARM']} ALARM, "
        f"{totals['INSUFFICIENT_DATA']} INSUFFICIENT_DATA"
    )


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify CloudWatch alarms for extended-resources-e2e-test stack"
    )
    parser.add_argument("--stack-name", default=DEFAULT_STACK_NAME)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument(
        "--skip-traffic", action="store_true",
        help="Skip traffic generation (alarm status check only)"
    )
    parser.add_argument(
        "--force-create", action="store_true",
        help="Force-create missing alarms via create_alarms_for_resource"
    )
    parser.add_argument(
        "--wait-seconds", type=int, default=60,
        help="Seconds to wait after traffic test before status report (default: 60)"
    )
    return parser.parse_args()


def main() -> None:
    """CLI 진입점: CFN Outputs 조회 → 알람 확인 → 생성 → 트래픽 → 상태 리포트."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    args = _parse_args()

    # Step 1: CFN Outputs 조회
    outputs = fetch_cfn_outputs(args.stack_name, args.profile, args.region)
    print_cfn_outputs(args.stack_name, outputs)

    # 리소스 목록 구성
    resources = _build_resource_list(outputs)

    # Step 2: 알람 확인
    missing_map = check_alarms(resources, args.profile, args.region)

    # Step 3: 누락 알람 강제 생성
    if args.force_create:
        create_missing_alarms(missing_map, resources, args.profile, args.region)
    elif missing_map:
        print("\n=== Step 3: Creating Missing Alarms ===")
        print("Skipped (use --force-create to create missing alarms)")

    # Step 4: 트래픽 생성
    if not args.skip_traffic:
        run_traffic_test(outputs, args.profile)
    else:
        print("\n=== Step 4: Running Traffic Test ===")
        print("Skipped (--skip-traffic)")

    # Step 5: 알람 상태 리포트
    wait = args.wait_seconds if not args.skip_traffic else 0
    print_alarm_status_report(resources, args.profile, args.region, wait)


if __name__ == "__main__":
    main()
