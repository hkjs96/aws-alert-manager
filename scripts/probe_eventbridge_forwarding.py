#!/usr/bin/env python3
"""
EventBridge 크로스 리전 알람 이벤트 포워딩 프로브 (alert-pipeline tasks.md 1.1)

판정 대상 (design.md U5): **고객사 리전(서울)의 CloudWatch 알람 이벤트가
우리 리전(us-east-1)의 이벤트 버스까지 실제로 도달하는가.**
AWS 문서상 크로스 리전 이벤트 버스 타깃은 "지원 목적지 리전"으로 제한되므로 실측이 필요하다.
이 결과에 따라 D1(EventBridge 수집)이 그대로 가거나 리전별 버스 대안으로 바뀐다.

구성 (전부 임시, 종료 시 삭제):

    [서울 ap-northeast-2]                    [버지니아 us-east-1]
    테스트 알람 ──▶ 기본 이벤트 버스              프로브 이벤트 버스
                        │  룰 + 전달 역할              │  룰
                        └──────── 크로스 리전 ────────▶└──▶ SQS 큐 ──▶ 확인

사용:
    AWS_PROFILE=xxx python scripts/probe_eventbridge_forwarding.py
    AWS_PROFILE=xxx python scripts/probe_eventbridge_forwarding.py --keep   # 정리 생략(디버깅)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# Windows 콘솔 기본 코드페이지(cp949)는 한글 외 기호(✅ 등)에서 UnicodeEncodeError를 낸다.
# 이 저장소는 배포 스크립트에서도 같은 문제를 겪었다 — 출력 스트림을 UTF-8로 고정한다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

NAME = "alarm-pipeline-probe"
ALARM_NAME = "[PROBE] eventbridge-forwarding DELETE-ME"
SRC_REGION = "ap-northeast-2"      # 고객사 리전 역할
DST_REGION = "us-east-1"           # 우리 스택 리전
POLL_SECONDS = 90                  # 이벤트 도달 대기 상한


def log(step: str, msg: str) -> None:
    print(f"[{step}] {msg}", flush=True)


class Probe:
    def __init__(self, session, keep: bool):
        self.keep = keep
        self.account = session.client("sts").get_caller_identity()["Account"]
        self.src_events = session.client("events", region_name=SRC_REGION)
        self.src_cw = session.client("cloudwatch", region_name=SRC_REGION)
        self.dst_events = session.client("events", region_name=DST_REGION)
        self.dst_sqs = session.client("sqs", region_name=DST_REGION)
        self.iam = session.client("iam")
        self.created: list[tuple[str, str]] = []   # (종류, 식별자) — 역순 정리용
        self.bus_arn = f"arn:aws:events:{DST_REGION}:{self.account}:event-bus/{NAME}"
        self.queue_url = ""
        self.queue_arn = f"arn:aws:sqs:{DST_REGION}:{self.account}:{NAME}"
        self.role_arn = f"arn:aws:iam::{self.account}:role/{NAME}-forward"

    # ── 목적지(us-east-1) ────────────────────────────────
    def setup_destination(self) -> None:
        log("1/6", f"{DST_REGION}: SQS 큐 생성")
        # SQS는 같은 이름 큐를 지운 뒤 60초간 재생성을 막는다 — 연속 실행 시 걸린다.
        for attempt in range(8):
            try:
                self.queue_url = self.dst_sqs.create_queue(QueueName=NAME)["QueueUrl"]
                break
            except ClientError as e:
                if e.response["Error"]["Code"] != "AWS.SimpleQueueService.QueueDeletedRecently":
                    raise
                log("1/6", f"  큐 재생성 대기 중 ... ({attempt + 1}/8)")
                time.sleep(15)
        else:
            raise RuntimeError("SQS 큐 재생성 대기 시간 초과")
        self.created.append(("sqs", self.queue_url))

        # 큐 정책: 이 계정의 EventBridge만 발행 허용
        self.dst_sqs.set_queue_attributes(
            QueueUrl=self.queue_url,
            Attributes={"Policy": json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"Service": "events.amazonaws.com"},
                    "Action": "sqs:SendMessage",
                    "Resource": self.queue_arn,
                    "Condition": {"StringEquals": {"aws:SourceAccount": self.account}},
                }],
            })},
        )

        log("2/6", f"{DST_REGION}: 이벤트 버스 + 룰 생성")
        try:
            self.dst_events.create_event_bus(Name=NAME)
        except self.dst_events.exceptions.ResourceAlreadyExistsException:
            pass
        self.created.append(("dst_bus", NAME))

        # 버스에 도착한 CloudWatch 이벤트를 전부 큐로 (detail-type을 좁히지 않는다 —
        # 상태 변경 외에 생성/수정/삭제 이벤트도 오는지 함께 보기 위함, tasks 1.1.4)
        self.dst_events.put_rule(
            Name=NAME, EventBusName=NAME, State="ENABLED",
            EventPattern=json.dumps({"source": ["aws.cloudwatch"]}),
        )
        self.created.append(("dst_rule", NAME))
        self.dst_events.put_targets(
            Rule=NAME, EventBusName=NAME,
            Targets=[{"Id": "queue", "Arn": self.queue_arn}],
        )

    # ── 출발지(서울) ─────────────────────────────────────
    def setup_source(self) -> None:
        log("3/6", "EventBridge 전달용 IAM 역할 생성")
        try:
            self.iam.create_role(
                RoleName=f"{NAME}-forward",
                AssumeRolePolicyDocument=json.dumps({
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Effect": "Allow",
                        "Principal": {"Service": "events.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }],
                }),
                Description="Temporary probe role for cross-region EventBridge forwarding",
            )
        except self.iam.exceptions.EntityAlreadyExistsException:
            pass
        self.created.append(("role", f"{NAME}-forward"))
        self.iam.put_role_policy(
            RoleName=f"{NAME}-forward", PolicyName="PutEvents",
            PolicyDocument=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow", "Action": "events:PutEvents",
                    "Resource": self.bus_arn,
                }],
            }),
        )
        log("3/6", "IAM 전파 대기 (10초)")
        time.sleep(10)

        log("4/6", f"{SRC_REGION}: 기본 버스 룰 → {DST_REGION} 버스로 전달")
        self.src_events.put_rule(
            Name=NAME, State="ENABLED",
            EventPattern=json.dumps({"source": ["aws.cloudwatch"]}),
        )
        self.created.append(("src_rule", NAME))
        # 크로스 리전 타깃: 목적지 버스 ARN + 전달 역할
        resp = self.src_events.put_targets(
            Rule=NAME,
            Targets=[{"Id": "crossregion", "Arn": self.bus_arn, "RoleArn": self.role_arn}],
        )
        if resp.get("FailedEntryCount"):
            raise RuntimeError(f"put_targets 실패: {resp.get('FailedEntries')}")

    # ── 알람 발화 ────────────────────────────────────────
    def fire_alarm(self) -> None:
        log("5/6", f"{SRC_REGION}: 테스트 알람 생성 후 강제 발화")
        self.src_cw.put_metric_alarm(
            AlarmName=ALARM_NAME, Namespace="AWS/EC2", MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": "i-0000000000probe00"}],
            Statistic="Average", Period=300, EvaluationPeriods=1, Threshold=99.0,
            ComparisonOperator="GreaterThanThreshold", ActionsEnabled=False,
            TreatMissingData="notBreaching",
            AlarmDescription="EventBridge forwarding probe — safe to delete",
        )
        self.created.append(("alarm", ALARM_NAME))
        time.sleep(3)
        # set_alarm_state로 상태 전이를 즉시 만든다 (실제 메트릭을 기다리지 않는다)
        self.src_cw.set_alarm_state(
            AlarmName=ALARM_NAME, StateValue="ALARM",
            StateReason="EventBridge cross-region forwarding probe",
        )

    # ── 도달 확인 ────────────────────────────────────────
    def wait_for_events(self) -> list[dict]:
        log("6/6", f"{DST_REGION} 큐에서 이벤트 대기 (최대 {POLL_SECONDS}초)")
        received: list[dict] = []
        deadline = time.time() + POLL_SECONDS
        while time.time() < deadline:
            msgs = self.dst_sqs.receive_message(
                QueueUrl=self.queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=10,
            ).get("Messages", [])
            for m in msgs:
                try:
                    received.append(json.loads(m["Body"]))
                except json.JSONDecodeError:
                    pass
                self.dst_sqs.delete_message(
                    QueueUrl=self.queue_url, ReceiptHandle=m["ReceiptHandle"],
                )
            if received:
                # 첫 이벤트 후 잠깐 더 모은다 (설정 변경 이벤트가 뒤따라올 수 있음)
                time.sleep(8)
                more = self.dst_sqs.receive_message(
                    QueueUrl=self.queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=5,
                ).get("Messages", [])
                for m in more:
                    try:
                        received.append(json.loads(m["Body"]))
                    except json.JSONDecodeError:
                        pass
                    self.dst_sqs.delete_message(
                        QueueUrl=self.queue_url, ReceiptHandle=m["ReceiptHandle"],
                    )
                break
        return received

    # ── 정리 ─────────────────────────────────────────────
    def teardown(self) -> None:
        if self.keep:
            log("정리", "--keep 지정 — 리소스를 남긴다. 수동 삭제 필요:")
            for kind, ident in self.created:
                print(f"        {kind}: {ident}")
            return
        log("정리", "임시 리소스 삭제")
        for kind, ident in reversed(self.created):
            try:
                if kind == "alarm":
                    self.src_cw.delete_alarms(AlarmNames=[ident])
                elif kind == "src_rule":
                    self.src_events.remove_targets(Rule=ident, Ids=["crossregion"], Force=True)
                    self.src_events.delete_rule(Name=ident, Force=True)
                elif kind == "role":
                    self.iam.delete_role_policy(RoleName=ident, PolicyName="PutEvents")
                    self.iam.delete_role(RoleName=ident)
                elif kind == "dst_rule":
                    self.dst_events.remove_targets(
                        Rule=ident, EventBusName=NAME, Ids=["queue"], Force=True)
                    self.dst_events.delete_rule(Name=ident, EventBusName=NAME, Force=True)
                elif kind == "dst_bus":
                    self.dst_events.delete_event_bus(Name=ident)
                elif kind == "sqs":
                    self.dst_sqs.delete_queue(QueueUrl=ident)
            except ClientError as e:
                print(f"        ! {kind} {ident} 삭제 실패 (수동 확인 필요): {e}", file=sys.stderr)


def report(received: list[dict]) -> int:
    print("\n" + "=" * 68)
    if not received:
        print("판정: ❌ 이벤트가 도달하지 않음")
        print()
        print(f"  {SRC_REGION} → {DST_REGION} 크로스 리전 포워딩이 동작하지 않는다.")
        print("  → design.md D1 수정 필요: 리전별로 우리 계정 버스를 두는 대안으로 전환")
        print("=" * 68)
        return 2

    print("판정: ✅ 크로스 리전 포워딩 동작 확인")
    print()
    print(f"  {SRC_REGION} 알람 이벤트가 {DST_REGION} 버스까지 도달했다 (총 {len(received)}건).")
    print("  → design.md D1(EventBridge 수집) 전제 성립. U5 해소.")
    print()
    print("  수신한 이벤트:")
    for ev in received:
        detail = ev.get("detail", {})
        state = detail.get("state", {}).get("value", "")
        print(f"    - detail-type: {ev.get('detail-type')}")
        print(f"      source={ev.get('source')} region={ev.get('region')} "
              f"account={ev.get('account')}")
        if state:
            print(f"      알람 상태: {state} / 사유: {detail.get('state', {}).get('reason', '')[:60]}")
    types = {ev.get("detail-type") for ev in received}
    print()
    print(f"  detail-type 종류: {', '.join(sorted(t for t in types if t))}")
    if any("Configuration" in (t or "") for t in types):
        print("  → 알람 생성/수정/삭제(구성 변경) 이벤트도 수신됨 (tasks 1.1.4 충족)")
    else:
        print("  ⚠️ 상태 변경만 수신됨 — 구성 변경 이벤트는 이 창에서 관측 안 됨")
    print("=" * 68)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="EventBridge 크로스 리전 포워딩 실측")
    ap.add_argument("--keep", action="store_true", help="종료 시 리소스를 남긴다(디버깅)")
    args = ap.parse_args()

    session = boto3.Session()
    probe = Probe(session, args.keep)
    print(f"계정 {probe.account} · {SRC_REGION} → {DST_REGION} "
          f"· {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z\n")

    received: list[dict] = []
    try:
        probe.setup_destination()
        probe.setup_source()
        probe.fire_alarm()
        received = probe.wait_for_events()
    except (ClientError, RuntimeError) as e:
        print(f"\n프로브 실패: {e}", file=sys.stderr)
        return 1
    finally:
        probe.teardown()

    return report(received)


if __name__ == "__main__":
    sys.exit(main())
