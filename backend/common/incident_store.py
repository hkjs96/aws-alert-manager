"""
인시던트 저장 — 낙관적 잠금 (review-phase2 H2)

인시던트에 쓰는 곳이 셋이다: 라우터(병합·해소), API(확인), 재알림 틱(표시). 전부 "읽고 → 바꾸고 →
통째로 쓰기"였고, 같은 축의 실행이 겹치는 건 예외가 아니라 일상이라(auto-pause 동안 다음 창이 열린다)
서로를 덮어썼다 — 확인이 사라져 `triggered`로 되돌아가고, 구성원이 사라져 아직 울리는데 해소됐다.

이제 모든 쓰기는 **읽은 버전일 때만** 들어간다. 끼어든 쓰기가 있으면 실패하고(`IncidentConflict`),
호출자는 다시 읽어 자기 변경을 그 위에 다시 적용한다. 무엇을 바꾸는지는 `common.incident`의 순수
함수가 정하고, 이 모듈은 그 결과를 안전하게 넣는 일만 한다.

버전 규칙:
- 새 항목: `attribute_not_exists(incident_id)` — 같은 ID가 이미 있으면 충돌
- 버전이 없는 옛 행: 0으로 읽고, 쓸 때 "여전히 버전이 없다"를 조건으로 건다
- 그 밖: `version = 읽은 값`, 쓰면서 +1
"""

from __future__ import annotations

from datetime import datetime

from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from common.incident import from_item, to_item

VERSION_FIELD = "version"

#: 읽고-적용하고-쓰기를 다시 시도하는 횟수. 그 이상 겹치면 그 축이 폭풍 중이라는 뜻이고,
#: 호출자가 사건 기록 없이도 할 일(발송)을 마저 하는 편이 낫다.
MAX_ATTEMPTS = 3


class IncidentConflict(Exception):
    """읽은 뒤 누가 먼저 썼다 — 다시 읽어서 적용할 것."""


def load(table, incident_id: str) -> tuple[dict | None, int | None]:
    """(사건, 버전). 없으면 (None, None). 버전 없는 옛 행은 0."""
    item = table.get_item(Key={"incident_id": incident_id}, ConsistentRead=True).get("Item")
    if not item:
        return None, None
    return from_item(item), int(item.get(VERSION_FIELD, 0) or 0)


def save(table, incident: dict, *, now: datetime, expected_version: int | None) -> dict:
    """조건부 저장. 저장된 사건(새 버전 포함)을 돌려준다.

    `expected_version`: None = 새 항목이어야 한다, 0 = 버전 없는 옛 행, n = 읽은 버전.
    """
    stored = {**incident, VERSION_FIELD: (expected_version or 0) + 1}
    if expected_version is None:
        condition = Attr("incident_id").not_exists()
    elif expected_version == 0:
        condition = Attr("incident_id").exists() & Attr(VERSION_FIELD).not_exists()
    else:
        condition = Attr(VERSION_FIELD).eq(int(expected_version))
    try:
        table.put_item(Item=to_item(stored, now=now), ConditionExpression=condition)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise IncidentConflict(str(incident.get("incident_id", ""))) from None
        raise
    return stored
