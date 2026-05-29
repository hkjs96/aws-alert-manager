"""
common.resource_discovery.cleanup_stale_inventory 단위 테스트.

핵심 안전 속성:
- 디스커버리에 없는 리소스는 삭제된다.
- 디스커버리가 통째로 빈 계정의 인벤토리는 보존된다(전멸 방지).
- 알람 스냅샷/비-resource 항목은 절대 삭제되지 않는다.
"""

from unittest.mock import MagicMock

from common.resource_discovery import cleanup_stale_inventory


def _item(resource_id, account_id, entity_type="resource"):
    return {"resource_id": resource_id, "account_id": account_id, "entity_type": entity_type}


def test_deletes_resource_absent_from_discovery():
    table = MagicMock()
    db_items = [
        _item("i-keep", "111"),
        _item("i-stale", "111"),
    ]
    discovered = [{"resource_id": "i-keep", "account_id": "111"}]

    removed = cleanup_stale_inventory(table, db_items, discovered)

    assert removed == 1
    table.delete_item.assert_called_once_with(Key={"resource_id": "i-stale", "account_id": "111"})


def test_empty_discovery_deletes_nothing():
    """Critical 가드: 디스커버리가 비면(전체 실패 가능) 아무것도 지우지 않는다."""
    table = MagicMock()
    db_items = [_item("i-1", "111"), _item("i-2", "111")]

    removed = cleanup_stale_inventory(table, db_items, [])

    assert removed == 0
    table.delete_item.assert_not_called()


def test_account_with_no_discovery_is_preserved():
    """디스커버리가 계정 111만 반환하면, 계정 222 항목은 보존된다."""
    table = MagicMock()
    db_items = [
        _item("i-aaa", "111"),  # stale in a discovered account → delete
        _item("i-bbb", "222"),  # account 222 had no discovery → preserve
    ]
    discovered = [{"resource_id": "i-keep", "account_id": "111"}]

    removed = cleanup_stale_inventory(table, db_items, discovered)

    assert removed == 1
    table.delete_item.assert_called_once_with(Key={"resource_id": "i-aaa", "account_id": "111"})


def test_alarm_and_non_resource_items_are_never_deleted():
    table = MagicMock()
    db_items = [
        _item("alarm#arn:aws:cloudwatch:...", "111", entity_type="alarm"),
        _item("alarm#legacy-no-entity", "111", entity_type="resource"),  # prefix guard
        _item("job#123", "111", entity_type="job"),
    ]
    discovered = [{"resource_id": "i-keep", "account_id": "111"}]

    removed = cleanup_stale_inventory(table, db_items, discovered)

    assert removed == 0
    table.delete_item.assert_not_called()


def test_item_present_in_discovery_is_kept():
    table = MagicMock()
    db_items = [_item("i-live", "111")]
    discovered = [{"resource_id": "i-live", "account_id": "111"}]

    removed = cleanup_stale_inventory(table, db_items, discovered)

    assert removed == 0
    table.delete_item.assert_not_called()


def test_id_fallback_when_resource_id_missing():
    """디스커버리 항목이 resource_id 대신 id만 가져도 키 매칭된다(#5a)."""
    table = MagicMock()
    db_items = [_item("i-live", "111"), _item("i-stale", "111")]
    discovered = [{"id": "i-live", "account_id": "111"}]

    removed = cleanup_stale_inventory(table, db_items, discovered)

    assert removed == 1
    table.delete_item.assert_called_once_with(Key={"resource_id": "i-stale", "account_id": "111"})
