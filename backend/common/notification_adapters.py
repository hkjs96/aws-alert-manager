"""
알림 채널 어댑터 — 채널 유형 하나 = 이 파일의 블록 하나 (tasks 2.2.4, design.md D3)

**추가 방법:** `Adapter(...)`를 만들어 `register()`에 넘긴다. 그게 전부다.
라우터도, 검증도, API 응답 필터도 고치지 않는다. 어댑터가 스스로 선언한다:

- 어떤 설정 필드를 받는가 (`fields`)
- 그중 무엇이 **자격증명**인가 (`secret=True`) → API 응답에서 자동으로 빠진다
- 얼마나 빨리 보낼 수 있는가 (`rate_limit_per_sec`)
- 알림 하나를 그 채널의 형식으로 어떻게 그리는가 (`render`)
- **어떻게 보내는가** (`transport`) + 그 전송에 필요한 설정 필드가 무엇인지 (`endpoint_field` 등)

자격증명을 "빼는 것을 기억해야 하는" 구조로 만들지 않았다. 응답 직렬화가 검증과 **같은 선언**을
읽으므로, 필드를 추가하면서 secret 표시를 빠뜨리지 않는 한 새 채널 유형이 값을 흘릴 수 없다.
(R6-8 — `api_handler`에는 스캔 결과를 그대로 응답에 넣는 코드가 12곳 있다. 그 관례를 따르지 않는다.)

발송 자체(HTTP·SNS 호출)는 여기 없다. 이 모듈은 순수하며 저장소도 네트워크도 모른다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

#: 등급 표기 — 렌더링에서 색·머리말에 쓴다.
SEVERITY_ORDER = ("SEV-1", "SEV-2", "SEV-3", "SEV-4", "SEV-5")

#: 자격증명 자리에 응답으로 나가는 가림 문자열. 수정 시 이 값이 그대로 돌아오면 "안 바꿈"으로 읽는다.
REDACTED = "(설정됨)"


class AdapterError(ValueError):
    """어댑터 설정이 잘못됐다 — API가 400으로 돌려준다."""


@dataclass(frozen=True)
class Notification:
    """채널에 보낼 알림 하나. 어댑터는 이것만 보고 그린다 — 이벤트 원본을 파싱하지 않는다.

    묶음 발송(폭풍 시 요약)도 같은 구조를 쓴다: `count`가 1보다 크면 대표 1건 + 나머지 건수다.
    """
    title: str
    severity: str = ""
    customer_id: str = ""
    account_id: str = ""
    resource_id: str = ""
    resource_type: str = ""
    metric_key: str = ""
    state: str = ""
    reason: str = ""
    occurred_at: str = ""
    url: str = ""
    count: int = 1

    @property
    def is_bundle(self) -> bool:
        return self.count > 1

    def summary_line(self) -> str:
        parts = [p for p in (self.severity, self.resource_type, self.resource_id) if p]
        head = " · ".join(parts)
        tail = f" 외 {self.count - 1}건" if self.is_bundle else ""
        return f"[{head}] {self.title}{tail}" if head else f"{self.title}{tail}"


@dataclass(frozen=True)
class Field:
    """채널 설정 필드 하나의 선언."""
    name: str
    label: str
    required: bool = True
    #: True면 API 응답에 절대 나가지 않는다. 저장은 되고 발송에만 쓰인다.
    secret: bool = False
    max_len: int = 1024
    #: 값 형식 검사. 실패하면 메시지를 담아 AdapterError.
    check: Callable[[str], str | None] | None = None


#: 전송 방식. 새 방식이 필요할 때만 늘어난다(대부분의 채널은 HTTPS POST 하나로 끝난다).
TRANSPORT_HTTPS = "https_post"
TRANSPORT_EMAIL = "ses_email"


@dataclass(frozen=True)
class Adapter:
    type: str
    label: str
    fields: tuple[Field, ...]
    render: Callable[[Notification], dict]
    #: 채널 유형별 발송 속도 상한. Slack Incoming Webhook은 초당 1건이 실질 한계다.
    rate_limit_per_sec: float = 1.0
    transport: str = TRANSPORT_HTTPS
    #: HTTPS 전송이 요청을 보낼 주소가 담긴 설정 필드 이름.
    endpoint_field: str = ""
    #: 있으면 그 설정 값을 Authorization 헤더로 보낸다.
    auth_header_field: str = ""
    #: 이메일 전송이 수신자를 읽을 설정 필드 이름.
    recipients_field: str = ""

    @property
    def secret_fields(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.secret)

    def field(self, name: str) -> Field | None:
        return next((f for f in self.fields if f.name == name), None)

    def validate_config(self, config: dict) -> dict:
        """API 입력 → 저장할 설정. 모르는 키는 거절한다.

        조용히 버리면 사용자는 오타를 친 채 "저장됐다"는 응답을 받고, 발송은 안 된다.
        """
        if not isinstance(config, dict):
            raise AdapterError("config는 객체여야 합니다")
        known = {f.name for f in self.fields}
        unknown = sorted(set(config) - known)
        if unknown:
            raise AdapterError(
                f"{self.type} 채널이 모르는 설정 항목입니다: {', '.join(unknown)} "
                f"(가능: {', '.join(sorted(known))})")
        out: dict = {}
        for f in self.fields:
            raw = config.get(f.name)
            value = "" if raw is None else str(raw).strip()
            if not value:
                if f.required:
                    raise AdapterError(f"{f.label}({f.name})이(가) 필요합니다")
                continue
            if len(value) > f.max_len:
                raise AdapterError(f"{f.label}은(는) {f.max_len}자를 넘을 수 없습니다")
            if f.check:
                problem = f.check(value)
                if problem:
                    raise AdapterError(f"{f.label}: {problem}")
            out[f.name] = value
        return out

    def public_config(self, config: dict) -> dict:
        """API 응답용 설정 — 자격증명은 값 대신 **설정 여부**만 알려준다."""
        out: dict = {}
        for f in self.fields:
            if f.name not in config:
                continue
            out[f.name] = REDACTED if f.secret else config[f.name]
        return out


# ────────────────────────────────── 레지스트리

_ADAPTERS: dict[str, Adapter] = {}


def register(adapter: Adapter) -> Adapter:
    if adapter.type in _ADAPTERS:
        raise ValueError(f"channel type already registered: {adapter.type}")
    _ADAPTERS[adapter.type] = adapter
    return adapter


def get(channel_type: str) -> Adapter:
    adapter = _ADAPTERS.get(str(channel_type or ""))
    if adapter is None:
        raise AdapterError(
            f"알 수 없는 채널 유형입니다: {channel_type!r} (가능: {', '.join(types())})")
    return adapter


def types() -> list[str]:
    return sorted(_ADAPTERS)


def all_adapters() -> list[Adapter]:
    return [_ADAPTERS[t] for t in types()]


# ────────────────────────────────── 형식 검사기

_HTTPS = re.compile(r"^https://[^\s]+$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _https_url(value: str) -> str | None:
    if not _HTTPS.match(value):
        return "https:// 로 시작하는 URL이어야 합니다"
    return None


def _slack_webhook(value: str) -> str | None:
    problem = _https_url(value)
    if problem:
        return problem
    if "hooks.slack.com" not in value:
        return "Slack Incoming Webhook URL이어야 합니다 (hooks.slack.com)"
    return None


def _email_list(value: str) -> str | None:
    addrs = [a.strip() for a in value.split(",") if a.strip()]
    if not addrs:
        return "이메일 주소가 필요합니다"
    bad = [a for a in addrs if not _EMAIL.match(a)]
    if bad:
        return f"형식이 올바르지 않습니다: {', '.join(bad[:3])}"
    return None


# ────────────────────────────────── 채널 유형들
# 새 유형은 여기 블록 하나를 더하면 끝난다.

_SEVERITY_COLOR = {
    "SEV-1": "#d32f2f", "SEV-2": "#f57c00", "SEV-3": "#fbc02d",
    "SEV-4": "#0288d1", "SEV-5": "#757575",
}


def _render_slack(n: Notification) -> dict:
    lines = [f"*{n.summary_line()}*"]
    detail = [x for x in (
        f"계정 {n.account_id}" if n.account_id else "",
        f"지표 {n.metric_key}" if n.metric_key else "",
        f"상태 {n.state}" if n.state else "",
        n.occurred_at,
    ) if x]
    if detail:
        lines.append(" | ".join(detail))
    if n.reason:
        lines.append(n.reason)
    if n.url:
        lines.append(f"<{n.url}|자세히 보기>")
    return {
        "text": n.summary_line(),          # 알림 미리보기·접근성용 폴백
        "attachments": [{
            "color": _SEVERITY_COLOR.get(n.severity, "#757575"),
            "text": "\n".join(lines),
        }],
    }


def _render_email(n: Notification) -> dict:
    body = [n.summary_line(), ""]
    for label, value in (("고객사", n.customer_id), ("계정", n.account_id),
                         ("리소스", n.resource_id), ("지표", n.metric_key),
                         ("상태", n.state), ("발생", n.occurred_at), ("사유", n.reason)):
        if value:
            body.append(f"{label}: {value}")
    if n.url:
        body += ["", n.url]
    return {"subject": n.summary_line()[:100], "body": "\n".join(body)}


def _render_webhook(n: Notification) -> dict:
    return {"body": json.dumps({
        "title": n.title, "severity": n.severity, "customer_id": n.customer_id,
        "account_id": n.account_id, "resource_id": n.resource_id,
        "resource_type": n.resource_type, "metric_key": n.metric_key,
        "state": n.state, "reason": n.reason, "occurred_at": n.occurred_at,
        "url": n.url, "count": n.count,
    }, ensure_ascii=False)}


SLACK = register(Adapter(
    type="slack",
    label="Slack",
    fields=(
        Field("webhook_url", "Webhook URL", secret=True, check=_slack_webhook),
    ),
    render=_render_slack,
    # Slack Incoming Webhook은 초당 1건이 실질 한계 — 넘으면 429가 온다.
    rate_limit_per_sec=1.0,
    transport=TRANSPORT_HTTPS,
    endpoint_field="webhook_url",
))

EMAIL = register(Adapter(
    type="email",
    label="이메일",
    fields=(
        Field("addresses", "수신 주소", check=_email_list),
    ),
    render=_render_email,
    rate_limit_per_sec=5.0,
    transport=TRANSPORT_EMAIL,
    recipients_field="addresses",
))

WEBHOOK = register(Adapter(
    type="webhook",
    label="범용 Webhook",
    fields=(
        Field("url", "요청 URL", check=_https_url),
        Field("auth_header", "인증 헤더", required=False, secret=True),
    ),
    render=_render_webhook,
    rate_limit_per_sec=5.0,
    transport=TRANSPORT_HTTPS,
    endpoint_field="url",
    auth_header_field="auth_header",
))
