"""
알람 정체성 해석 — "이 알람은 어느 리소스의 무슨 메트릭인가"를 한 곳에서 답한다.

우선순위 (듀얼 리드):
  1. AlarmDescription JSON 메타데이터 (정본) — 엔진이 만든 모든 알람에 존재.
     resource_id는 Full ID(ALB/NLB/TG는 ARN)라 인벤토리 resource_id와 그대로 조인된다.
  2. 알람 이름의 MARK 포맷 `[{type}] ... (TagName: {short_id})` — 메타데이터가 없는
     구버전 알람 폴백. short_id는 ALB/NLB/TG/ACM/APIGW-HTTP에서 Full ID가 아니다.
  3. 레거시 EC2 이름 `i-xxx-{metric}-{env}`.

이름 파싱 정규식은 이 모듈(및 이름을 *생성*하는 alarm_naming/alarm_search)에만 둔다.
예전엔 같은 정규식이 프로덕션 5곳(daily_monitor, cw_helper, routes/alarms·dashboard·
resources)에 복제돼 있었고, 이름 기반 short_id를 인벤토리 Full ID와 비교해 ALB 계열의
알람↔리소스 조인이 조용히 실패했다. (tests/test_alarm_identity.py의 가드가 재유입을 막는다)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from common.alarm_naming import _parse_alarm_metadata

# [EC2] label metric > threshold (TagName: resource_id)
_MARK_NAME_RE = re.compile(r"^\[(\w+)\]\s+.+\(TagName:\s*(.+)\)$")
# 레거시 EC2 포맷: i-xxx-metric-env
_LEGACY_EC2_RE = re.compile(r"^(i-[0-9a-f]+)-")

SOURCE_METADATA = "metadata"
SOURCE_NAME = "name"
SOURCE_LEGACY = "legacy"


@dataclass(frozen=True)
class AlarmIdentity:
    resource_type: str
    #: 정본 리소스 ID — 메타데이터가 있으면 Full ID, 없으면 이름의 TagName.
    resource_id: str
    #: 이름 서픽스의 (TagName: ...) 값. 컬렉터 resolve_alive_ids 입력·레거시 매칭용. 없으면 "".
    tag_name: str
    metric_key: str | None
    source: str

    @property
    def match_keys(self) -> frozenset[str]:
        """이 알람을 리소스에 매칭할 때 허용되는 식별자 집합 (Full ID + short ID)."""
        return frozenset(k for k in (self.resource_id, self.tag_name) if k)

    def matches(self, resource_id: str) -> bool:
        return bool(resource_id) and resource_id in self.match_keys


def parse_alarm_name(name: str) -> tuple[str, str] | None:
    """MARK 포맷 이름에서 (resource_type, tag_name)을 추출. 이름만으로 판단할 때 사용."""
    if not name:
        return None
    m = _MARK_NAME_RE.match(name)
    if m:
        return m.group(1), m.group(2)
    return None


def identify_alarm_name(name: str) -> AlarmIdentity | None:
    """이름만으로 정체성 해석 (메타데이터 없음). 관리 포맷이 아니면 None."""
    parsed = parse_alarm_name(name)
    if parsed:
        rtype, tag = parsed
        return AlarmIdentity(rtype, tag, tag, None, SOURCE_NAME)
    legacy = _LEGACY_EC2_RE.match(name or "")
    if legacy:
        iid = legacy.group(1)
        return AlarmIdentity("EC2", iid, iid, None, SOURCE_LEGACY)
    return None


def identify_alarm(alarm: dict) -> AlarmIdentity | None:
    """describe_alarms 항목(AlarmName/AlarmDescription)에서 정체성 해석.

    메타데이터가 있으면 resource_type/resource_id는 메타데이터, tag_name은 이름에서 취한다.
    메타데이터도 없고 이름도 관리 포맷이 아니면 None (인프라 알람 등 — 관리 대상 아님).
    """
    name = alarm.get("AlarmName", "") or ""
    by_name = identify_alarm_name(name)

    metadata = _parse_alarm_metadata(alarm.get("AlarmDescription", "") or "")
    if metadata:
        rid = str(metadata.get("resource_id") or "")
        rtype = str(metadata.get("resource_type") or "")
        if rid and rtype:
            return AlarmIdentity(
                rtype, rid,
                by_name.tag_name if by_name else "",
                metadata.get("metric_key"),
                SOURCE_METADATA,
            )
        # 불완전한 메타데이터 — 이름 폴백에 metric_key만 얹는다
        if by_name and metadata.get("metric_key"):
            return AlarmIdentity(
                by_name.resource_type, by_name.resource_id, by_name.tag_name,
                metadata.get("metric_key"), by_name.source,
            )
    return by_name


def group_alarms_by_resource(alarms: list[dict]) -> dict[str, list[dict]]:
    """알람을 리소스 식별자별로 묶는다. Full ID와 short ID 양쪽 키로 조회 가능하다.

    같은 알람이 두 키 아래 중복으로 들어갈 수 있으므로 values()를 합산하지 말 것 —
    특정 리소스 ID로 조회하는 용도다.
    """
    grouped: dict[str, list[dict]] = {}
    for alarm in alarms:
        identity = identify_alarm(alarm)
        if identity is None:
            continue
        for key in identity.match_keys:
            grouped.setdefault(key, []).append(alarm)
    return grouped
