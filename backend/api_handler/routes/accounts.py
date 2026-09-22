"""
/accounts 엔드포인트

GET    /accounts                  → 어카운트 목록 (?customer_id=X)
POST   /accounts                  → 어카운트 생성
DELETE /accounts/{id}             → 어카운트 삭제
POST   /accounts/{id}/test        → AWS 연결 테스트 (STS AssumeRole + 알림 전달 경로)

**교차계정 알림 전달은 두 쪽이 다 있어야 한다**: 고객 계정의 전달 룰·역할(온보딩 스택)과 우리 버스의
정책(이 파일). 버스 정책이 없으면 EventBridge는 이벤트를 **조용히 버린다** — 고객 계정에도 우리에게도
오류가 남지 않는다. 그래서 이 파일의 모든 경로는 실패를 드러내는 쪽으로 기운다: 등록은 read-back으로
확인하고, 매시 정합 점검이 드리프트를 되돌리며, 되돌린 사실과 실패는 운영 오류 알림으로 올린다.
"""

import functools
import json
import logging
import os
from datetime import datetime, UTC

import boto3
from botocore.exceptions import ClientError

from api_handler.db import accounts_table, scan_all, query_by_pk
from common.sns_notifier import send_error_alert

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _current_account_id() -> str:
    return boto3.client("sts").get_caller_identity().get("Account", "")


@functools.lru_cache(maxsize=1)
def _events_client():
    return boto3.client("events")


#: 고객사 계정이 우리 버스로 보낼 수 있는 것 — 알람 이벤트뿐이다.
#: 조건이 없으면 등록된 계정이 **아무 이벤트나** 우리 버스에 넣을 수 있다.
ALERT_EVENT_SOURCE = "aws.cloudwatch"
ALERT_DETAIL_TYPES = [
    "CloudWatch Alarm State Change",
    "CloudWatch Alarm Configuration Change",
]


def _forward_statement_id(account_id: str) -> str:
    return f"acct-{account_id}"


def _forward_statement(account_id: str, bus_arn: str) -> dict:
    return {
        "Sid": _forward_statement_id(account_id),
        "Effect": "Allow",
        "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
        "Action": "events:PutEvents",
        "Resource": bus_arn,
        "Condition": {"ForAllValues:StringEquals": {
            "events:source": ALERT_EVENT_SOURCE,
            "events:detail-type": ALERT_DETAIL_TYPES,
        }},
    }


def _read_bus_policy(bus: str) -> tuple[str, list[dict]]:
    """(버스 ARN, 현재 statement 목록). 정책이 없으면 빈 목록."""
    desc = _events_client().describe_event_bus(Name=bus)
    raw = desc.get("Policy") or ""
    statements: list[dict] = []
    if raw:
        try:
            statements = list(json.loads(raw).get("Statement") or [])
        except json.JSONDecodeError:
            logger.error("bus %s has an unparseable policy — refusing to overwrite it", bus)
            raise ConditionalWriteError(f"bus {bus} policy is not valid JSON")
    return str(desc.get("Arn") or ""), statements


def _write_bus_policy(bus: str, statements: list[dict]) -> None:
    """statement 목록을 그대로 버스 정책으로 쓴다. 비면 정책을 지운다.

    **PutPermission(Policy=...)는 정책 전체를 교체한다**(실측 확인). 그래서 호출자는 반드시
    현재 정책을 읽어 합친 뒤 넘겨야 한다 — 안 그러면 고객사를 추가할 때마다 앞 고객사의
    권한이 조용히 사라지고, 그 계정의 알람이 그날부터 안 들어온다.
    """
    client = _events_client()
    if not statements:
        client.remove_permission(EventBusName=bus, RemoveAllPermissions=True)
        return
    client.put_permission(EventBusName=bus, Policy=json.dumps(
        {"Version": "2012-10-17", "Statement": statements}))


class ConditionalWriteError(RuntimeError):
    """버스 정책을 안전하게 갱신할 수 없는 상태 — 덮어쓰지 않고 물러난다."""


def _grant_alert_forwarding(account_id: str) -> str:
    """등록된 계정이 알림 이벤트 버스로 **알람 이벤트만** 보낼 수 있게 허용한다.

    교차계정 PutEvents는 발신 룰의 역할(온보딩 템플릿)과 수신 버스의 정책 둘 다 필요하다.
    이쪽이 없으면 고객사 룰이 조용히 막힌다. 실패해도 등록 자체는 성공시키되 상태를 남겨
    드러낸다 — 조용히 삼키면 온보딩 후 "이벤트가 안 온다"의 원인이 감춰진다.
    """
    bus = os.environ.get("ALERT_EVENT_BUS_NAME", "")
    if not bus or not account_id:
        return "skipped"
    if account_id == _current_account_id():
        return "self"     # 우리 계정은 기본 버스 룰로 들어온다 — 교차계정 정책 불필요
    sid = _forward_statement_id(account_id)
    try:
        bus_arn, statements = _read_bus_policy(bus)
        kept = [s for s in statements if s.get("Sid") != sid]
        _write_bus_policy(bus, [*kept, _forward_statement(account_id, bus_arn)])
        # 읽어서 확인한다 — 전체 교체 API라 동시 등록이 서로를 지울 수 있고,
        # 그 손실은 "알람이 안 온다"로만 드러나 원인을 찾기 어렵다.
        _, after = _read_bus_policy(bus)
        got = {s.get("Sid") for s in after}
        missing = ({s.get("Sid") for s in statements} | {sid}) - got
        if missing:
            logger.error("bus %s lost statements after grant: %s", bus, sorted(missing))
            return "grant_failed"
        return "granted"
    except (ClientError, ConditionalWriteError) as e:
        logger.error("Failed to grant alert forwarding to %s on bus %s: %s", account_id, bus, e)
        return "grant_failed"


def _forwarding_incident(context: str, detail: str) -> None:
    """전달 권한 문제를 운영 오류 알림으로 올린다 — 로그만 남기면 아무도 안 본다.

    이 경로의 실패는 "그 계정 알람이 안 온다"로만 드러나고, 그때는 이미 이벤트가 버려진 뒤다. 토픽이
    없는 환경에서는 `sns_notifier`가 로그만 남기고 조용히 물러나므로 호출부는 신경 쓰지 않아도 된다.
    """
    send_error_alert(context=context, error=RuntimeError(detail))


def check_alert_forwarding(account_id: str) -> dict:
    """이 계정이 우리 버스로 알람 이벤트를 보낼 수 있는가 — 버스 정책을 읽어 답하고, 어긋나 있으면 고친다.

    AssumeRole이 되는 것과 알람 이벤트가 도착하는 것은 다른 조건이다. 2026-09-22까지 연결 테스트는
    AssumeRole만 봐서 "연결됨"인데 알람은 영영 오지 않는 상태를 통과시켰다 — 온보딩 스택을 만든 뒤
    계정 등록 전이거나, 동시 등록으로 statement가 지워졌을 때가 그렇다.

    Returns: ``{"status": ..., "detail": ...}``
      ``ok``       statement가 기대한 모양 그대로 있다
      ``repaired`` 없거나 옛 형식이라 다시 썼다 — 그 전에 보낸 이벤트는 이미 버려졌다
      ``failed``   확인하거나 고칠 수 없다(권한·정책 파손)
      ``self``     우리 계정 자신 — 기본 버스 룰로 들어오므로 교차계정 정책이 필요 없다
      ``skipped``  버스가 설정되지 않은 환경
    """
    bus = os.environ.get("ALERT_EVENT_BUS_NAME", "")
    if not bus or not account_id:
        return {"status": "skipped", "detail": "alert event bus is not configured"}
    if account_id == _current_account_id():
        return {"status": "self", "detail": "central account forwards through the default bus"}

    sid = _forward_statement_id(account_id)
    try:
        bus_arn, statements = _read_bus_policy(bus)
    except (ClientError, ConditionalWriteError) as e:
        logger.error("Could not read bus %s policy while checking %s: %s", bus, account_id, e)
        return {"status": "failed", "detail": f"could not read the {bus} policy: {e}"}

    current = next((s for s in statements if s.get("Sid") == sid), None)
    if current == _forward_statement(account_id, bus_arn):
        return {"status": "ok", "detail": f"{bus} accepts alarm events from {account_id}"}

    was = "missing" if current is None else "outdated"
    if _grant_alert_forwarding(account_id) != "granted":
        _forwarding_incident(
            f"alert forwarding for account {account_id}",
            f"bus {bus} statement was {was} and could not be repaired")
        return {"status": "failed", "detail": f"statement was {was} and could not be repaired"}
    return {"status": "repaired",
            "detail": f"statement was {was}; rewritten — alarm events sent before now were dropped"}


def reconcile_alert_forwarding() -> dict:
    """계정 표와 버스 정책을 맞춘다 — 등록된 계정의 statement가 빠졌거나 옛 형식이면 다시 쓰고,
    표에 없는 `acct-*` statement는 뗀다 (review-phase2 L1).

    등록 경로의 read-back 검증은 "내 쓰기와 확인 사이"의 덮어쓰기만 잡는다. A읽→B읽→A씀✓→B씀✓이면
    A의 권한이 사라지는데 둘 다 `granted`다. 잠금 대신 **주기 점검으로 수렴**시킨다 — 이 손실은
    "그 계정 알람이 안 온다"로만 드러나 사람이 알아채기 어렵기 때문이다. 우리가 만들지 않은
    statement(Sid가 `acct-`로 시작하지 않는 것)는 건드리지 않는다.
    """
    bus = os.environ.get("ALERT_EVENT_BUS_NAME", "")
    if not bus:
        return {"skipped": "no_bus"}
    try:
        me = _current_account_id()
        rows = scan_all(accounts_table())
        bus_arn, statements = _read_bus_policy(bus)
    except (ClientError, ConditionalWriteError) as e:
        logger.error("alert forwarding reconcile could not read state: %s", e)
        _forwarding_incident("alert forwarding reconcile", f"could not read state: {e}")
        return {"error": str(e)}

    wanted = sorted({str(r.get("account_id") or "") for r in rows} - {"", me})
    have = {str(s.get("Sid", "")): s for s in statements}
    added, updated, removed = [], [], []
    kept: list[dict] = []
    for sid, statement in have.items():
        if sid.startswith("acct-") and sid[len("acct-"):] not in wanted:
            removed.append(sid)                  # 표에서 사라진 계정 — 권한도 회수
            continue
        kept.append(statement)
    for account_id in wanted:
        sid = _forward_statement_id(account_id)
        expected = _forward_statement(account_id, bus_arn)
        current = have.get(sid)
        if current == expected:
            continue
        kept = [s for s in kept if s.get("Sid") != sid] + [expected]
        (updated if current is not None else added).append(sid)

    result = {"bus": bus, "accounts": len(wanted), "added": added, "updated": updated,
              "removed": removed, "changed": bool(added or updated or removed)}
    if not result["changed"]:
        return result
    try:
        _write_bus_policy(bus, kept)
    except ClientError as e:
        logger.error("alert forwarding reconcile could not write policy: %s", e)
        _forwarding_incident("alert forwarding reconcile", f"could not write the {bus} policy: {e}")
        return {**result, "error": str(e)}
    logger.warning("alert forwarding drift fixed on bus %s: added=%s updated=%s removed=%s",
                   bus, added, updated, removed)
    # 드리프트를 되돌렸다는 것은 그때까지 그 계정 이벤트가 버려지고 있었다는 뜻이다 — 조용히 고치면
    # 손실이 있었다는 사실 자체가 사라진다. 수렴은 자동이지만 보고는 사람에게 한다.
    _forwarding_incident(
        "alert forwarding reconcile",
        f"bus {bus} drifted and was repaired: added={added} updated={updated} removed={removed}; "
        "alarm events from those accounts were dropped until now")
    return result


def reconcile_alert_forwarding_route(event: dict) -> dict:
    """`POST /accounts/alert-forwarding/reconcile` — 관리자 수동 실행(온보딩 진단 절차용)."""
    from api_handler.identity import admin_enforced, current_email, is_admin
    if admin_enforced() and not is_admin(current_email(event)):
        return _err(403, "FORBIDDEN", "버스 정책 정합성 점검은 관리자 전용입니다")
    result = reconcile_alert_forwarding()
    return _ok(result) if "error" not in result else _err(503, "EVENTS_ERROR", result["error"])


def _revoke_alert_forwarding_if_orphan(account_id: str) -> None:
    """다른 고객사 행이 이 계정을 더 쓰지 않을 때만 버스 권한을 회수한다."""
    bus = os.environ.get("ALERT_EVENT_BUS_NAME", "")
    if not bus or not account_id or account_id == _current_account_id():
        return
    try:
        remaining = scan_all(accounts_table())
    except ClientError as e:
        logger.warning("Could not check remaining accounts before revoke of %s: %s", account_id, e)
        return
    if any((a.get("account_id") or "") == account_id for a in remaining):
        return
    sid = _forward_statement_id(account_id)
    try:
        _, statements = _read_bus_policy(bus)
        kept = [s for s in statements if s.get("Sid") != sid]
        if len(kept) != len(statements):
            _write_bus_policy(bus, kept)
    except (ClientError, ConditionalWriteError) as e:
        logger.warning("Failed to revoke alert forwarding for %s on bus %s: %s", account_id, bus, e)


def list_accounts(event: dict) -> dict:
    qs = event.get("queryStringParameters") or {}
    customer_id = qs.get("customer_id", "").strip()

    try:
        if customer_id:
            items = query_by_pk(accounts_table(), "customer_id", customer_id)
        else:
            items = scan_all(accounts_table())
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))

    return _ok(items)


def create_account(event: dict) -> dict:
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _err(400, "INVALID_JSON", "요청 본문이 JSON 형식이 아닙니다")

    required = ("account_id", "role_arn", "name", "customer_id")
    missing = [f for f in required if not (body.get(f) or "").strip()]
    if missing:
        return _err(400, "VALIDATION_ERROR", f"필수 필드 누락: {', '.join(missing)}")

    account_id = body["account_id"].strip()
    customer_id = body["customer_id"].strip()

    table = accounts_table()
    try:
        existing = table.get_item(
            Key={"customer_id": customer_id, "account_id": account_id}
        ).get("Item")
        if existing:
            return _err(409, "DUPLICATE", f"account_id '{account_id}'가 이미 존재합니다")
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))

    regions = _normalize_regions(body.get("regions"))
    if not regions:
        return _err(400, "VALIDATION_ERROR", "regions must include at least one AWS region")

    item = {
        "customer_id": customer_id,
        "account_id": account_id,
        "name": body["name"].strip(),
        "role_arn": body["role_arn"].strip(),
        "regions": regions,
        "connection_status": "untested",
        "created_at": datetime.now(UTC).isoformat(),
    }
    item["alert_forwarding"] = _grant_alert_forwarding(account_id)
    if item["alert_forwarding"] == "grant_failed":
        _forwarding_incident(
            f"alert forwarding for account {account_id}",
            "registration completed but the bus grant failed — this account's alarms will not arrive "
            "until the hourly reconcile or a connection test repairs it")
    try:
        table.put_item(Item=item)
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))

    return _ok(item, status=201)


def delete_account(event: dict) -> dict:
    path_params = event.get("pathParameters") or {}
    account_id = path_params.get("id", "").strip()
    qs = event.get("queryStringParameters") or {}
    customer_id = qs.get("customer_id", "").strip()

    if not account_id or not customer_id:
        return _err(400, "MISSING_PARAM", "account_id와 customer_id가 필요합니다")

    try:
        accounts_table().delete_item(
            Key={"customer_id": customer_id, "account_id": account_id}
        )
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))

    _revoke_alert_forwarding_if_orphan(account_id)
    return {"statusCode": 204, "body": ""}


def _probe_regions(item: dict) -> tuple[str, list[dict], str]:
    """AssumeRole → 리전별 CloudWatch 접근. ``(status, 리전별 결과, 오류 메시지)``.

    `_test_region_access`가 리전 단위 `ClientError`를 스스로 삼키므로, 여기서 잡히는 것은 AssumeRole
    실패뿐이다 — 그때는 모든 리전을 같은 이유로 실패 처리한다(기존 동작 그대로).
    """
    regions = item.get("regions") or []
    try:
        session_kwargs = _assume_role_kwargs(item)
    except ClientError as e:
        message = str(e)
        return "failed", [{"region": r, "status": "failed", "error": message} for r in regions], message

    results = [_test_region_access(region, session_kwargs) for region in regions]
    reachable = bool(regions) and all(r["status"] == "connected" for r in results)
    first_error = next((r.get("error", "") for r in results if r["status"] == "failed"), "")
    return ("connected" if reachable else "failed"), results, first_error


def test_connection(event: dict) -> dict:
    """AWS 연결 가능 여부를 확인한다 — STS AssumeRole·리전 접근에 더해 **알림 전달 경로**까지.

    `status`는 예전 그대로 AssumeRole·리전 접근 기준이다(화면·저장 값 호환). 전달 경로는 별도 필드
    `alert_forwarding`으로 낸다 — 둘은 다른 조건이고, 전달만 끊긴 계정은 여기서만 드러난다.
    """
    path_params = event.get("pathParameters") or {}
    account_id = path_params.get("id", "").strip()
    qs = event.get("queryStringParameters") or {}
    customer_id = qs.get("customer_id", "").strip()

    if not account_id or not customer_id:
        return _err(400, "MISSING_PARAM", "account_id와 customer_id가 필요합니다")

    table = accounts_table()
    try:
        item = table.get_item(
            Key={"customer_id": customer_id, "account_id": account_id}
        ).get("Item")
    except ClientError as e:
        return _err(500, "DB_ERROR", str(e))

    if not item:
        return _err(404, "NOT_FOUND", "어카운트를 찾을 수 없습니다")

    role_arn = item.get("role_arn", "")
    if not role_arn:
        return _err(400, "MISSING_ROLE", "role_arn이 설정되지 않았습니다")

    status, region_results, error_msg = _probe_regions(item)

    # 전달 경로 점검 — AssumeRole이 실패해도 본다(둘은 독립된 조건이고, 진단에는 둘 다 필요하다).
    forwarding = check_alert_forwarding(account_id)

    # 연결 상태 업데이트
    try:
        table.update_item(
            Key={"customer_id": customer_id, "account_id": account_id},
            UpdateExpression=(
                "SET connection_status = :s, last_tested_at = :t, alert_forwarding = :f"),
            ExpressionAttributeValues={
                ":s": status,
                ":t": datetime.now(UTC).isoformat(),
                ":f": forwarding["status"],
            },
        )
    except ClientError:
        pass  # 상태 업데이트 실패는 무시

    result = {
        "account_id": account_id,
        "status": status,
        "regions": region_results,
        "alert_forwarding": forwarding,
        "tested_at": datetime.now(UTC).isoformat(),
    }
    if error_msg:
        result["error"] = error_msg
    return _ok(result)


# ── 헬퍼 ──────────────────────────────────────────────────────────

def _ok(data, status: int = 200) -> dict:
    return {"statusCode": status, "body": json.dumps(data, default=str)}


def _err(status: int, code: str, message: str) -> dict:
    return {"statusCode": status, "body": json.dumps({"code": code, "message": message})}


def _normalize_regions(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(region).strip() for region in value if str(region).strip()]


def _assume_role_kwargs(account: dict) -> dict:
    if account.get("account_id", "") == _current_account_id():
        return {}

    resp = boto3.client("sts").assume_role(
        RoleArn=account.get("role_arn", ""),
        RoleSessionName="ConnectionTest",
    )
    creds = resp["Credentials"]
    return {
        "aws_access_key_id": creds["AccessKeyId"],
        "aws_secret_access_key": creds["SecretAccessKey"],
        "aws_session_token": creds["SessionToken"],
    }


def _test_region_access(region: str, session_kwargs: dict) -> dict:
    try:
        cw = boto3.client("cloudwatch", region_name=region, **session_kwargs)
        cw.describe_alarms(MaxRecords=1)
        return {"region": region, "status": "connected"}
    except ClientError as e:
        return {"region": region, "status": "failed", "error": str(e)}
