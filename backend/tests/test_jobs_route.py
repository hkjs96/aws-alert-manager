"""GET /jobs/{id} 라우트 테스트.

회귀: job 레코드는 DynamoDB에서 Decimal(count/results)을 담아 돌아오므로
json.dumps(item)이 default=str 없이는 TypeError로 터져 500을 낸다.
프론트는 그 500을 "Failed to connect to monitoring job tracker."로 표시한다.
"""

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from api_handler.routes import jobs


def _event(job_id: str) -> dict:
    # 라우터가 정규식 (?P<id>...)로 채워주는 형태
    return {"pathParameters": {"id": job_id}}


def test_get_job_serializes_decimal_item():
    item = {
        "job_id": "job-abc",
        "status": "completed",
        "total_count": Decimal("1"),
        "completed_count": Decimal("1"),
        "failed_count": Decimal("0"),
        "results": [{"account_id": "949501913924", "imported": Decimal("1"), "deleted": Decimal("0")}],
    }
    table = MagicMock()
    table.get_item.return_value = {"Item": item}

    with patch.object(jobs, "job_status_table", return_value=table):
        resp = jobs.get_job(_event("job-abc"))

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])  # Decimal이 살아있으면 여기서 못 옴
    assert body["status"] == "completed"
    assert body["total_count"] == "1"  # default=str로 직렬화됨


def test_get_job_missing_returns_404():
    table = MagicMock()
    table.get_item.return_value = {}
    with patch.object(jobs, "job_status_table", return_value=table):
        resp = jobs.get_job(_event("nope"))
    assert resp["statusCode"] == 404


def test_get_job_blank_id_returns_400():
    resp = jobs.get_job({"pathParameters": {}})
    assert resp["statusCode"] == 400
