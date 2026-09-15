"""
범용 수집기 — 나열은 RGT(태그 캐시), 메트릭은 알람 정의에서, 존재 확인은 서비스 describe (docs/specs/resource-type-registry D4)

2026-09까지 수집기 26개는 같은 뼈대의 복제였다: 서비스 list → 리소스마다 태그 API(N+1) → Monitoring=on 필터 →
ResourceInfo, 그리고 알람 정의와 똑같은 (네임스페이스·메트릭·stat) 셋을 다시 적은 `get_metrics`. 이 모듈이 그 뼈대 한 벌이다.
타입별 수집기 모듈에는 **환원 불가능한 것**만 남는다:

  - `_enumerate() -> [(TagName, tags)]` : 태그 캐시가 없을 때(IAM `tag:GetResources` 미부여·`TAG_CACHE=off`·프라임 실패)의
    서비스 describe 나열. 옛 코드 그대로 — 폴백이므로 동작이 같아야 한다.
  - `_alive(names) -> set`             : 알람 TagName 중 실제 존재하는 것. RGT는 "태그 있는 리소스"만 돌려주므로 태그가 벗겨진
    리소스를 고아로 오판한다 — 존재 증명은 서비스 API여야 한다(D4).
  - `_get_<svc>_client` (lru_cache)    : daily_monitor가 계정 전환 시 `_get*client`를 훑어 비운다. 테스트도 이 이름을 패치한다.

나열 순서: `spec.identity`(ARN → TagName, 순수)가 있고 `rgt_prime`이면 활성 태그 캐시의 `matching(rgt_filters)`를 읽는다 —
서비스 API 콜 0. 캐시가 없으면 `_enumerate`. 메트릭은 `spec.alarms(tags)`의 정의를 그대로 `collect_metric`에 넘긴다 —
정의가 이미 namespace·metric_name·dimension_key·stat을 갖고 있고 `MetricBatch`(record→execute→serve)가 그 관문이다.

RGT 경로는 최종 일관성이다(태그 변경 후 수 분). daily run은 하루 1회 정합 경로이고 즉시 반영은 remediation(CloudTrail)이
맡으므로 허용한다(`tag_cache` 모듈 문서). 킬 스위치 `TAG_CACHE=off` → 모든 타입이 `_enumerate`로 돈다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

import boto3

from common import ResourceInfo
from common.collectors.base import CW_LOOKBACK_MINUTES, collect_metric
from common.dimension_builder import _build_dimensions
from common.resource_types.base import ResourceTypeSpec
from common.tag_cache import cached_matching

logger = logging.getLogger(__name__)

#: describe 나열 — (TagName, 태그) 후보 목록. Monitoring 필터는 수집기가 다시 건다(미리 걸어도 된다: MQ처럼 후속 describe를
#: 아끼려면 걸어라). 서비스 list 실패는 ClientError로 올린다 — daily_monitor가 잡아 오류 알림을 보낸다.
#: 한 모듈이 타입 여럿을 내면(rds → RDS·AuroraRDS, elb → ALB·NLB·TG) 세 번째 원소로 타입 이름을 준다.
Enumerate = Callable[[], "list[tuple[str, dict] | tuple[str, dict, str]]"]
#: 알람 TagName 집합 → 실제 존재하는 부분집합.
Alive = Callable[[set[str]], set[str]]
#: (ARN, 태그) → [(TagName, 태그)] — 한 리소스가 여러 TagName이 되거나(MQ `{broker}-{1|2}`) 태그를 덧붙일 때만 모듈이 준다.
#: 보통은 `spec.identity`(ARN → TagName)로 충분하다.
Identities = Callable[[str, dict], list[tuple[str, dict]]]
#: 정의 기반 `get_metrics`를 대신하는 타입 고유 조회 — 정의로 표현되지 않는 것이 있을 때만(EC2 CWAgent 디스크 경로 발견,
#: RDS 계열의 GB 변환·개명 전 결과 키, ELB의 `lb_arn` 인자, CloudFront의 us-east-1 전용 클라이언트). 이유는 모듈 문서에.
Metrics = Callable[..., "dict[str, float] | None"]


def session_region() -> str:
    """기본 세션의 리전 — 옛 수집기들이 ResourceInfo.region에 넣던 값 그대로."""
    return boto3.session.Session().region_name or "us-east-1"


def is_monitored(tags: dict) -> bool:
    """옛 수집기 26개가 쓰던 필터 그대로: Monitoring=on (값은 대소문자 무시)."""
    return str(tags.get("Monitoring", "")).lower() == "on"


class GenericCollector:
    """`CollectorProtocol` 구현. 모듈은 `COLLECTOR = GenericCollector(SPEC, alive=…, enumerate=…)` 뒤 세 메서드를 모듈 이름에 묶는다."""

    def __init__(
        self,
        spec: ResourceTypeSpec,
        *,
        alive: Alive,
        enumerate: Enumerate | None = None,
        identities: Identities | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        if identities is None and spec.identity is not None:
            ident = spec.identity
            identities = lambda arn, tags: [(ident(arn), tags)]  # noqa: E731
        if identities is None and enumerate is None:
            raise ValueError(f"{spec.type}: needs spec.identity/identities (RGT path) or enumerate (describe path)")
        self.spec = spec
        self._alive = alive
        self._enumerate = enumerate
        self._identities = identities
        self._metrics = metrics
        #: 마지막 수집이 어느 경로였나 — "rgt" | "enumerate" | "none". 런 로그·테스트용.
        self.last_source = ""

    @property
    def rgt_capable(self) -> bool:
        """태그 캐시로 나열할 수 있는가 — ARN→TagName 규칙이 있고 캐시가 이 서비스를 프라임하는가."""
        return self._identities is not None and self.spec.rgt_prime

    # ── CollectorProtocol ──

    def collect_monitored_resources(self) -> list[ResourceInfo]:
        region = session_region()
        rtype = self.spec.type
        if self.rgt_capable:
            found = cached_matching(self.spec.rgt_filters)
            if found is not None:
                self.last_source = "rgt"
                resources: list[ResourceInfo] = []
                for arn, tags in found:
                    for tag_name, rtags in self._identities(arn, tags):
                        resources.append(ResourceInfo(id=tag_name, type=rtype, tags=rtags, region=region))
                logger.info("%s: %d monitored resources via tag cache (%s)", rtype, len(resources), ", ".join(self.spec.rgt_filters))
                return resources
        if self._enumerate is None:
            # identity만 있고 폴백 나열이 없는 타입에서 캐시가 죽었다 — 빈 결과를 조용히 내지 않는다.
            logger.warning("%s: tag cache inactive and no describe enumeration; collecting nothing", rtype)
            self.last_source = "none"
            return []
        self.last_source = "enumerate"
        resources = []
        for tag_name, tags, *typed in self._enumerate():
            if is_monitored(tags):
                resources.append(ResourceInfo(id=tag_name, type=typed[0] if typed else rtype, tags=tags, region=region))
        return resources

    @property
    def metrics_from_definitions(self) -> bool:
        """`get_metrics`가 알람 정의에서 생성되는가(False면 모듈의 타입 고유 조회 — 이유는 모듈 문서)."""
        return self._metrics is None

    def get_metrics(self, resource_id: str, resource_tags: dict | None = None, **kwargs) -> dict[str, float] | None:
        """알람 정의(태그 조건부 변형 반영)마다 CloudWatch 최근값 — 키는 정의의 `metric_key`(없으면 `metric`).

        옛 타입별 `get_metrics`가 하던 일은 이 셋을 나열하는 것뿐이었다. 태그 조건부(옵트인 포함) 정의는 `alarms(tags)`가
        이미 가른다 — 정의가 나오면 그 리소스는 그 알람을 갖고 있으니 메트릭도 본다. 디멘션은 **알람이 쓰는 것과 같은
        빌더**(`dimension_builder._build_dimensions`: OpenSearch ClientId·SageMaker VariantName·ECS ClusterName 같은 복합
        디멘션을 내부 태그에서 읽는다)로 만든다 — 메트릭과 알람이 다른 시리즈를 보는 일이 없게. 데이터가 하나도 없으면 None.
        모듈이 `metrics=`를 줬으면 그쪽으로(추가 인자 — ELB `lb_arn` — 그대로 전달).
        """
        if self._metrics is not None:
            return self._metrics(resource_id, resource_tags, **kwargs)
        if kwargs:
            raise TypeError(f"{self.spec.type}: definition-based get_metrics takes no extra arguments ({', '.join(kwargs)})")
        resource_tags = resource_tags or {}
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=CW_LOOKBACK_MINUTES)
        metrics: dict[str, float] = {}
        for d in self.spec.alarms(resource_tags):
            key = d.get("metric_key") or d["metric"]
            dims = _build_dimensions(d, resource_id, self.spec.type, resource_tags)
            collect_metric(d["namespace"], d["metric_name"], dims, start_time, end_time, key, metrics,
                           stat=d["stat"], resource_label=self.spec.type)
        return metrics if metrics else None

    def resolve_alive_ids(self, tag_names: set[str]) -> set[str]:
        return self._alive(tag_names)
