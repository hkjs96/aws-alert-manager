"""
리소스 타입 레지스트리 — 타입 하나 = 스펙 하나, 나머지는 파생 (docs/specs/resource-type-registry D3)

2026-09까지 한 리소스 타입은 12개 파일 15곳에 흩어져 있었다: 타입 목록, 수집기 모듈 목록과 타입→수집기 맵,
CloudTrail 이벤트 목록(3곳), 태그 캐시가 프라임할 서비스, 글로벌 리전, 알람 정의에서 파생되는 맵 셋.
횡단 변경이 26개 수집기 중 15개에서 멈추고(태그 캐시), 파생 가능한 맵을 손으로 두 번 적어 테스트로 드리프트를
막는 구조였다. 이 모듈이 **한 곳**이다 — 아래 스펙을 고치면 뷰(`types()`·`monitored_api_events()`·
`type_to_collector()`·`tagged_services()`…)가 따라오고, 소비처(`common/__init__`, `daily_monitor`,
`remediation_handler`, `tag_cache`)는 그 뷰를 읽는다.

알림 채널 어댑터(`notification_adapters.py`)와 같은 수법이다: `register()` 하나로 전부 따라온다.

이 패키지는 **표준 라이브러리만** 의존한다 — `alarm_registry`가 이쪽을 import하고 파생 표를 만든다(반대 방향 아님).
수집기는 **모듈 이름**으로만 가리키고(`daily_monitor`가 import한다), CloudTrail payload에서 ID를 뽑는 추출기는
`remediation_handler`에 남긴다(이벤트→타입 매핑만 여기). 그래야 `common/__init__`이 이 패키지를 import해도
순환이 없다.

알람 정의는 타입별 모듈(`common/resource_types/<type>.py`)에 있고 스펙의 `alarm_defs`가 그것이다(P2.4).
표시명·기본 임계치는 아직 `alarm_registry._METRIC_DISPLAY`·`common.HARDCODED_DEFAULTS`에(P2.4b). P3에서 `rgt_filters`가
범용 수집기의 나열 소스가 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# CloudTrail 이벤트 종류 — MONITORED_API_EVENTS의 키. 순서는 옛 상수의 순서를 따른다.
MODIFY, DELETE, TAG_CHANGE, CREATE = "MODIFY", "DELETE", "TAG_CHANGE", "CREATE"
KINDS: tuple[str, ...] = (MODIFY, DELETE, TAG_CHANGE, CREATE)

#: 여러 서비스가 같은 이름을 쓰는 이벤트 — ARN을 봐야 타입이 갈린다. `_API_MAP`은 이걸 "MULTI"로 부른다.
MULTI = "MULTI"


@dataclass(frozen=True)
class Lifecycle:
    """CloudTrail 이벤트 하나. `target`은 remediation이 쓰는 타입 이름 — 기본은 스펙 타입이지만, ELB 계열은
    이벤트 이름이 ALB/NLB/CLB를 구분하지 않아 "ELB"로 받고 ARN으로 가른다."""
    event: str
    kind: str
    target: str = ""


@dataclass(frozen=True)
class ResourceTypeSpec:
    type: str
    label: str
    #: `common.collectors` 아래 모듈 이름. 여러 타입이 하나를 공유할 수 있다(RDS 계열 → rds, LB 계열 → elb).
    collector: str
    #: 같은 수집기를 가리키는 옛 타입 이름(고아 정리 경로가 알람 이름에서 읽는다) — ELB, NATGateway.
    aliases: tuple[str, ...] = ()
    #: Resource Groups Tagging `ResourceTypeFilters`(design.md 부록 A). 실계정에서 유효성 확인됨(2026-09-15).
    rgt_filters: tuple[str, ...] = ()
    #: 런 시작 시 태그 캐시가 이 서비스를 `GetResources`로 프라임하는가(`tag_cache.TAGGED_SERVICES`).
    #: False인 이유는 `notes`에 — EC2 계열은 하위 리소스 ARN이 너무 많고 서버 측 태그 필터가 있다.
    rgt_prime: bool = False
    lifecycle: tuple[Lifecycle, ...] = ()
    #: 메트릭이 us-east-1에만 발행되는 글로벌 서비스.
    global_region: str = ""
    #: 파생 규칙에서 벗어나는 것의 이유. 맵은 이유를 말해 주지 않았다 — 스펙은 말한다(요구사항 R9).
    notes: str = ""
    #: 알람 정의 — 리스트(고정) 또는 `Callable[[resource_tags], list]`(태그 조건부). 정의 dict의 필드는
    #: docs/ALARM-RULES.md. 옛 `alarm_registry._ALARM_DEFS_BY_TYPE`이 여기서 파생된다.
    alarm_defs: list[dict] | Callable[[dict], list[dict]] = ()
    #: 조건부 정의가 읽는 태그의 **모든 조합** — 파생(메트릭 키·네임스페이스)이 전부 열거해 합친다.
    #: 조건 분기에서 태그를 새로 읽으면 여기에도 적는다(완전성 테스트가 함수 소스를 훑어 잡는다).
    variants: tuple[dict, ...] = ()

    def alarms(self, resource_tags: dict | None = None) -> list[dict]:
        """이 타입의 알람 정의(태그 조건부 변형 반영)."""
        entry = self.alarm_defs
        return entry(resource_tags or {}) if callable(entry) else list(entry)

    @property
    def rgt_services(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(f.split(":", 1)[0] for f in self.rgt_filters))

    def events(self) -> tuple[Lifecycle, ...]:
        return tuple(Lifecycle(e.event, e.kind, e.target or self.type) for e in self.lifecycle)


# ────────────────────────────────── 레지스트리

_SPECS: dict[str, ResourceTypeSpec] = {}
_ALIASES: dict[str, str] = {}


def register(spec: ResourceTypeSpec) -> ResourceTypeSpec:
    if spec.type in _SPECS or spec.type in _ALIASES:
        raise ValueError(f"resource type already registered: {spec.type}")
    for alias in spec.aliases:
        if alias in _SPECS or alias in _ALIASES:
            raise ValueError(f"alias already registered: {alias} (for {spec.type})")
    if spec.kind_check():
        raise ValueError(spec.kind_check())
    _SPECS[spec.type] = spec
    for alias in spec.aliases:
        _ALIASES[alias] = spec.type
    return spec


def _kind_check(self: ResourceTypeSpec) -> str:
    bad = [e.event for e in self.lifecycle if e.kind not in KINDS]
    return f"{self.type}: unknown lifecycle kind on {bad}" if bad else ""


ResourceTypeSpec.kind_check = _kind_check      # type: ignore[attr-defined]


def get(type_or_alias: str) -> ResourceTypeSpec:
    key = _ALIASES.get(type_or_alias, type_or_alias)
    try:
        return _SPECS[key]
    except KeyError:
        raise KeyError(f"unknown resource type: {type_or_alias!r} (known: {', '.join(_SPECS)})") from None


def all_specs() -> list[ResourceTypeSpec]:
    return list(_SPECS.values())


def types() -> list[str]:
    """지원 타입 목록 — 등록 순서. `common.SUPPORTED_RESOURCE_TYPES`가 이것이다."""
    return list(_SPECS)


#: 특정 타입에 속하지 않는 생명주기 이벤트. 12개 서비스가 `TagResource`/`UntagResource`를 같은 이름으로 낸다.
SHARED_LIFECYCLE: tuple[Lifecycle, ...] = (
    Lifecycle("TagResource", TAG_CHANGE, target=MULTI),
    Lifecycle("UntagResource", TAG_CHANGE, target=MULTI),
)


# ────────────────────────────────── 파생 뷰 — 소비처가 읽는 이름들

def monitored_api_events() -> dict[str, list[str]]:
    """종류 → CloudTrail 이벤트 이름. `common.MONITORED_API_EVENTS`. CFN 템플릿의 EventPattern과 같아야 한다(R8)."""
    out: dict[str, list[str]] = {k: [] for k in KINDS}
    for spec in _SPECS.values():
        for e in spec.events():
            if e.event not in out[e.kind]:
                out[e.kind].append(e.event)
    for e in SHARED_LIFECYCLE:
        if e.event not in out[e.kind]:
            out[e.kind].append(e.event)
    return out


def event_to_type() -> dict[str, str]:
    """CloudTrail 이벤트 → remediation이 처리에 쓰는 타입 이름("ELB"·"MULTI" 포함). `_API_MAP`의 타입 절반."""
    out: dict[str, str] = {}
    for spec in _SPECS.values():
        for e in spec.events():
            if e.event in out and out[e.event] != e.target:
                raise ValueError(f"event {e.event} claimed by {out[e.event]} and {e.target}")
            out[e.event] = e.target
    for e in SHARED_LIFECYCLE:
        out[e.event] = e.target
    return out


def type_to_collector() -> dict[str, str]:
    """타입(별칭 포함) → 수집기 모듈 이름. `daily_monitor._RESOURCE_TYPE_TO_COLLECTOR`."""
    out: dict[str, str] = {}
    for spec in _SPECS.values():
        out[spec.type] = spec.collector
        for alias in spec.aliases:
            out[alias] = spec.collector
    return out


def collector_modules() -> list[str]:
    """수집기 모듈 이름 — 중복 제거, 등록 순서. `daily_monitor._COLLECTOR_MODULES`."""
    return list(dict.fromkeys(s.collector for s in _SPECS.values()))


def tagged_services() -> list[str]:
    """태그 캐시가 프라임하는 RGT 서비스 — `rgt_prime`인 스펙의 서비스, 등록 순서. `tag_cache.TAGGED_SERVICES`."""
    return list(dict.fromkeys(svc for s in _SPECS.values() if s.rgt_prime for svc in s.rgt_services))


def global_service_regions() -> dict[str, str]:
    return {s.type: s.global_region for s in _SPECS.values() if s.global_region}
