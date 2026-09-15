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
- **나열 소스**(P3, docs/specs/resource-type-registry D4): `matching(rgt_filters)`는 프라임된 리소스 중
  필터에 맞고 Monitoring=on인 (ARN, 태그)를 돌려준다. RGT는 태그가 하나라도 있는 리소스를 전부 돌려주므로
  Monitoring=on 리소스는 반드시 그 안에 있다 — 범용 수집기가 서비스별 list/describe 대신 이걸 읽는다.
  비활성이거나 필터의 서비스가 프라임 목록에 없으면 `None`(호출자가 describe 나열로 폴백).
"""

from __future__ import annotations

import logging
import os
from typing import Callable

from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

# ARN의 service 세그먼트. EC2(인스턴스/NAT/VPN)·EFS·MSK·APIGW v2는 describe 응답에
# 태그가 포함되므로 제외 — 프라임 페이로드만 늘린다.
# 프라임할 서비스는 리소스 타입 레지스트리의 `rgt_prime` 스펙에서 파생된다 (docs/specs/resource-type-registry P2).
# 빠진 서비스(ec2 계열·efs)의 이유는 각 스펙의 notes에 있다.
from common.resource_types import tagged_services as _tagged_services  # noqa: E402

TAGGED_SERVICES = _tagged_services()
_RESOURCES_PER_PAGE = 100


class TagCache:
    def __init__(self) -> None:
        self._tags: dict[str, dict] = {}
        self.active = False
        #: 프라임에 쓴 RGT 서비스 — `matching()`이 필터의 서비스가 여기 없으면 None을 돌려준다(빈 결과를 "0개"로 오판하지 않게).
        self.services: frozenset[str] = frozenset()
        self.stats = {"primed": 0, "pages": 0, "hits": 0, "negatives": 0, "matched": 0}

    def __len__(self) -> int:
        return len(self._tags)

    def prime(self, client, *, services: list[str] | None = None) -> bool:
        """GetResources를 페이지 순회해 ARN→태그를 적재. 성공(≥1건) 시 활성화."""
        services = list(services if services is not None else TAGGED_SERVICES)
        count = 0
        try:
            paginator = client.get_paginator("get_resources")
            for page in paginator.paginate(
                ResourceTypeFilters=services,
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
        self.services = frozenset(svc.split(":", 1)[0] for svc in services) if self.active else frozenset()
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

    def matching(
        self, rgt_filters: tuple[str, ...] | list[str], *, tag_key: str = "Monitoring", tag_value: str = "on",
    ) -> list[tuple[str, dict]] | None:
        """프라임된 리소스 중 `rgt_filters`(RGT ResourceTypeFilters 문자열)에 맞고 tag_key=tag_value(대소문자 무시)인
        (ARN, 태그) 목록 — 프라임 순서. 비활성이거나 필터의 서비스가 프라임되지 않았으면 None(폴백 신호)."""
        if not self.active or not rgt_filters:
            return None
        if any(f.split(":", 1)[0] not in self.services for f in rgt_filters):
            return None
        out: list[tuple[str, dict]] = []
        for arn, tags in self._tags.items():
            if not any(arn_matches_filter(arn, f) for f in rgt_filters):
                continue
            if str(tags.get(tag_key, "")).lower() != tag_value:
                continue
            out.append((arn, dict(tags)))
        self.stats["matched"] += len(out)
        return out


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


def cached_matching(rgt_filters: tuple[str, ...] | list[str]) -> list[tuple[str, dict]] | None:
    """활성 캐시의 `matching()` — Monitoring=on 리소스 (ARN, 태그) 목록. 캐시가 없거나 못 쓰면 `None`(describe 나열로 폴백)."""
    cache = _active
    if cache is None:
        return None
    return cache.matching(rgt_filters)


def arn_matches_filter(arn: str, rgt_filter: str) -> bool:
    """ARN이 RGT `ResourceTypeFilters` 문자열에 해당하는가 — `sqs`(서비스 전체) 또는 `lambda:function`(리소스 타입).

    ARN 형식 `arn:partition:service:region:account:resource`; 리소스 타입은 `type/id` 또는 `type:id`로 붙는다
    (API Gateway는 `/restapis/id`처럼 슬래시로 시작한다). S3 버킷처럼 리소스 부분에 타입 접두가 없는 서비스는
    서비스만 있는 필터(`s3`)로 매칭한다.
    """
    parts = arn.split(":", 5)
    if len(parts) != 6 or parts[0] != "arn":
        return False
    service, resource = parts[2], parts[5].lstrip("/")
    svc, _, rtype = rgt_filter.partition(":")
    if service != svc:
        return False
    if not rtype:
        return True
    return resource == rtype or resource.startswith(rtype + "/") or resource.startswith(rtype + ":")


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
        "Tag cache stats (%s): active=%s primed=%d hits=%d negatives=%d matched=%d",
        label, cache.active, cache.stats["primed"], cache.stats["hits"], cache.stats["negatives"],
        cache.stats["matched"],
    )
