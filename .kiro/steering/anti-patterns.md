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
