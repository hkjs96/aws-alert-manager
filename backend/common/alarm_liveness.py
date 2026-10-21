"""인시던트 구성원이 CloudWatch에서 아직 울리고 있는가 — 해소 이벤트를 영영 못 받는 경우를 메운다.

인시던트는 OK 이벤트가 와야 닫힌다(`fp#…episode_open`). 그런데 **ALARM 상태에서 알람을 지우면 OK 이벤트는
오지 않는다** — 2026-10-21 HOME 실측: WEBFIL 디스크 알람이 ALARM인 채 삭제돼 인시던트가 10-06부터 열려 있었고,
같은 축의 SEV-3 알람이 2주 동안 전부 거기에 붙었다. 이벤트를 놓친 경우도 같다.

그래서 5분 점검이 열린 구성원을 CloudWatch에 직접 묻는다. 판정은 보수적이다: 알람을 **찾았고 ALARM이면** 열린 것,
**찾았고 ALARM이 아니면** 해소 누락, **계정의 모든 리전을 성공적으로 봤는데 없으면** 삭제. 하나라도 확인하지
못하면(권한·네트워크·미등록 계정) 판정하지 않는다 — 살아 있는 사건을 성급히 닫지 않는다.

구성원(series id) 형식: `계정#리소스#메트릭`. 우리 메타데이터가 없는 알람은 리소스 자리에 알람 ARN이 들어간다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from common.alarm_identity import identify_alarm

logger = logging.getLogger(__name__)

FIRING = "firing"
NOT_FIRING = "not_firing"     # 알람은 있는데 ALARM이 아니다 — 해소 이벤트를 놓쳤다
DELETED = "deleted"           # 볼 수 있는 모든 리전에 없다
UNKNOWN = "unknown"           # 확인하지 못했다 — 닫지 않는다

_ALARM_ARN_PREFIX = "arn:aws:cloudwatch:"


@dataclass(frozen=True)
class Member:
    account_id: str
    resource: str
    metric: str

    @property
    def alarm_arn(self) -> str:
        return self.resource if self.resource.startswith(_ALARM_ARN_PREFIX) else ""

    @property
    def region(self) -> str:
        """ARN 구성원만 리전을 안다. 우리 알람 구성원은 계정의 모든 리전을 봐야 한다."""
        parts = self.alarm_arn.split(":")
        return parts[3] if len(parts) > 3 else ""


def parse_member(series_id: str) -> Member | None:
    """`계정#리소스#메트릭` — 리소스(ARN)에 `#`이 없다고 가정하지 않는다: 첫 칸과 마지막 칸만 떼어 낸다."""
    head, sep, rest = str(series_id).partition("#")
    if not sep or not head:
        return None
    resource, _, metric = rest.rpartition("#")
    if not resource:
        return None
    return Member(head, resource, metric)


def _matches(member: Member, alarm: dict) -> bool:
    if member.alarm_arn:
        return alarm.get("AlarmArn") == member.alarm_arn
    identity = identify_alarm(alarm)
    return (identity is not None and identity.resource_id == member.resource
            and (identity.metric_key or "") == member.metric)


def _same_resource_firing(member: Member, alarm: dict) -> bool:
    if alarm.get("StateValue") != "ALARM":
        return False
    identity = identify_alarm(alarm)
    return identity is not None and identity.resource_id == member.resource


def classify(member: Member, alarms_by_region: dict[str, list[dict] | None]) -> str:
    """한 구성원의 상태. `alarms_by_region` 값이 None이면 그 리전은 확인 실패다.

    ARN 구성원은 자기 리전만, 우리 알람 구성원은 주어진 모든 리전을 본다.
    """
    regions = [member.region] if member.region else list(alarms_by_region)
    if not regions:
        return UNKNOWN
    found = []
    for region in regions:
        alarms = alarms_by_region.get(region)
        if alarms is None:
            return UNKNOWN
        found += [a for a in alarms if _matches(member, a)]
    if not found:
        # 우리 알람 구성원은 메트릭 키 대조로 찾는다 — 표기가 어긋나 못 찾았을 수도 있다. 같은 리소스에 울리는
        # 알람이 있으면 삭제라고 단정하지 않는다(울리는 사건을 닫는 쪽이 놓치는 쪽보다 나쁘다).
        if not member.alarm_arn and any(_same_resource_firing(member, a)
                                        for r in regions for a in alarms_by_region.get(r) or []):
            return UNKNOWN
        return DELETED
    return FIRING if any(a.get("StateValue") == "ALARM" for a in found) else NOT_FIRING


def all_quiet(statuses: list[str]) -> bool:
    """열린 구성원이 전부 확실히 조용한가 — 하나라도 울리거나 모르면 닫지 않는다."""
    return bool(statuses) and all(s in (NOT_FIRING, DELETED) for s in statuses)


class LiveAlarms:
    """한 번의 점검 동안 계정·리전별 알람 목록을 한 번만 읽는다. 실패한 리전은 None으로 기억한다.

    `accounts`: 계정 테이블 행(`account_id`, `role_arn`, `regions`). 미등록 계정은 확인하지 않는다(UNKNOWN).
    글로벌 서비스 알람은 us-east-1에 있으므로 우리 알람 구성원은 등록 리전 + us-east-1을 본다.
    """

    def __init__(self, accounts: list[dict], current_account: str):
        self._accounts = {a.get("account_id"): a for a in accounts if a.get("account_id")}
        self._current = current_account
        self._cache: dict[tuple[str, str], list[dict] | None] = {}
        self._sessions: dict[str, object] = {}

    def regions_for(self, account_id: str) -> list[str]:
        account = self._accounts.get(account_id)
        if account is None:
            return []
        return list(dict.fromkeys([*(account.get("regions") or ["ap-northeast-2"]), "us-east-1"]))

    def status(self, member: Member) -> str:
        regions = [member.region] if member.region else self.regions_for(member.account_id)
        if member.account_id not in self._accounts:
            return UNKNOWN
        return classify(member, {r: self._alarms(member.account_id, r) for r in regions})

    def _session(self, account_id: str):
        import boto3   # 지연 import — 판정 함수만 쓰는 테스트가 boto3 세션을 만들지 않게
        if account_id not in self._sessions:
            account = self._accounts[account_id]
            role_arn = account.get("role_arn") or ""
            if not role_arn or account_id == self._current:
                self._sessions[account_id] = boto3.session.Session()
            else:
                creds = boto3.client("sts").assume_role(
                    RoleArn=role_arn, RoleSessionName=f"AlertRouterLiveness-{account_id}",
                )["Credentials"]
                self._sessions[account_id] = boto3.session.Session(
                    aws_access_key_id=creds["AccessKeyId"], aws_secret_access_key=creds["SecretAccessKey"],
                    aws_session_token=creds["SessionToken"],
                )
        return self._sessions[account_id]

    def _alarms(self, account_id: str, region: str) -> list[dict] | None:
        from botocore.exceptions import BotoCoreError, ClientError
        key = (account_id, region)
        if key not in self._cache:
            try:
                cw = self._session(account_id).client("cloudwatch", region_name=region)
                alarms: list[dict] = []
                for page in cw.get_paginator("describe_alarms").paginate(AlarmTypes=["MetricAlarm"]):
                    alarms.extend(page.get("MetricAlarms", []))
                self._cache[key] = alarms
            except (ClientError, BotoCoreError) as e:
                logger.warning("liveness: alarms unreadable (account=%s region=%s): %s", account_id, region, e)
                self._cache[key] = None
        return self._cache[key]
