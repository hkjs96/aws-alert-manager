"""
런 스코프 태그 캐시 — Resource Groups Tagging API `GetResources` 일괄 프라임.

컬렉터(`collect_monitored_resources`)와 인벤토리 디스커버리는 리소스마다 태그 API를
1회씩 부른다(N+1: 리소스 200개 기준 ~900콜/런). RGT `GetResources`는 한 콜에 100개
리소스의 태그를 돌려주므로, 리전당 몇 콜로 프라임한 뒤 ARN으로 메모리 조회한다.

의미론
- **프라임 성공(≥1건)** → 활성. `cached_tags(arn)`은 태그 dict를, 목록에 없는 ARN은 `{}`를
  돌려준다 — RGT는 "태그가 하나라도 있는 리소스"를 모두 반환하므로 부재 = 태그 없음.
- **프라임 실패/0건** → 비활성. `cached_tags()`는 `None`을 돌려주고 호출자는 기존 리소스별
  API로 폴백한다. 즉 IAM(`tag:GetResources`) 미부여 고객사에서도 동작은 예전과 같다.
- 리전 불일치 위험이 있는 글로벌/크로스리전 조회(S3 버킷, CloudFront, Route53)는
  `trust_negative=False`로 히트만 쓰고 부재는 폴백한다.
- 최종 일관성: RGT는 태그 변경 직후 수 분간 이전 상태를 돌려줄 수 있다. daily run은
  하루 1회 정합 경로이고 태그 변경 즉시 반영은 remediation(CloudTrail) 경로가 맡으므로
  허용한다. 킬 스위치: 환경변수 `TAG_CACHE=off`.
"""

from __future__ import annotations

import logging
import os
from typing import Callable

from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

# ARN의 service 세그먼트. EC2(인스턴스/NAT/VPN)·EFS·MSK·APIGW v2는 describe 응답에
# 태그가 포함되므로 제외 — 프라임 페이로드만 늘린다.
TAGGED_SERVICES = [
    "rds", "elasticloadbalancing", "elasticache", "lambda", "sqs", "dynamodb",
    "es", "ecs", "apigateway", "acm", "backup", "mq", "kafka", "wafv2",
    "directconnect", "sagemaker", "sns", "cloudfront", "route53", "s3",
]
_RESOURCES_PER_PAGE = 100


class TagCache:
    def __init__(self) -> None:
        self._tags: dict[str, dict] = {}
        self.active = False
        self.stats = {"primed": 0, "pages": 0, "hits": 0, "negatives": 0}

    def __len__(self) -> int:
        return len(self._tags)

    def prime(self, client) -> bool:
        """GetResources를 페이지 순회해 ARN→태그를 적재. 성공(≥1건) 시 활성화."""
        count = 0
        try:
            paginator = client.get_paginator("get_resources")
            for page in paginator.paginate(
                ResourceTypeFilters=TAGGED_SERVICES,
                ResourcesPerPage=_RESOURCES_PER_PAGE,
            ):
                self.stats["pages"] += 1
                for mapping in page.get("ResourceTagMappingList", []) or []:
                    arn = mapping.get("ResourceARN")
                    if not arn:
                        continue
                    self._tags[arn] = {
                        t["Key"]: t["Value"] for t in mapping.get("Tags", []) or []
                    }
                    count += 1
        except (ClientError, BotoCoreError) as e:
            logger.warning("Tag cache prime failed (falling back to per-resource tag APIs): %s", e)
            self.active = False
            return False
        self.stats["primed"] = count
        self.active = count > 0
        return self.active

    def lookup(self, arn: str, *, trust_negative: bool = True) -> dict | None:
        if not self.active or not arn:
            return None
        tags = self._tags.get(arn)
        if tags is not None:
            self.stats["hits"] += 1
            return dict(tags)
        if trust_negative:
            self.stats["negatives"] += 1
            return {}
        return None


_active: TagCache | None = None


def set_active_tag_cache(cache: TagCache | None) -> None:
    global _active
    _active = cache


def get_active_tag_cache() -> TagCache | None:
    return _active


def cached_tags(arn: str, *, trust_negative: bool = True) -> dict | None:
    """활성 캐시가 있으면 arn의 태그(부재 시 `{}`), 없으면 `None`(호출자가 API 폴백)."""
    cache = _active
    if cache is None:
        return None
    return cache.lookup(arn, trust_negative=trust_negative)


def prime_tag_cache(client_factory: Callable[[], object], *, label: str = "") -> TagCache:
    """새 캐시를 만들어 프라임하고 활성 캐시로 등록한다. 실패해도 예외를 내지 않는다."""
    cache = TagCache()
    if os.environ.get("TAG_CACHE", "").lower() == "off":
        logger.info("Tag cache disabled by TAG_CACHE=off (%s)", label)
        set_active_tag_cache(cache)
        return cache
    try:
        client = client_factory()
    except (ClientError, BotoCoreError) as e:
        logger.warning("Tag cache client unavailable (%s): %s", label, e)
        set_active_tag_cache(cache)
        return cache
    cache.prime(client)
    logger.info(
        "Tag cache primed (%s): %d resources in %d GetResources calls, active=%s",
        label, cache.stats["primed"], cache.stats["pages"], cache.active,
    )
    set_active_tag_cache(cache)
    return cache


def log_tag_cache_stats(label: str = "") -> None:
    cache = _active
    if cache is None:
        return
    logger.info(
        "Tag cache stats (%s): active=%s primed=%d hits=%d negatives=%d",
        label, cache.active, cache.stats["primed"], cache.stats["hits"], cache.stats["negatives"],
    )
