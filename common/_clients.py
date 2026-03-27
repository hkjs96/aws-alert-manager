"""
Shared boto3 client singletons — 모든 모듈에서 동일한 캐시된 클라이언트를 사용.
"""

import functools

import boto3


@functools.lru_cache(maxsize=None)
def _get_cw_client():
    return boto3.client("cloudwatch")


def create_clients_for_account(
    role_arn: str,
    session_name: str = "MonitoringEngine",
) -> dict[str, object]:
    """STS AssumeRole로 대상 계정의 boto3 클라이언트 세트 생성.

    Returns:
        {"cw": cloudwatch_client, "ec2": ec2_client, "rds": rds_client, "elbv2": elbv2_client}
    """
    sts = boto3.client("sts")
    creds = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName=session_name,
    )["Credentials"]
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
