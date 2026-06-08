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

### AP-17. DynamoDB 아이템을 default=str 없이 json.dumps (Decimal → 500)
DynamoDB는 숫자 속성을 **Decimal**로 돌려준다. 이를 그대로 `json.dumps`하면 `TypeError`가
나고 최상위 핸들러가 잡아 **제네릭 500**을 던진다. 모든 API 라우트는 `default=str`로 직렬화한다.

```python
# ❌ 금지: Decimal(count/results 등)이 섞인 DynamoDB 아이템 직접 직렬화 → TypeError → 500
return {"statusCode": 200, "body": json.dumps(item)}

# ✅ 올바른 방법: 프로젝트 전 라우트 공통 컨벤션
return {"statusCode": 200, "body": json.dumps(item, default=str)}
```
> 교훈: 새 라우트가 DynamoDB 아이템을 반환하면 반드시 `default=str`. 이번 사례는
> `GET /jobs/{id}`만 누락돼 백엔드 job은 완료됐는데도 UI가 "Failed to connect"(AP-16)로
> 표시됐다. 짝이 되는 프론트 규칙은 AP-16 참조.

### AP-18. 관리 알람을 태그 없이 생성/재생성 (조건부 DeleteAlarms로 정리 불가 → 고착)
daily monitor의 `cloudwatch:DeleteAlarms`는 수동 알람 실수 삭제 방지를 위해
`aws:ResourceTag/ManagedBy=AlarmManager` **조건부**다. 따라서 **알람을 만드는 모든 경로**
(`_create_standard_alarm`/`_create_single_alarm`/`_recreate_standard_alarm`/`_recreate_disk_alarm`)는
put 직후 `_tag_alarm_with_severity`로 ManagedBy/Severity 태그를 반드시 부여해야 한다. 한 경로라도
빠지면 그 알람은 태그가 없어, 이후 **임계치 변경(삭제+재생성)·prune·orphan 정리가 AccessDenied로
영구 고착**된다. 태깅 실패를 **조용히 흡수하지 말 것**(권한 누락이 묻힌다).

```python
# ❌ 금지: put 후 태깅 누락 (특히 재생성 경로만 빠뜨리기 쉬움)
cw.put_metric_alarm(AlarmName=name, ...)
# ... _tag_alarm_with_severity 호출 없음 → untagged → 이후 DeleteAlarms AccessDenied

# ✅ 생성·재생성 모든 경로에서 동일하게 태깅
cw.put_metric_alarm(AlarmName=name, ...)
_tag_alarm_with_severity(name, metric_key, cw)
```
> 교훈: 이번 사례는 (a) `_recreate_standard_alarm`/`_recreate_disk_alarm`가 태깅을 빠뜨려
> 임계치 변경 시 untagged 알람을 양산했고, (b) remediation 롤에 TagResource가 없어(AP-19)
> 생성 알람이 전부 untagged였다. 두 갭 모두 임계치가 flat 값에 고착되는 증상으로 나타났다.
> 짝이 되는 IAM 규칙은 AP-19.

### AP-20. 배포 Lambda의 boto3에 없는 최신 API에 정적 폴백 없이 의존
Lambda 런타임 내장 boto3는 로컬보다 **구버전**일 수 있어, 최신 API 호출이
`AttributeError: 'X' object has no attribute '...'`로 깨진다. 새 boto3 API를 쓸 땐 정적 매핑 등
폴백을 두고, `ClientError`뿐 아니라 **`AttributeError`도 함께 catch**한다.

```python
# ❌ 금지: 배포 boto3에 없을 수 있는 API에만 의존 (+ ClientError만 catch)
resp = rds.describe_db_instance_classes(DBInstanceClass=cls)  # 구버전 → AttributeError 전파

# ✅ 정적 매핑 우선 + AttributeError 포함 catch
val = _STATIC_MAP.get(cls)
if val is None:
    try:
        val = _via(rds.describe_db_instance_classes(DBInstanceClass=cls))
    except (ClientError, AttributeError):
        val = None
```
> 교훈: Aurora 로컬스토리지 조회가 배포 boto3의 `describe_db_instance_classes` 부재로 깨져
> FreeLocalStorage 임계치가 flat 폴백으로 떨어졌다. 정적 맵 우선으로 해결. (참고: Aurora
> temp-storage 값은 엔진별로 다르다 — MySQL/PostgreSQL이 같은 클래스라도 값이 다름.)

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

### AP-16. 모든 요청 실패를 단일 "연결 실패" 메시지로 뭉뚱그리기 (백엔드 에러 은폐)
폴링/조회 `catch` 블록이 네트워크 에러와 HTTP 4xx/5xx를 **같은 메시지·같은 status=failed**로
처리하면, 진짜 백엔드 버그(예: 500)가 "Failed to connect"로 가려진다. 또한 "상태 조회 요청
실패"와 "job.status === 'failed'"는 서로 다른 사건인데 한데 묶인다.

```typescript
// ❌ 금지: 모든 예외를 같은 메시지/상태로 처리
catch (err) {
  setErrorMsg("Failed to connect to monitoring job tracker."); // 500도 이걸로 은폐
  setStatus("failed");
}

// ✅ 올바른 방법: HTTP 상태/백엔드 code로 분기, 실제 에러를 노출
catch (err) {
  if (err instanceof HttpError)
    setErrorMsg(`Job tracker error (${err.status}): ${err.body?.message ?? ""}`);
  else
    setErrorMsg("Failed to reach job tracker (network).");
  setStatus("failed");
}
```
> 교훈: 폴링 에러 메시지는 HTTP 상태/백엔드 `code`를 그대로 노출해 백엔드 버그가 UI에
> 묻히지 않게 한다. 짝이 되는 백엔드 직렬화 규칙은 AP-17 참조.

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

### AP-19. 알람 생성 IAM 롤에 cloudwatch:TagResource 누락
알람을 생성하는 **모든** Lambda 롤(daily monitor, remediation handler, sqs worker, api handler)은
`cloudwatch:PutMetricAlarm`과 함께 **`cloudwatch:TagResource`를 반드시 가져야** 한다. 없으면
생성 직후 태깅(`tag_resource`)이 AccessDenied로 실패하고(코드가 조용히 흡수, AP-18), 알람이 태그
없이 남아 daily의 조건부 DeleteAlarms(`aws:ResourceTag/ManagedBy=AlarmManager`)로 **영구 정리 불가**가
된다. 새 알람 생성 경로/롤을 추가할 때 이 권한을 빠뜨리지 말 것.

```yaml
# ❌ 금지: 알람 생성 롤인데 TagResource 없음
- Effect: Allow
  Action:
    - cloudwatch:PutMetricAlarm
    - cloudwatch:DeleteAlarms

# ✅ 올바른 방법: TagResource(+ListTagsForResource) 포함
- Effect: Allow
  Action:
    - cloudwatch:PutMetricAlarm
    - cloudwatch:DeleteAlarms
    - cloudwatch:TagResource
    - cloudwatch:ListTagsForResource
```
> 교훈: 이번 사례는 RemediationHandlerRole에 TagResource가 없어 리소스 생성 이벤트로 만든
> 알람이 전부 untagged → 임계치가 flat 값에 고착됐다. 짝이 되는 코드 규칙은 AP-18.
