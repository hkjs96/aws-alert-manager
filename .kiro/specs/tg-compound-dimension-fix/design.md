# TG 복합 디멘션 수정 — Bugfix Design

## Overview

TG(Target Group) 알람 생성 시 `TargetGroup` 단일 디멘션만 설정되어 CloudWatch가 메트릭을 찾지 못하는 버그와, ELB 리소스 타입 분리 후 레거시 `[ELB]` 알람이 잔존하는 부차 버그를 수정한다.

수정 전략: 디멘션 구성 로직을 `_build_dimensions()` 헬퍼로 추출하여 `_create_standard_alarm()`, `_create_single_alarm()`, `_recreate_standard_alarm()` 3곳의 중복 코드를 제거하고, TG의 경우 `TargetGroup` + `LoadBalancer` 복합 디멘션을 생성한다. 또한 `_TG_ALARMS`의 하드코딩된 namespace를 `_lb_type` 태그 기반으로 동적 결정한다.

## Glossary

- **Bug_Condition (C)**: `resource_type == "TG"`일 때 알람 디멘션에 `LoadBalancer`가 누락되는 조건
- **Property (P)**: TG 알람 생성 시 `[{"Name": "TargetGroup", ...}, {"Name": "LoadBalancer", ...}]` 복합 디멘션이 포함되어야 함
- **Preservation**: ALB/NLB/EC2/RDS 리소스의 기존 디멘션 로직이 변경 없이 유지됨
- **`_build_dimensions()`**: 신규 헬퍼 함수. `alarm_def`, `resource_id`, `resource_type`, `resource_tags`를 받아 CloudWatch Dimensions 리스트를 반환
- **`_extract_elb_dimension()`**: ARN에서 CloudWatch 디멘션 값(suffix)을 추출하는 기존 함수
- **`_lb_arn`**: ELB collector가 TG 리소스 태그에 설정하는 부모 LB ARN
- **`_lb_type`**: ELB collector가 설정하는 LB 타입 (`"application"` 또는 `"network"`)

## Bug Details

### Bug Condition

TG 리소스에 대해 `_create_standard_alarm()`, `_create_single_alarm()`, `_recreate_standard_alarm()`이 호출될 때, `TargetGroup` 디멘션만 설정되고 `LoadBalancer` 디멘션이 누락된다. CloudWatch의 `AWS/ApplicationELB` (또는 `AWS/NetworkELB`) 네임스페이스에서 TG 메트릭은 반드시 `TargetGroup` + `LoadBalancer` 두 디멘션이 모두 있어야 데이터가 매칭된다.

부차적으로, `_TG_ALARMS`의 namespace가 `AWS/ApplicationELB`로 하드코딩되어 있어 NLB TG의 경우 잘못된 namespace가 사용된다.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type AlarmCreationRequest
    - resource_type: str
    - resource_tags: dict
    - alarm_def: dict (dimension_key, namespace 포함)
  OUTPUT: boolean

  RETURN resource_type == "TG"
         AND alarm_def["dimension_key"] == "TargetGroup"
         AND "LoadBalancer" NOT IN resulting_dimensions
END FUNCTION
```

### Examples

- TG ARN `arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/my-tg/abc123` + ALB 부모 LB
  - 현재: `[{"Name": "TargetGroup", "Value": "my-tg/abc123"}]` → `INSUFFICIENT_DATA`
  - 기대: `[{"Name": "TargetGroup", "Value": "my-tg/abc123"}, {"Name": "LoadBalancer", "Value": "app/my-alb/def456"}]` → 정상 데이터 매칭
- TG ARN + NLB 부모 LB
  - 현재: namespace `AWS/ApplicationELB` + `TargetGroup` 단일 디멘션 → `INSUFFICIENT_DATA`
  - 기대: namespace `AWS/NetworkELB` + `TargetGroup` + `LoadBalancer` 복합 디멘션 → 정상
- ALB 리소스 (비버그 케이스)
  - 현재/기대 동일: `[{"Name": "LoadBalancer", "Value": "app/my-alb/def456"}]`
- EC2 리소스 (비버그 케이스)
  - 현재/기대 동일: `[{"Name": "InstanceId", "Value": "i-0123456789abcdef0"}]`

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- ALB 리소스: `LoadBalancer` 단일 디멘션, namespace `AWS/ApplicationELB` 유지
- NLB 리소스: `LoadBalancer` 단일 디멘션, namespace `AWS/NetworkELB` 유지
- EC2 리소스: `InstanceId` 단일 디멘션 유지
- RDS 리소스: `DBInstanceIdentifier` 단일 디멘션 유지
- `_find_alarms_for_resource()`의 ALB/NLB에 대한 `[ELB]` prefix 검색 로직 유지
- 알람 이름 포맷, AlarmDescription 메타데이터, SNS 액션 등 기존 동작 유지

**Scope:**
`resource_type != "TG"`인 모든 알람 생성/재생성 경로는 이 수정에 의해 영향받지 않아야 한다.

## Hypothesized Root Cause

### 버그 1: TG 복합 디멘션 누락

`_create_standard_alarm()` (및 `_create_single_alarm()`, `_recreate_standard_alarm()`)의 디멘션 구성 로직:

```python
dim_key = alarm_def["dimension_key"]  # "TargetGroup"
if resource_type in ("ALB", "NLB", "TG") and dim_key in ("LoadBalancer", "TargetGroup"):
    dim_value = _extract_elb_dimension(resource_id)
dimensions = [{"Name": dim_key, "Value": dim_value}]
```

이 코드는 `TargetGroup` 디멘션 하나만 생성한다. CloudWatch TG 메트릭은 `TargetGroup` + `LoadBalancer` 두 디멘션이 필수인데, `LoadBalancer` 디멘션을 추가하는 로직이 없다. `resource_tags["_lb_arn"]`에 부모 LB ARN이 있지만 사용되지 않고 있다.

### 버그 1-b: TG namespace 하드코딩

`_TG_ALARMS` 정의에서 namespace가 `AWS/ApplicationELB`로 하드코딩되어 있다. NLB에 연결된 TG의 경우 `AWS/NetworkELB`를 사용해야 하지만, 현재 코드는 이를 구분하지 않는다.

### 버그 2: 레거시 [ELB] 알람 잔존

`_find_alarms_for_resource()`는 ALB/NLB에 대해 `[ELB]` prefix를 이미 검색하고 있다. 따라서 `_delete_all_alarms_for_resource()` → `_find_alarms_for_resource()` 경로에서 레거시 알람이 검색되어 삭제되어야 한다. 그러나 TG 리소스에 대해서는 `[ELB]` prefix 검색이 없다. TG가 이전에 ELB 타입으로 관리되었다면 레거시 알람이 남을 수 있다. `_find_alarms_for_resource()`에서 TG에 대해서도 `[ELB]` prefix 검색을 추가해야 할 수 있다.

## Correctness Properties

Property 1: Bug Condition — TG 복합 디멘션 생성

_For any_ TG 리소스(`resource_type == "TG"`)와 유효한 `_lb_arn` 태그가 있는 `resource_tags`에 대해, `_build_dimensions()` 함수는 SHALL `TargetGroup` 디멘션과 `LoadBalancer` 디멘션을 모두 포함하는 리스트를 반환해야 한다. `TargetGroup` 값은 `_extract_elb_dimension(resource_id)`이고, `LoadBalancer` 값은 `_extract_elb_dimension(resource_tags["_lb_arn"])`이다.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation — 비TG 리소스 디멘션 불변

_For any_ 비TG 리소스(`resource_type in ("ALB", "NLB", "EC2", "RDS")`)에 대해, `_build_dimensions()` 함수는 SHALL 기존 로직과 동일한 디멘션 리스트를 반환해야 한다. 즉, ALB/NLB는 `LoadBalancer` 단일 디멘션, EC2는 `InstanceId`, RDS는 `DBInstanceIdentifier` 단일 디멘션을 유지한다.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

Property 3: Bug Condition — TG namespace 동적 결정

_For any_ TG 리소스에 대해, `_lb_type == "network"`이면 namespace는 `AWS/NetworkELB`를, `_lb_type == "application"`(또는 미지정)이면 `AWS/ApplicationELB`를 사용 SHALL 한다.

**Validates: Requirements 3.6**

Property 4: Preservation — 레거시 [ELB] 알람 정리

_For any_ ALB/NLB 리소스에 대해 `create_alarms_for_resource()` 호출 시, `[ELB]` prefix 레거시 알람이 존재하면 SHALL 삭제되어야 한다.

**Validates: Requirements 2.4, 3.5**

## Fix Implementation

### Changes Required

가정: 위 근본 원인 분석이 정확하다.

**File**: `common/alarm_manager.py`

**1. 신규 헬퍼 `_build_dimensions()` 추가**

```python
def _build_dimensions(
    alarm_def: dict,
    resource_id: str,
    resource_type: str,
    resource_tags: dict,
) -> list[dict]:
```

- `resource_type == "TG"`: `TargetGroup` + `LoadBalancer` 복합 디멘션 반환
  - `TargetGroup` 값: `_extract_elb_dimension(resource_id)`
  - `LoadBalancer` 값: `_extract_elb_dimension(resource_tags["_lb_arn"])`
- `resource_type in ("ALB", "NLB")`: `LoadBalancer` 단일 디멘션 반환
- 그 외 (EC2, RDS): `{dim_key: resource_id}` 단일 디멘션 반환
- `alarm_def.get("extra_dimensions", [])` 추가

**2. 신규 헬퍼 `_resolve_tg_namespace()` 추가**

```python
def _resolve_tg_namespace(alarm_def: dict, resource_tags: dict) -> str:
```

- `resource_tags.get("_lb_type") == "network"`이면 `"AWS/NetworkELB"` 반환
- 그 외: `alarm_def["namespace"]` (기본값 `"AWS/ApplicationELB"`) 반환

**3. `_create_standard_alarm()` 수정**

기존 디멘션 구성 코드를 `_build_dimensions()` 호출로 교체. TG인 경우 namespace를 `_resolve_tg_namespace()`로 결정.

**4. `_create_single_alarm()` 수정**

동일하게 `_build_dimensions()` + `_resolve_tg_namespace()` 적용.

**5. `_recreate_standard_alarm()` 수정**

동일하게 `_build_dimensions()` + `_resolve_tg_namespace()` 적용.

**6. `_find_alarms_for_resource()` 수정 (버그 2)**

TG 리소스에 대해서도 `[ELB]` prefix 검색을 추가하여 레거시 알람을 찾을 수 있게 한다.

## Testing Strategy

### Validation Approach

2단계 접근: (1) 수정 전 코드에서 버그를 재현하는 탐색 테스트, (2) 수정 후 fix checking + preservation checking.

### Exploratory Bug Condition Checking

**Goal**: 수정 전 코드에서 TG 알람의 디멘션 누락을 재현하여 근본 원인을 확인한다.

**Test Plan**: moto로 CloudWatch를 모킹하고, TG 리소스에 대해 `_create_standard_alarm()`을 호출한 뒤 생성된 알람의 Dimensions를 검사한다.

**Test Cases**:
1. **TG 단일 디멘션 확인**: `_create_standard_alarm()`으로 TG 알람 생성 후 `LoadBalancer` 디멘션 누락 확인 (수정 전 코드에서 실패)
2. **TG namespace 확인**: NLB TG에 대해 namespace가 `AWS/ApplicationELB`로 잘못 설정되는지 확인 (수정 전 코드에서 실패)
3. **_create_single_alarm() 동일 버그**: 단일 알람 생성에서도 동일 문제 확인
4. **_recreate_standard_alarm() 동일 버그**: 재생성에서도 동일 문제 확인

**Expected Counterexamples**:
- TG 알람의 Dimensions에 `LoadBalancer`가 없음
- NLB TG 알람의 Namespace가 `AWS/NetworkELB`가 아닌 `AWS/ApplicationELB`

### Fix Checking

**Goal**: 수정 후 TG 알람이 올바른 복합 디멘션과 namespace로 생성되는지 검증.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  dimensions := _build_dimensions(alarm_def, resource_id, "TG", resource_tags)
  ASSERT {"Name": "TargetGroup", ...} IN dimensions
  ASSERT {"Name": "LoadBalancer", ...} IN dimensions
  ASSERT len(dimensions) >= 2
  namespace := _resolve_tg_namespace(alarm_def, resource_tags)
  IF resource_tags["_lb_type"] == "network" THEN
    ASSERT namespace == "AWS/NetworkELB"
  ELSE
    ASSERT namespace == "AWS/ApplicationELB"
END FOR
```

### Preservation Checking

**Goal**: 수정 후 비TG 리소스의 디멘션 로직이 변경되지 않았는지 검증.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  dimensions_new := _build_dimensions(alarm_def, resource_id, resource_type, resource_tags)
  dimensions_old := original_dimension_logic(alarm_def, resource_id, resource_type)
  ASSERT dimensions_new == dimensions_old
END FOR
```

**Testing Approach**: Property-based testing(Hypothesis)으로 다양한 리소스 타입과 ARN 조합에 대해 preservation을 검증한다. 랜덤 생성된 ALB/NLB/EC2/RDS 입력에 대해 `_build_dimensions()`가 기존 로직과 동일한 결과를 반환하는지 확인.

**Test Cases**:
1. **ALB 디멘션 보존**: ALB 리소스에 대해 `LoadBalancer` 단일 디멘션 유지 확인
2. **NLB 디멘션 보존**: NLB 리소스에 대해 `LoadBalancer` 단일 디멘션 유지 확인
3. **EC2 디멘션 보존**: EC2 리소스에 대해 `InstanceId` 단일 디멘션 유지 확인
4. **RDS 디멘션 보존**: RDS 리소스에 대해 `DBInstanceIdentifier` 단일 디멘션 유지 확인

### Unit Tests

- `_build_dimensions()`: TG 복합 디멘션, ALB/NLB/EC2/RDS 단일 디멘션
- `_resolve_tg_namespace()`: application → `AWS/ApplicationELB`, network → `AWS/NetworkELB`
- `_create_standard_alarm()`: TG 알람 생성 시 put_metric_alarm에 전달되는 Dimensions/Namespace 검증
- `_find_alarms_for_resource()`: TG에 대한 `[ELB]` prefix 검색 포함 여부

### Property-Based Tests

- 임의의 TG ARN + LB ARN 조합에 대해 `_build_dimensions()`가 항상 2개 이상 디멘션 반환
- 임의의 비TG 리소스에 대해 `_build_dimensions()`가 기존 로직과 동일한 결과 반환 (preservation)
- 임의의 `_lb_type` 값에 대해 `_resolve_tg_namespace()`가 올바른 namespace 반환

### Integration Tests

- moto 기반 전체 흐름: TG 리소스 `create_alarms_for_resource()` → CloudWatch 알람 Dimensions 검증
- `sync_alarms_for_resource()` 호출 시 TG 알람 재생성 경로에서도 복합 디멘션 적용 확인
- 레거시 `[ELB]` 알람이 있는 상태에서 `create_alarms_for_resource()` 호출 시 정리 확인

## Test Infrastructure Improvements

### EC2 UserData 웹서버 개선

기존 `lb-tg-alarm-lab` 템플릿의 EC2 UserData를 개선하여 안정적인 웹서버를 구성한다.

**현재 문제:**
- `python3 -m http.server 80 &`는 백그라운드 프로세스로 실행되어 불안정
- 프로세스 크래시 시 자동 재시작 없음
- Health Check 응답이 디렉토리 리스팅 HTML (불필요하게 큼)

**개선 방안:**
- `httpd`(Apache) 또는 `nginx`를 systemd 서비스로 설치·실행
- Amazon Linux 2023 기준 `httpd` 패키지 사용 (별도 repo 불필요)
- Health Check용 `/index.html`에 간단한 "OK" 응답 생성
- systemd가 프로세스 관리하므로 크래시 시 자동 재시작

**UserData 예시:**
```bash
#!/bin/bash
yum install -y httpd
echo "OK" > /var/www/html/index.html
systemctl enable httpd
systemctl start httpd
```

**효과:**
1. ALB HTTP Health Check (`/` → 200 OK) 즉시 통과
2. NLB TCP Health Check (port 80 open) 즉시 통과
3. TG `HealthyHostCount` 메트릭이 CloudWatch에 자동 생성 (값: 1)
4. ALB/NLB를 통한 트래픽 발생 시 `RequestCount`, `ProcessedBytes` 등 메트릭 데이터 축적
5. 알람이 `INSUFFICIENT_DATA`가 아닌 실제 `OK`/`ALARM` 상태로 전환 가능

**변경 파일:** `infra-test/lb-tg-alarm-lab/template.yaml` — `TestEc2Instance.Properties.UserData` 섹션
