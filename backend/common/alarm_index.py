"""
Alarm Index — 런 스코프 인메모리 알람 인덱스

daily run은 계정의 전체 알람을 이미 1회 조회한다(인벤토리 동기화).
그 결과를 재사용해 리소스별 알람 매칭을 메모리에서 수행함으로써,
리소스마다 타입 프리픽스 describe_alarms 스캔(리소스 수 × 타입 알람 수에
비례하는 준제곱 API 콜)을 제거한다.

매칭 규칙은 라이브 검색(alarm_search._find_alarms_for_resource)과 동일한
헬퍼(_candidate_prefixes/_match_suffixes)를 공유한다 — 인덱스 경로와 라이브
경로가 다른 알람을 찾으면 sync가 중복 생성/오삭제를 일으킨다.

주의:
- 글로벌 서비스(CloudFront/Route53) 알람은 us-east-1에 있어 계정 리전
  페치 범위 밖일 수 있다. sync_alarms_for_resource가 글로벌 타입에 대해
  인덱스를 무시하고 라이브 경로로 폴백한다.
- 인덱스는 읽기 전용 스냅샷이다. 같은 런에서 생성/삭제한 알람은 반영되지
  않지만, daily 흐름에서는 리소스당 1회 sync라 문제가 되지 않는다.
"""

import logging

from common.alarm_identity import identify_alarm
from common.alarm_search import _candidate_prefixes, _match_suffixes

logger = logging.getLogger("common.alarm_manager")


class AlarmIndex:
    """describe_alarms 결과 리스트를 감싼 인메모리 조회 인덱스."""

    def __init__(self, alarms: list[dict]):
        # 같은 이름이 여러 리전에서 올 수 있으므로(리전 주석 _region 상이)
        # 이름 → 알람 목록으로 보관한다.
        self._by_name: dict[str, list[dict]] = {}
        for a in alarms:
            name = a.get("AlarmName")
            if name:
                self._by_name.setdefault(name, []).append(a)

    def __len__(self) -> int:
        return len(self._by_name)

    def find_names(
        self,
        resource_id: str,
        resource_type: str = "",
        resource_tags: dict | None = None,
        *,
        region: str = "",
    ) -> list[str]:
        """_find_alarms_for_resource와 동일 의미의 인메모리 매칭.

        region이 주어지면 해당 리전(_region 주석)의 알람만 매칭한다.
        _region 주석이 없는 알람(단일 리전 페치 등)은 리전 무관으로 취급한다.
        """
        prefixes = _candidate_prefixes(resource_type)
        suffixes = _match_suffixes(resource_id, resource_type, resource_tags)

        names: list[str] = []
        for name, entries in self._by_name.items():
            if region and not any(
                not e.get("_region") or e.get("_region") == region
                for e in entries
            ):
                continue
            # 정본: AlarmDescription 메타데이터의 Full ID — 이름과 무관하게 매칭
            identity = identify_alarm(entries[0])
            if (
                identity is not None
                and identity.source == "metadata"
                and identity.resource_id == resource_id
                and (not resource_type or identity.resource_type == resource_type)
            ):
                names.append(name)
                continue
            # 레거시 포맷: {resource_id}-{metric}-{env}
            if name.startswith(resource_id):
                names.append(name)
                continue
            # 새 포맷: [{type}] ... (TagName: {short_id})
            if any(name.startswith(p) for p in prefixes) and any(
                name.endswith(s) for s in suffixes
            ):
                names.append(name)
        return names

    def describe(self, alarm_names: list[str], *, region: str = "") -> dict[str, dict]:
        """_describe_alarms_batch와 동일 형태의 {이름: 알람 dict} 반환 (API 콜 없음)."""
        result: dict[str, dict] = {}
        for name in alarm_names:
            entries = self._by_name.get(name)
            if not entries:
                continue
            picked = entries[0]
            if region:
                picked = next(
                    (e for e in entries if not e.get("_region") or e.get("_region") == region),
                    entries[0],
                )
            result[name] = picked
        return result
