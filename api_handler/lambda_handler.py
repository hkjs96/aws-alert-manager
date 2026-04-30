"""
API Handler Lambda — HTTP API Gateway v2 라우터

API Gateway HTTP API (payload format v2.0) 이벤트를 수신하여
경로/메서드 기반으로 각 route 핸들러에 위임한다.

라우팅 규칙:
  METHOD /path  →  handler(event) → {"statusCode": N, "body": "..."}

인증: API Key (x-api-key 헤더). Phase 2에서 Cognito로 교체 예정.
CORS: 모든 오리진 허용 (내부 MSP 도구 기준).
"""

import json
import logging
import os
import re

logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

from api_handler.routes import customers, accounts, dashboard, resources, alarms, thresholds, jobs, bulk


def _health(event: dict) -> dict:
    return {"statusCode": 200, "body": json.dumps({"status": "ok"})}


# ──────────────────────────────────────────────
# 라우트 테이블
# ──────────────────────────────────────────────
# (method, path_pattern) → handler
# path_pattern: 정적 문자열 또는 정규식 (named group: 경로 파라미터)

_ROUTES: list[tuple[str, re.Pattern, object]] = [
    # Health
    ("GET",    re.compile(r"^/health$"),                              _health),
    # Dashboard
    ("GET",    re.compile(r"^/dashboard/stats$"),                     dashboard.get_stats),
    ("GET",    re.compile(r"^/dashboard/recent-alarms$"),             dashboard.get_recent_alarms),
    # Resources
    ("GET",    re.compile(r"^/resources$"),                           resources.list_resources),
    ("POST",   re.compile(r"^/resources/sync$"),                      resources.sync_resources),
    ("GET",    re.compile(r"^/resources/(?P<id>[^/]+)/alarms$"),      resources.get_resource_alarms),
    ("GET",    re.compile(r"^/resources/(?P<id>[^/]+)$"),             resources.get_resource),
    # Alarms
    ("GET",    re.compile(r"^/alarms/summary$"),                      alarms.get_alarm_summary),
    ("GET",    re.compile(r"^/alarms$"),                              alarms.list_alarms_handler),
    # Customers
    ("GET",    re.compile(r"^/customers$"),                           customers.list_customers),
    ("POST",   re.compile(r"^/customers$"),                           customers.create_customer),
    ("DELETE", re.compile(r"^/customers/(?P<id>[^/]+)$"),             customers.delete_customer),
    # Accounts
    ("GET",    re.compile(r"^/accounts$"),                            accounts.list_accounts),
    ("POST",   re.compile(r"^/accounts$"),                            accounts.create_account),
    ("DELETE", re.compile(r"^/accounts/(?P<id>[^/]+)$"),              accounts.delete_account),
    ("POST",   re.compile(r"^/accounts/(?P<id>[^/]+)/test$"),         accounts.test_connection),
    # Thresholds
    ("GET",    re.compile(r"^/thresholds/(?P<type>[^/]+)$"),          thresholds.get_thresholds),
    ("PUT",    re.compile(r"^/thresholds/(?P<type>[^/]+)$"),          thresholds.put_thresholds),
    # Jobs
    ("GET",    re.compile(r"^/jobs/(?P<id>[^/]+)$"),                  jobs.get_job),
    # Bulk
    ("POST",   re.compile(r"^/bulk/monitoring$"),                     bulk.bulk_monitoring),
]


# ──────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────

def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET").upper()
    raw_path = event.get("rawPath", event.get("path", "/"))

    # API Gateway stage prefix 제거 (/prod/api/customers → /api/customers)
    stage = os.environ.get("API_STAGE", "")
    if stage and raw_path.startswith(f"/{stage}"):
        raw_path = raw_path[len(f"/{stage}"):]

    # /api prefix 제거 (/api/customers → /customers)
    # 프론트엔드가 apiFetch("/api/customers")로 호출하기 때문에 필요
    if raw_path.startswith("/api"):
        raw_path = raw_path[4:] or "/"

    logger.info("%s %s", method, raw_path)

    for route_method, pattern, handler in _ROUTES:
        if route_method != method:
            continue
        m = pattern.match(raw_path)
        if m:
            path_params = m.groupdict()
            if path_params:
                event = {**event, "pathParameters": path_params}
            try:
                result = handler(event)
            except Exception as e:
                logger.error("Handler error [%s %s]: %s", method, raw_path, e)
                result = {
                    "statusCode": 500,
                    "body": json.dumps({"code": "INTERNAL_ERROR", "message": "서버 오류가 발생했습니다"}),
                }
            return _with_cors(result)

    return _with_cors({
        "statusCode": 404,
        "body": json.dumps({"code": "NOT_FOUND", "message": f"{method} {raw_path} 를 찾을 수 없습니다"}),
    })


def _with_cors(response: dict) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,x-api-key",
        "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    }
    return {**response, "headers": headers}
