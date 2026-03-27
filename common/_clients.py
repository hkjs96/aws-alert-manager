"""
Shared boto3 client singletons — 모든 모듈에서 동일한 캐시된 클라이언트를 사용.
"""

import functools

import boto3


@functools.lru_cache(maxsize=None)
def _get_cw_client():
    return boto3.client("cloudwatch")
