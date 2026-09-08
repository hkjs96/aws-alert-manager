"""
테스트용 가짜 DynamoDB 테이블·Step Functions — 조건식과 인덱스 조회를 실제처럼 해석한다.

mock으로는 낙관적 잠금(조건부 PutItem)과 인덱스 조회의 **상호작용**을 검증할 수 없다.
이 가짜들은 boto3 조건 객체의 `get_expression()`을 해석해 실제 DynamoDB와 같은 결과를 낸다.
"""

from __future__ import annotations

import json

from botocore.exceptions import ClientError


def conditional_failure():
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}}, "PutItem")


def _eval(cond, item: dict | None) -> bool:
    expr = cond.get_expression()
    op, values = expr["operator"], expr["values"]
    if op == "attribute_not_exists":
        return item is None or values[0].name not in item
    if op == "attribute_exists":
        return item is not None and values[0].name in item
    if op == "=":
        return item is not None and item.get(values[0].name) == values[1]
    if op == "<>":
        return item is None or item.get(values[0].name) != values[1]
    if op == "OR":
        return _eval(values[0], item) or _eval(values[1], item)
    if op == "AND":
        return _eval(values[0], item) and _eval(values[1], item)
    raise AssertionError(f"unsupported condition operator {op}")


class FakeStateTable:
    """단일 키(`state_key`) 테이블. 조건부 PutItem을 해석한다."""

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.puts = 0

    def get_item(self, Key, **_):
        it = self.items.get(Key["state_key"])
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item, ConditionExpression=None, **_):
        cur = self.items.get(Item["state_key"])
        if ConditionExpression is not None and not _eval(ConditionExpression, cur):
            raise conditional_failure()
        self.items[Item["state_key"]] = dict(Item)
        self.puts += 1

    def delete_item(self, Key, **_):
        self.items.pop(Key["state_key"], None)

    def by_prefix(self, prefix: str) -> dict[str, dict]:
        return {k: v for k, v in self.items.items() if k.startswith(prefix)}


class FakeHistoryTable:
    """(series_id, event_key) 테이블 + `group_id-index` 조회 + UpdateItem(SET) 해석."""

    def __init__(self):
        self.items: dict[tuple, dict] = {}

    def put_item(self, Item, ConditionExpression=None, **_):
        key = (Item["series_id"], Item["event_key"])
        if ConditionExpression is not None and not _eval(ConditionExpression, self.items.get(key)):
            raise conditional_failure()
        self.items[key] = dict(Item)

    def query(self, IndexName=None, KeyConditionExpression=None, **_):
        expr = KeyConditionExpression.get_expression()
        assert expr["operator"] == "=", expr
        field, value = expr["values"][0].name, expr["values"][1]
        if IndexName == "group_id-index":
            assert field == "group_id"
        return {"Items": [dict(i) for i in self.items.values() if i.get(field) == value]}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, **_):
        item = self.items[(Key["series_id"], Key["event_key"])]
        assert UpdateExpression.startswith("SET ")
        for part in UpdateExpression[4:].split(","):
            name, ref = (x.strip() for x in part.split("="))
            item[name] = ExpressionAttributeValues[ref]

    def by_series(self, series_id: str) -> list[dict]:
        return sorted((i for i in self.items.values() if i["series_id"] == series_id),
                      key=lambda i: i["event_key"])


class FakeConfigTable:
    """(config_type, config_id) 복합 키 테이블 — 정제 정책과 정비창."""

    def __init__(self):
        self.items: dict[tuple, dict] = {}
        self.queries = 0
        self.gets = 0
        self.page_size = 0          # >0이면 그만큼씩 나눠 돌려준다(페이지네이션 검증용)

    def get_item(self, Key, **_):
        self.gets += 1
        it = self.items.get((Key["config_type"], Key["config_id"]))
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item, **_):
        self.items[(Item["config_type"], Item["config_id"])] = dict(Item)

    def delete_item(self, Key, **_):
        self.items.pop((Key["config_type"], Key["config_id"]), None)

    def query(self, KeyConditionExpression=None, ExclusiveStartKey=None, **_):
        self.queries += 1
        expr = KeyConditionExpression.get_expression()
        assert expr["operator"] == "=", expr
        wanted = expr["values"][1]
        rows = [dict(v) for k, v in sorted(self.items.items()) if k[0] == wanted]
        if not self.page_size:
            return {"Items": rows}
        start = 0
        if ExclusiveStartKey:
            ids = [r["config_id"] for r in rows]
            start = ids.index(ExclusiveStartKey["config_id"]) + 1
        page = rows[start:start + self.page_size]
        out: dict = {"Items": page}
        if start + self.page_size < len(rows) and page:
            out["LastEvaluatedKey"] = {"config_type": wanted, "config_id": page[-1]["config_id"]}
        return out


class FakeSfn:
    """StartExecution 기록. 같은 이름은 ExecutionAlreadyExists — 실제와 같다."""

    def __init__(self, fail_with: str | None = None):
        self.calls: list[dict] = []
        self.names: set[str] = set()
        self.fail_with = fail_with

    def start_execution(self, stateMachineArn, name, input):
        if self.fail_with:
            raise ClientError({"Error": {"Code": self.fail_with, "Message": "x"}}, "StartExecution")
        if name in self.names:
            raise ClientError({"Error": {"Code": "ExecutionAlreadyExists", "Message": name}},
                              "StartExecution")
        self.names.add(name)
        self.calls.append({"stateMachineArn": stateMachineArn, "name": name, "input": json.loads(input)})
        return {"executionArn": stateMachineArn.replace(":stateMachine:", ":execution:") + ":" + name}
