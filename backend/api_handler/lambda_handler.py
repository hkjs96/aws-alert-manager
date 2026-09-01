"""
API Handler Lambda — HTTP API Gateway v2 라우터

API Gateway HTTP API (payload format v2.0) 이벤트를 수신하여
경로/메서드 기반으로 각 route 핸들러에 위임한다.

라우팅 규칙:
  METHOD /path  →  handler(event) → {"statusCode": N, "body": "..."}

인증: API Gateway 네이티브 JWT authorizer가 Google ID 토큰을 검증하고,
     여기서 email/도메인 allowlist(_authorize)로 접근을 강제한다. docs/AUTH.md 참고.
CORS: 모든 오리진 허용 (내부 MSP 도구 기준).
"""

import json
import logging
import os
import re
import time

logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

from common.perf_log import log_perf

# 첫 invocation(콜드 스타트)은 INIT 비용이 얹혀 응답이 느리다. 이 둘을 섞어 평균을 내면
# "느린 API"와 "가끔 느린 콜드 스타트"를 구분할 수 없으므로 측정에 플래그로 남긴다.
_COLD = True

# 라우트 정규식 → 집계용 이름. raw_path로 집계하면 리소스 ID마다 다른 축이 생겨
# "어느 엔드포인트가 느린가"를 볼 수 없다. (?P<id>...) → {id} 로 정규화한다.
_ROUTE_PARAM_RE = re.compile(r"\(\?P<(\w+)>[^)]*\)")


def _route_name(method: str, pattern: re.Pattern) -> str:
    raw = pattern.pattern.lstrip("^").rstrip("$")
    return f"{method} {_ROUTE_PARAM_RE.sub(lambda m: '{' + m.group(1) + '}', raw)}"

from api_handler.routes import (
    customers, accounts, dashboard, resources, alarms, thresholds, jobs, bulk,
    monitor_runs, sync, preferences,
)


def _health(event: dict) -> dict:
    return {"statusCode": 200, "body": json.dumps({"status": "ok"})}


def _csv_set(value: str) -> set[str]:
    return {p.strip().lower().lstrip("@") for p in value.split(",") if p.strip()}


def _authorize(event: dict) -> dict | None:
    """Email/domain allowlist guard.

    Identity comes from the API Gateway JWT authorizer, which has already
    verified the Google ID token signature/issuer/audience/expiry. We only
    enforce *which* verified identities are allowed.

    Returns None when the request may proceed, or a 403 response dict.
    When neither allowlist env var is set, no restriction is applied
    (auth is either disabled at API Gateway or intentionally open).
    """
    allowed_emails = _csv_set(os.environ.get("ALLOWED_EMAILS", ""))
    allowed_domains = _csv_set(os.environ.get("ALLOWED_EMAIL_DOMAINS", ""))
    if not allowed_emails and not allowed_domains:
        return None

    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    ) or {}

    email = str(claims.get("email", "")).strip().lower()
    if not email or str(claims.get("email_verified", "true")).lower() == "false":
        return _forbidden("unverified or missing identity")

    if email in allowed_emails:
        return None

    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    hd = str(claims.get("hd", "")).strip().lower()
    if (domain and domain in allowed_domains) or (hd and hd in allowed_domains):
        return None

    return _forbidden(email)


def _forbidden(who: str) -> dict:
    logger.warning("Authorization denied: %s", who)
    return {
        "statusCode": 403,
        "body": json.dumps({"code": "FORBIDDEN", "message": "접근 권한이 없습니다"}),
    }


# ──────────────────────────────────────────────
# 라우트 테이블
# ──────────────────────────────────────────────
# (method, path_pattern) → handler
# path_pattern: 정적 문자열 또는 정규식 (named group: 경로 파라미터)

_ROUTES: list[tuple[str, re.Pattern, object]] = [
    # Health
    ("GET",    re.compile(r"^/health$"),                              _health),
    # Current user (identity + personal view selection)
    ("GET",    re.compile(r"^/me$"),                                  preferences.get_me),
    ("PUT",    re.compile(r"^/me/preferences$"),                      preferences.put_preferences),
    # Dashboard
    ("GET",    re.compile(r"^/dashboard/stats$"),                     dashboard.get_stats),
    ("GET",    re.compile(r"^/dashboard/recent-alarms$"),             dashboard.get_recent_alarms),
    # Resources
    ("GET",    re.compile(r"^/resources$"),                           resources.list_resources),
    ("POST",   re.compile(r"^/resources/sync$"),                      sync.import_resources),
    ("PUT",    re.compile(r"^/resources/(?P<id>[^/]+)/monitoring$"),   resources.update_resource_monitoring),
    ("GET",    re.compile(r"^/resources/(?P<id>[^/]+)/alarms$"),      resources.get_resource_alarms),
    ("PUT",    re.compile(r"^/resources/(?P<id>[^/]+)/alarms$"),      resources.update_resource_alarms),
    ("POST",   re.compile(r"^/resources/(?P<id>[^/]+)/alarms$"),      resources.create_resource_alarm),
    ("GET",    re.compile(r"^/resources/(?P<id>[^/]+)/disk-paths$"),  resources.get_disk_paths),
    ("GET",    re.compile(r"^/resources/(?P<id>[^/]+)/metrics$"),     resources.get_resource_metrics),
    ("GET",    re.compile(r"^/resources/(?P<id>[^/]+)$"),             resources.get_resource),
    # Alarms
    ("GET",    re.compile(r"^/alarms/summary$"),                      alarms.get_alarm_summary),
    ("GET",    re.compile(r"^/alarms$"),                              alarms.list_alarms_handler),
    ("POST",   re.compile(r"^/sync/alarms$"),                         sync.import_alarms),
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
    # Monitor runs
    ("GET",    re.compile(r"^/monitor-runs$"),                        monitor_runs.list_monitor_runs),
    # Bulk
    ("POST",   re.compile(r"^/bulk/monitoring$"),                     bulk.bulk_monitoring),
]


# ──────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────

def lambda_handler(event, context):
    global _COLD
    cold, _COLD = _COLD, False
    started = time.perf_counter()

    method = event.get("requestContext", {}).get("http", {}).get("method", "GET").upper()

    # CORS preflight — 라우트 매칭 없이 즉시 응답 (측정 대상 아님)
    if method == "OPTIONS":
        return _with_cors({"statusCode": 200, "body": ""})

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

    # Email/domain allowlist guard (identity verified by API GW JWT authorizer).
    # /health stays open for uptime checks.
    if raw_path != "/health":
        denied = _authorize(event)
        if denied is not None:
            _log_request(f"{method} (denied)", denied, started, cold)
            return _with_cors(denied)

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
            _log_request(_route_name(route_method, pattern), result, started, cold)
            return _with_cors(result)

    not_found = {
        "statusCode": 404,
        "body": json.dumps({"code": "NOT_FOUND", "message": f"{method} {raw_path} 를 찾을 수 없습니다"}),
    }
    _log_request(f"{method} (unmatched)", not_found, started, cold)
    return _with_cors(not_found)


def _log_request(route: str, result: dict, started: float, cold: bool) -> None:
    """요청 1건의 소요·상태·콜드스타트를 구조화 로그로 남긴다 (docs/OBSERVABILITY.md)."""
    log_perf(
        "api_request",
        (time.perf_counter() - started) * 1000,
        route=route,
        status=result.get("statusCode", 0),
        cold=cold,
        bytes=len(result.get("body") or ""),
    )


def _with_cors(response: dict) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,x-api-key",
        "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    }
    return {**response, "headers": headers}
