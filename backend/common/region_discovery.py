"""고객 계정이 실제로 쓰는 리전 탐지 (2026-10).

계정 표의 `regions`는 사람이 등록 때 고른다. 고객사는 대개 서울(+글로벌용 버지니아)이지만 간혹 다른 리전을 쓰고, 등록에서
빠진 리전의 리소스는 감시 밖이다. 리전마다 Resource Groups Tagging API `GetResources`를 1건만 물어 리소스가 있는 리전을
찾는다 — 고객 역할에 이미 있는 `tag:GetResources`만 쓴다(스택 재배포 불필요). 첫 실고객 실측: 17리전 중 서울·버지니아만 있음.

한계: RGT는 태그가 하나라도 있었던 리소스만 돌려준다. 우리는 Monitoring 태그가 붙은 리소스만 감시하므로 태그가 전혀 없는
리전은 감시 대상도 없다 — 놓치는 게 없다. 옵트인하지 않은 리전(홍콩·중동 등)은 호출이 실패하고 "안 씀"으로 본다.

탐지는 제안만 한다. 계정 `regions`는 사람이 확인해 바꾼다(`PUT /accounts/{id}/regions`) — 예상 못 한 리전을 고객 확인 없이
감시 범위에 넣지 않는다.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

#: 상용 파티션 리전 — 프론트 `AccountSection`의 선택지와 같은 목록.
CANDIDATE_REGIONS: tuple[str, ...] = (
    "us-east-1", "us-east-2", "us-west-1", "us-west-2", "ca-central-1", "ca-west-1", "mx-central-1", "sa-east-1",
    "eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1", "eu-central-2", "eu-north-1", "eu-south-1", "eu-south-2",
    "af-south-1", "il-central-1", "me-central-1", "me-south-1",
    "ap-south-1", "ap-south-2", "ap-east-1", "ap-east-2", "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
    "ap-southeast-1", "ap-southeast-2", "ap-southeast-3", "ap-southeast-4", "ap-southeast-5", "ap-southeast-6",
    "ap-southeast-7",
)

#: 정기 워커가 등록과 무관하게 항상 도는 리전(글로벌 서비스) — 미등록이어도 감시 밖이 아니다.
ALWAYS_COVERED = frozenset({"us-east-1"})

# 옵트인 안 된 리전은 연결이 늦게 실패할 수 있다 — API 요청 안에서 돌므로 짧게 끊는다.
_PROBE_CONFIG = Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1})


def _has_resources(region: str, client) -> bool:
    try:
        resp = client.get_resources(ResourcesPerPage=1)
    except (ClientError, BotoCoreError) as e:
        logger.debug("Region probe skipped for %s: %s", region, e)
        return False
    return bool(resp.get("ResourceTagMappingList"))


@dataclass(frozen=True)
class Detection:
    """탐지 결과 — `regions`: 리소스가 있는 리전(후보 순서), `unchecked`: 기한 안에 답을 못 받은 리전."""
    regions: list[str]
    unchecked: list[str] = field(default_factory=list)


def detect_regions(session_kwargs: dict, regions: tuple[str, ...] = CANDIDATE_REGIONS,
                   deadline: float | None = None) -> Detection:
    """리소스가 있는 리전. `session_kwargs`는 대상 계정 자격증명(우리 계정이면 `{}`).

    세션은 **하나**, 클라이언트는 이 스레드에서 차례로 만든다 — 세션마다 서비스 모델을 따로 읽어 스레드별 세션 34개는
    256MB API 람다를 OOM으로 죽였다(2026-10-12 첫 라이브 호출). 클라이언트 생성은 스레드 안전하지 않지만 호출은 안전하다.

    병렬로 불러도 거의 직렬로 끝난다: 연결마다 CA 번들을 읽는 TLS 설정(urllib3 `ssl_wrap_socket`)이 줄을 선다 —
    리전당 람다 ~0.4초, 34리전 ~14초(1024MB). API 요청 안에서는 `deadline`(초)을 줘 30초 한도를 지키고, 못 끝낸 리전은
    `unchecked`로 돌려준다. 정기 실행은 기한 없이 전부 본다.
    """
    session = boto3.session.Session(**session_kwargs)
    clients = [session.client("resourcegroupstaggingapi", region_name=r, config=_PROBE_CONFIG) for r in regions]
    pool = ThreadPoolExecutor(max_workers=max(1, len(regions)))
    futures = [pool.submit(_has_resources, r, c) for r, c in zip(regions, clients)]
    done, _pending = wait(futures, timeout=deadline)
    # 기한을 넘긴 호출은 기다리지 않는다(남은 스레드는 응답 뒤 버려진다).
    pool.shutdown(wait=False, cancel_futures=True)
    found = [r for r, f in zip(regions, futures) if f in done and f.result()]
    unchecked = [r for r, f in zip(regions, futures) if f not in done]
    if unchecked:
        logger.warning("Region detection hit the %.0fs deadline; unchecked: %s", deadline or 0, unchecked)
    return Detection(found, unchecked)


def unregistered_regions(detected: list[str], registered: list[str]) -> list[str]:
    """리소스가 있는데 감시 밖인 리전 — 등록 리전도, 항상 도는 리전도 아닌 것."""
    covered = set(registered) | ALWAYS_COVERED
    return [r for r in detected if r not in covered]
