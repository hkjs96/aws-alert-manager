"""
/jobs 엔드포인트

GET /jobs/{id}  → 작업 상태 조회
"""

import json
from botocore.exceptions import ClientError

from api_handler.db import job_status_table


def get_job(event: dict) -> dict:
    job_id = (event.get("pathParameters") or {}).get("id", "")
    if not job_id:
        return {"statusCode": 400, "body": json.dumps({"code": "BAD_REQUEST", "message": "job_id 필요"})}

    try:
        item = job_status_table().get_item(Key={"job_id": job_id}).get("Item")
    except ClientError as e:
        return {"statusCode": 500, "body": json.dumps({"code": "INTERNAL_ERROR", "message": str(e)})}

    if not item:
        return {"statusCode": 404, "body": json.dumps({"code": "NOT_FOUND", "message": "Job not found"})}

    # DynamoDB returns Decimal for numeric attrs (counts, results); default=str
    # keeps json.dumps from raising TypeError -> uncaught 500 (matches other routes).
    return {"statusCode": 200, "body": json.dumps(item, default=str)}
