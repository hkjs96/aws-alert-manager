"""
Shared boto3 client singletons — 모든 모듈에서 동일한 캐시된 클라이언트를 사용.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_cw_client():
    return boto3.client("cloudwatch")


@functools.lru_cache(maxsize=None)
def _get_cw_client_for_region(region_name: str):
    """특정 리전의 CloudWatch 클라이언트 싱글턴 (글로벌 서비스용)."""
    return boto3.client("cloudwatch", region_name=region_name)


def create_clients_for_account(
    role_arn: str,
    session_name: str = "MonitoringEngine",
) -> dict[str, object]:
    """STS AssumeRole로 대상 계정의 boto3 클라이언트 세트 생성.

    Returns:
        {"cw": cloudwatch_client, "ec2": ec2_client, "rds": rds_client, "elbv2": elbv2_client}

    Raises:
        ClientError: IAM 권한 없음 또는 Role ARN이 잘못된 경우
        ValueError: role_arn이 비어 있는 경우
    """
    if not role_arn:
        raise ValueError("role_arn must not be empty")

    sts = boto3.client("sts")
    try:
        response = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName=session_name,
        )
    except ClientError as e:
        logger.error(
            "Failed to assume role %s (session=%s): %s", role_arn, session_name, e
        )
        raise

    creds = response["Credentials"]
    kwargs = {
        "aws_access_key_id": creds["AccessKeyId"],
        "aws_secret_access_key": creds["SecretAccessKey"],
        "aws_session_token": creds["SessionToken"],
    }
    return {
        "cw": boto3.client("cloudwatch", **kwargs),
        "ec2": boto3.client("ec2", **kwargs),
        "rds": boto3.client("rds", **kwargs),
        "elbv2": boto3.client("elbv2", **kwargs),
    }
