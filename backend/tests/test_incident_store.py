"""
인시던트 저장의 낙관적 잠금 (`common/incident_store.py`, review-phase2 H2)

쓰기는 읽은 버전일 때만 들어간다. 여기서 고정하는 건 버전 규칙 셋 — 새 항목·옛 행(버전 없음)·
읽은 버전 — 과 "충돌은 예외로 드러난다"는 계약이다. 재시도는 호출자의 몫이다.
"""

from datetime import datetime, timezone

import pytest

from common.incident import new_incident
from common.incident_store import IncidentConflict, load, save
from tests.test_alert_router import FakeIncidentTable

T0 = datetime(2026, 9, 9, 10, 0, 0, tzinfo=timezone.utc)


def fresh():
    return new_incident("cust-1", "SEV-2", now=T0, title="[EC2] i-1 CPU > 80%")


class TestSave:
    def test_new_item_gets_version_one(self):
        table = FakeIncidentTable()
        saved = save(table, fresh(), now=T0, expected_version=None)
        assert saved["version"] == 1
        assert table.items[saved["incident_id"]]["version"] == 1

    def test_new_item_conflicts_when_the_id_already_exists(self):
        table = FakeIncidentTable()
        inc = fresh()
        save(table, inc, now=T0, expected_version=None)
        with pytest.raises(IncidentConflict):
            save(table, inc, now=T0, expected_version=None)

    def test_matching_version_bumps(self):
        table = FakeIncidentTable()
        inc = save(table, fresh(), now=T0, expected_version=None)
        again = save(table, {**inc, "title": "changed"}, now=T0, expected_version=1)
        assert again["version"] == 2 and table.items[inc["incident_id"]]["title"] == "changed"

    def test_stale_version_conflicts_and_leaves_the_row_alone(self):
        table = FakeIncidentTable()
        inc = save(table, fresh(), now=T0, expected_version=None)
        save(table, {**inc, "title": "second writer"}, now=T0, expected_version=1)
        with pytest.raises(IncidentConflict):
            save(table, {**inc, "title": "first writer, late"}, now=T0, expected_version=1)
        assert table.items[inc["incident_id"]]["title"] == "second writer"

    def test_legacy_row_without_a_version_is_accepted_as_zero(self):
        table = FakeIncidentTable()
        inc = fresh()
        table.items[inc["incident_id"]] = dict(inc)          # 버전 없음
        loaded, version = load(table, inc["incident_id"])
        assert version == 0
        saved = save(table, loaded, now=T0, expected_version=0)
        assert saved["version"] == 1

    def test_legacy_row_rejects_a_writer_that_assumed_a_version(self):
        table = FakeIncidentTable()
        inc = fresh()
        table.items[inc["incident_id"]] = dict(inc)
        with pytest.raises(IncidentConflict):
            save(table, inc, now=T0, expected_version=1)

    def test_zero_is_not_accepted_once_a_version_exists(self):
        table = FakeIncidentTable()
        inc = save(table, fresh(), now=T0, expected_version=None)
        with pytest.raises(IncidentConflict):
            save(table, inc, now=T0, expected_version=0)


class TestLoad:
    def test_missing_is_none_none(self):
        assert load(FakeIncidentTable(), "nope") == (None, None)

    def test_returns_the_incident_and_its_version(self):
        table = FakeIncidentTable()
        inc = save(table, fresh(), now=T0, expected_version=None)
        loaded, version = load(table, inc["incident_id"])
        assert version == 1 and loaded["incident_id"] == inc["incident_id"]
        assert "ttl" not in loaded
