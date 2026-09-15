"""
API Gateway 수집기 — REST(v1)·HTTP/WebSocket(v2)을 한 모듈에서, 나열은 describe (docs/specs/resource-type-registry P3)

v2 `get_apis`는 태그와 ProtocolType을 한 콜에 주고, REST는 TagName이 API **이름**이라 ARN(`/restapis/<id>`)만으로는 정체가 안 나온다 —
RGT 나열로 아낄 콜이 REST의 태그 N+1뿐이라 스펙에 `identity`가 없고 이 모듈의 `_enumerate`가 유일한 나열이다(REST 태그는 캐시 히트를
먼저 본다). 내부 태그 `_api_type`(REST/HTTP/WEBSOCKET)이 알람 정의 변형과 디멘션(ApiName/ApiId)을 가른다.
메트릭은 스펙(`common/resource_types/apigw.py`)의 알람 정의에서 만든다. 네임스페이스 AWS/ApiGateway.
"""

import functools
import logging

import boto3
from botocore.exceptions import ClientError

from common.collectors.generic import GenericCollector, session_region
from common.resource_types.apigw import SPEC
from common.tag_cache import cached_tags

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None)
def _get_apigw_client():
    """API Gateway v1 (REST) 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("apigateway")


@functools.lru_cache(maxsize=None)
def _get_apigwv2_client():
    """API Gateway v2 (HTTP/WS) 클라이언트 싱글턴. 테스트 시 cache_clear()로 리셋."""
    return boto3.client("apigatewayv2")


def _enumerate() -> list[tuple[str, dict]]:
    """REST: get_rest_apis + 태그(캐시 → get_tags). HTTP/WS: get_apis(Tags 포함). 한쪽 실패 시 다른 쪽은 계속."""
    region = session_region()
    return _rest_apis(region) + _v2_apis()


def _rest_apis(region: str) -> list[tuple[str, dict]]:
    """REST API (v1). TagName = API 이름. 실패 시 로그 후 빈 목록."""
    try:
        client = _get_apigw_client()
        paginator = client.get_paginator("get_rest_apis")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("APIGW get_rest_apis failed: %s", e)
        return []

    found: list[tuple[str, dict]] = []
    for page in pages:
        for api in page.get("items", []):
            api_id = api["id"]
            tags = dict(_get_rest_api_tags(client, api_id, region))
            if tags.get("Monitoring", "").lower() != "on":
                continue
            tags["_api_type"] = "REST"
            found.append((api.get("name", api_id), tags))
    return found


def _v2_apis() -> list[tuple[str, dict]]:
    """HTTP/WebSocket API (v2). TagName = ApiId, Name 태그가 없으면 API 이름을 넣는다. 실패 시 로그 후 빈 목록."""
    try:
        client = _get_apigwv2_client()
        paginator = client.get_paginator("get_apis")
        pages = paginator.paginate()
    except ClientError as e:
        logger.error("APIGW v2 get_apis failed: %s", e)
        return []

    found: list[tuple[str, dict]] = []
    for page in pages:
        for api in page.get("Items", []):
            tags = dict(api.get("Tags", {}))
            if tags.get("Monitoring", "").lower() != "on":
                continue
            tags["_api_type"] = "WEBSOCKET" if api.get("ProtocolType", "HTTP") == "WEBSOCKET" else "HTTP"
            api_name = api.get("Name", "")
            if api_name:
                tags.setdefault("Name", api_name)
            found.append((api["ApiId"], tags))
    return found


def _alive(tag_names: set[str]) -> set[str]:
    """알람 TagName 집합에서 실제 AWS API Gateway가 존재하는 TagName 부분집합 반환.

    composite TagName ('{api_name}/{api_id}' 형식, '/'포함):
        마지막 '/' 기준으로 분리하여 api_id를 추출하고 v2 API (HTTP/WS)의
        ApiId와 비교한다.
    non-composite TagName ('/' 미포함):
        REST API 이름으로 간주하고 get_rest_apis 결과의 name과 비교한다.
    """
    if not tag_names:
        return set()

    composite: dict[str, str] = {}   # api_id -> original tag_name
    rest_names: dict[str, str] = {}  # api_name -> original tag_name
    for tag_name in tag_names:
        if "/" in tag_name:
            composite[tag_name.rsplit("/", 1)[1]] = tag_name
        else:
            rest_names[tag_name] = tag_name

    alive: set[str] = set()
    if composite:
        try:
            v2 = _get_apigwv2_client()
            for page in v2.get_paginator("get_apis").paginate():
                for api in page.get("Items", []):
                    if api["ApiId"] in composite:
                        alive.add(composite[api["ApiId"]])
        except ClientError as e:
            logger.error("APIGW v2 get_apis failed: %s", e)

    if rest_names:
        try:
            client = _get_apigw_client()
            for page in client.get_paginator("get_rest_apis").paginate():
                for api in page.get("items", []):
                    name = api.get("name", "")
                    if name in rest_names:
                        alive.add(rest_names[name])
        except ClientError as e:
            logger.error("APIGW get_rest_apis failed: %s", e)
    return alive


def _get_rest_api_tags(apigw_client, api_id: str, region: str) -> dict:
    """REST API 태그 — 태그 캐시 히트 우선, 없으면 get_tags(). ClientError 시 빈 dict 반환."""
    # REST API ARN: arn:aws:apigateway:{region}::/restapis/{api_id}
    arn = f"arn:aws:apigateway:{region}::/restapis/{api_id}"
    cached = cached_tags(arn)
    if cached is not None:
        return cached
    try:
        response = apigw_client.get_tags(resourceArn=arn)
        return response.get("tags", {})
    except ClientError as e:
        logger.error("APIGW get_tags failed for %s: %s", api_id, e)
        return {}


COLLECTOR = GenericCollector(SPEC, alive=_alive, enumerate=_enumerate)
collect_monitored_resources = COLLECTOR.collect_monitored_resources
get_metrics = COLLECTOR.get_metrics
resolve_alive_ids = COLLECTOR.resolve_alive_ids
