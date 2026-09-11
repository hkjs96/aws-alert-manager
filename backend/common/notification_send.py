"""
알림 전송 — 채널 하나에 실제로 보낸다 (tasks 2.2.4~2.2.6)

여기가 유일하게 바깥으로 나가는 곳이다. 어댑터가 **무엇을 어디로 어떻게** 보낼지 선언하고
(`transport`/`endpoint_field`/`recipients_field`), 이 모듈은 그 선언대로 실행만 한다 —
채널 유형이 늘어도 이 파일은 그대로다.

원칙 셋:

1. **한 채널의 실패가 다른 채널을 막지 않는다** (R6-7). 결과는 채널마다 따로 기록한다.
2. **설정 오류는 재시도하지 않는다.** 404·401 같은 4xx는 다시 보내도 같은 답이 온다 —
   재시도는 지연만 늘리고 속도 제한만 먹는다. 5xx·타임아웃·429만 재시도한다.
3. **자격증명은 오류 메시지에도 넣지 않는다.** 웹훅 URL이 실패 기록으로 새면 응답에서 가린
   의미가 없다.
"""

from __future__ import annotations

import functools
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field

from common.notification_adapters import (
    TRANSPORT_EMAIL,
    TRANSPORT_HTTPS,
    Notification,
)

logger = logging.getLogger(__name__)

#: 전송 한 번의 상한. Lambda 타임아웃보다 훨씬 짧아야 채널 여러 개를 돌 수 있다.
TIMEOUT_SEC = 5
#: 일시적 실패의 재시도 횟수(최초 시도 포함). 알림은 늦으면 가치가 급감하므로 짧게.
MAX_ATTEMPTS = 3
BACKOFF_SEC = 0.5

#: 다시 보내면 달라질 수 있는 응답. 그 밖의 4xx는 설정이 틀린 것이다.
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


@dataclass
class DeliveryResult:
    channel_id: str
    channel_name: str
    type: str
    ok: bool
    attempts: int = 0
    status: int | None = None
    error: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in ("", None)}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """리다이렉트를 따라가지 않는다.

    urllib는 기본으로 3xx를 따라가며 `Authorization` 헤더를 그대로 들고 간다 — https로 검증한 URL이
    http로 302하면 토큰이 평문으로 나간다. 3xx는 실패로 기록한다(재시도 대상도 아니다)(review-phase2 L4).
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):     # noqa: PLR0913
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


@functools.lru_cache(maxsize=1)
def _ses():
    import boto3
    return boto3.client("ses")


#: 시간 예산이 다 됐을 때 남은 채널에 남기는 사유. 재시도 대상이 아니라 **기록**이다 — "안 왔다"의 원인.
BUDGET_EXCEEDED = "시간 예산 초과 — 이 채널까지 가지 못했습니다"


class Transports:
    """바깥 세계. 테스트는 이걸 갈아 끼운다."""

    def post(self, url: str, body: str, headers: dict, timeout: int) -> int:
        req = urllib.request.Request(
            url, data=body.encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", **headers})
        with _OPENER.open(req, timeout=timeout) as resp:              # noqa: S310 (https만 허용됨)
            return int(resp.status)

    def send_email(self, sender: str, recipients: list[str], subject: str, body: str) -> None:
        _ses().send_email(
            Source=sender,
            Destination={"ToAddresses": recipients},
            Message={"Subject": {"Data": subject, "Charset": "UTF-8"},
                     "Body": {"Text": {"Data": body, "Charset": "UTF-8"}}},
        )


def _retryable(status: int | None, exc: Exception | None) -> bool:
    if status is not None:
        return status in _RETRYABLE_STATUS
    # 네트워크가 흔들린 것 — 다시 해볼 가치가 있다
    return isinstance(exc, (urllib.error.URLError, TimeoutError, OSError))


def _https_attempt(channel, payload: dict, transports: Transports) -> tuple[int | None, Exception | None]:
    adapter = channel.adapter
    url = channel.config.get(adapter.endpoint_field, "")
    if not url:
        raise ValueError(f"{adapter.endpoint_field}이(가) 설정되지 않았습니다")
    headers = {}
    if adapter.auth_header_field:
        token = channel.config.get(adapter.auth_header_field, "")
        if token:
            headers["Authorization"] = token
    body = payload.get("body") if "body" in payload else json.dumps(payload, ensure_ascii=False)
    try:
        return transports.post(url, body, headers, TIMEOUT_SEC), None
    except urllib.error.HTTPError as e:
        return int(e.code), e
    except Exception as e:                                     # noqa: BLE001
        return None, e


def _email_attempt(channel, payload: dict, transports: Transports, sender: str) -> tuple[int | None, Exception | None]:
    adapter = channel.adapter
    raw = channel.config.get(adapter.recipients_field, "")
    recipients = [a.strip() for a in str(raw).split(",") if a.strip()]
    if not recipients:
        raise ValueError("수신 주소가 설정되지 않았습니다")
    if not sender:
        raise ValueError("보내는 주소(ALERT_EMAIL_SENDER)가 설정되지 않았습니다")
    try:
        transports.send_email(sender, recipients, payload.get("subject", ""), payload.get("body", ""))
        return 200, None
    except Exception as e:                                     # noqa: BLE001
        return None, e


def _safe_error(exc: Exception | None, channel) -> str:
    """오류 메시지에서 자격증명을 지운다 — 실패 기록으로 새면 가린 의미가 없다."""
    text = str(exc or "")[:300]
    for name in channel.adapter.secret_fields:
        value = str(channel.config.get(name, "") or "")
        if value:
            text = text.replace(value, "(가림)")
    return text


def deliver(channel, notification: Notification, *,
            transports: Transports | None = None,
            sender: str = "",
            sleep=time.sleep) -> DeliveryResult:
    """채널 하나에 보낸다. 예외를 밖으로 내지 않는다 — 결과로 돌려준다."""
    transports = transports or Transports()
    adapter = channel.adapter
    result = DeliveryResult(channel_id=channel.channel_id, channel_name=channel.name,
                            type=channel.type, ok=False)
    try:
        payload = adapter.render(notification)
    except Exception as e:                                     # noqa: BLE001
        result.error = f"렌더 실패: {_safe_error(e, channel)}"
        return result

    for attempt in range(1, MAX_ATTEMPTS + 1):
        result.attempts = attempt
        try:
            if adapter.transport == TRANSPORT_HTTPS:
                status, exc = _https_attempt(channel, payload, transports)
            elif adapter.transport == TRANSPORT_EMAIL:
                status, exc = _email_attempt(channel, payload, transports, sender)
            else:
                result.error = f"지원하지 않는 전송 방식입니다: {adapter.transport}"
                return result
        except ValueError as e:            # 설정이 빠졌다 — 재시도해도 같다
            result.error = _safe_error(e, channel)
            return result

        result.status = status
        if exc is None and status is not None and 200 <= status < 300:
            result.ok = True
            result.error = ""
            return result

        result.error = _safe_error(exc, channel) or f"HTTP {status}"
        if not _retryable(status, exc) or attempt == MAX_ATTEMPTS:
            return result
        sleep(BACKOFF_SEC * attempt)

    return result


def deliver_all(channels: list, notification: Notification, *,
                transports: Transports | None = None,
                sender: str = "",
                sleep=time.sleep,
                deadline: float | None = None) -> list[DeliveryResult]:
    """여러 채널에 보낸다. **하나가 실패해도 나머지는 계속 간다.**

    같은 유형끼리는 어댑터가 선언한 속도만큼 간격을 둔다(Slack은 초당 1건). 이 간격은 한 번의
    실행 안에서만 유효하다 — 여러 실행이 동시에 같은 채널로 보내는 경우는 그룹핑이 상한을
    잡아 준다(고객사·등급당 30초 창 1건). 그걸로 부족해지면 공유 토큰 버킷이 필요하다.

    `deadline`(`time.monotonic()` 기준)이 지나면 남은 채널은 보내지 않고 **기록만** 남긴다 — Lambda가
    중간에 죽으면 어디까지 갔는지조차 남지 않는다(review-phase2 L5). 채널 상한(50)과 타임아웃(120초)이
    서로를 모르므로 예산은 호출자가 남은 실행 시간으로 정한다.
    """
    transports = transports or Transports()
    results: list[DeliveryResult] = []
    last_sent_at: dict[str, float] = {}
    for index, channel in enumerate(channels):
        if deadline is not None and time.monotonic() >= deadline:
            results.extend(DeliveryResult(channel_id=c.channel_id, channel_name=c.name, type=c.type,
                                          ok=False, error=BUDGET_EXCEEDED) for c in channels[index:])
            logger.error("delivery budget exhausted: %d of %d channels not attempted",
                         len(channels) - index, len(channels))
            break
        rate = max(0.0, float(channel.adapter.rate_limit_per_sec or 0))
        if rate:
            gap = 1.0 / rate
            previous = last_sent_at.get(channel.type)
            if previous is not None:
                wait = gap - (time.monotonic() - previous)
                if wait > 0:
                    sleep(wait)
        results.append(deliver(channel, notification, transports=transports,
                               sender=sender, sleep=sleep))
        last_sent_at[channel.type] = time.monotonic()
    return results
