---
inclusion: always
---

# 안티패턴 (Anti-Patterns) — 절대 금지 목록

> 이 문서는 프로젝트 전체에서 절대 사용하지 않아야 하는 패턴을 정의한다.
> 새 코드 작성 시, 코드 리뷰 시 이 목록을 반드시 확인한다.

## Python (Backend / Lambda)

### AP-1. 하드코딩된 시크릿
```python
# ❌ 금지
AWS_ACCESS_KEY = "AKIA..."
DB_PASSWORD = "my-secret-password"

# ✅ 올바른 방법
# 환경 변수 또는 AWS Secrets Manager / SSM Parameter Store 사용
import os
db_password = os.environ["DB_PASSWORD"]
```

### AP-2. 순환 참조 (Circular Import)
```python
# ❌ 금지: module_a.py → module_b.py → module_a.py
# 순환 참조가 발생하면 모듈 구조를 재설계한다.
# 공통 타입/상수는 common/__init__.py 또는 별도 types 모듈로 분리한다.
```

### AP-3. 알람 이름 문자열 매칭
```python
# ❌ 금지: 알람 이름에서 메트릭/리소스 정보를 파싱
if "CPUUtilization" in alarm_name:
    ...

# ✅ 올바른 방법: 알람 메타데이터(Namespace, MetricName, Dimensions) 기반 매칭
alarm_metric = alarm["MetricName"]
```

### AP-4. 전체 알람 풀스캔
```python
# ❌ 금지: describe_alarms()로 전체 알람을 가져와서 필터링
all_alarms = cw.describe_alarms()["MetricAlarms"]
my_alarms = [a for a in all_alarms if resource_id in a["AlarmName"]]

# ✅ 올바른 방법: AlarmNamePrefix 기반 검색
alarms = cw.describe_alarms(AlarmNamePrefix=f"[{resource_type}]")
```

### AP-5. except Exception 남용
```python
# ❌ 금지 (최상위 핸들러 제외)
try:
    cw.put_metric_alarm(...)
except Exception as e:
    logger.error(f"Failed: {e}")

# ✅ 올바른 방법
from botocore.exceptions import ClientError
try:
    cw.put_metric_alarm(...)
except ClientError as e:
    logger.error("알람 생성 실패: %s", e)
```

### AP-6. f-string 로깅
```python
# ❌ 금지
logger.error(f"리소스 {resource_id} 처리 실패: {e}")

# ✅ 올바른 방법: % 포맷 (lazy evaluation)
logger.error("리소스 %s 처리 실패: %s", resource_id, e)
```

### AP-7. 모듈 레벨 global 변수로 boto3 클라이언트 관리
```python
# ❌ 금지
_client = None
def get_client():
    global _client
    if _client is None:
        _client = boto3.client("cloudwatch")
    return _client

# ✅ 올바른 방법: functools.lru_cache
@functools.lru_cache(maxsize=None)
def _get_cw_client():
    return boto3.client("cloudwatch")
```

### AP-8. alive 체크 로직을 lambda_handler에 직접 작성
```python
# ❌ 금지: daily_monitor/lambda_handler.py에 리소스별 alive 체크 하드코딩
if resource_type == "EC2":
    ec2.describe_instances(InstanceIds=[resource_id])

# ✅ 올바른 방법: 각 Collector의 resolve_alive_ids() 메서드에서 처리
alive_ids = collector.resolve_alive_ids(tag_names)
```

## 테스트 (pytest / unittest.mock)

### AP-15. 페이지네이션 코드를 bare MagicMock 테이블로 호출 (무한 루프 → 수 GB)
`while True: resp = table.query(...); if not resp.get("LastEvaluatedKey"): break`
같은 DynamoDB 페이지네이션은, mock 테이블의 해당 메서드를 설정하지 않으면 **무한 루프**에 빠진다.
`MagicMock().query().get("LastEvaluatedKey")`는 None이 아니라 **항상 truthy한 자식 MagicMock**을
반환하므로 `if not last`가 영원히 거짓 → 루프가 안 끝나고, 매 반복의 `table.query(...)` 호출이
`mock_calls`에 무한 누적되어 RSS가 수 GB까지 치솟고 테스트가 멈춘다(겉보기엔 "느린 테스트").

```python
# ❌ 금지: query/scan을 설정하지 않은 bare mock 테이블을 페이지네이션 코드에 전달
table = MagicMock()
query_inventory_by_accounts(table, ["123"])   # while True 무한 루프 → 수 GB RSS

# ✅ 올바른 방법: 종료 페이지를 stub (진짜 dict → .get가 None 반환 → 루프 종료)
table = MagicMock()
table.query.return_value = {"Items": []}       # LastEvaluatedKey 없음 → 1회 후 종료
# 여러 페이지를 검증하려면 side_effect의 마지막 페이지에서 LastEvaluatedKey를 빼라
table.query.side_effect = [
    {"Items": [...], "LastEvaluatedKey": {"k": 1}},
    {"Items": [...]},                          # 종료 페이지
]
```
> 교훈: 페이지네이션 헬퍼를 바꾸면(예: `scan` → `query`) 그 테이블 메서드를 stub하던
> **모든 테스트의 mock 설정도 함께 갱신**한다. 이번 사례는 `query_inventory_by_accounts`
> 도입 시 `.scan`만 stub하던 테스트가 `.query`를 안 채워 발생했다.

## TypeScript / Next.js (Frontend)

### AP-9. any 타입 사용
```typescript
// ❌ 금지
const data: any = await fetchData();

// ✅ 올바른 방법
interface AlarmData { ... }
const data: AlarmData = await fetchData();
```

### AP-10. 페이지/레이아웃에 'use client' 선언
```typescript
// ❌ 금지: page.tsx, layout.tsx에 'use client'
'use client'
export default function DashboardPage() { ... }

// ✅ 올바른 방법: 상호작용 부분만 별도 Client Component로 분리
// page.tsx (Server Component)
export default function DashboardPage() {
  return <InteractiveFilter />  // 이것만 'use client'
}
```

### AP-11. 클라이언트에 민감 데이터 노출
```typescript
// ❌ 금지: DB 레코드 전체를 props로 전달
<ClientComponent data={fullDbRecord} />

// ✅ 올바른 방법: 필요한 필드만 DTO로 전달
<ClientComponent data={{ id: record.id, name: record.name }} />
```

### AP-12. 환경 변수 접두사 오용
```typescript
// ❌ 금지: 서버 전용 시크릿에 NEXT_PUBLIC_ 접두사
NEXT_PUBLIC_DB_URL=postgresql://...

// ✅ 올바른 방법: 서버 전용은 접두사 없이
DB_URL=postgresql://...
```

## 인프라 (CloudFormation)

### AP-13. 하드코딩된 리전/계정 ID
```yaml
# ❌ 금지
Resources:
  MyBucket:
    Properties:
      BucketName: my-bucket-123456789012-ap-northeast-2

# ✅ 올바른 방법: Pseudo Parameters 사용
BucketName: !Sub "${AWS::StackName}-${AWS::AccountId}-${AWS::Region}"
```

### AP-14. Lambda 런타임 버전 분산 관리
```yaml
# ❌ 금지: 각 Lambda에 런타임 직접 지정
Runtime: python3.12

# ✅ 올바른 방법: Mappings에서 단일 관리
Runtime: !FindInMap [LambdaConfig, Settings, Runtime]
```
