# 검증 절차서: LB/TG 알람 테스트 인프라

## 개요

이 문서는 `lb-tg-alarm-lab` 스택 배포 후, Daily Monitor Lambda(Alarm Engine)를 수동 실행하여
ALB/NLB/TG 알람 자동 생성 동작을 검증하는 절차를 기술한다.

각 시나리오의 예상 결과는 실제 코드 분석(`common/alarm_manager.py`) 기반이며,
"현재 동작함"과 "미구현(갭)"을 명확히 분리한다.

### 사전 조건

- `lb-tg-alarm-lab` 스택이 정상 배포된 상태
- Daily Monitor Lambda가 최소 1회 실행 완료
- AWS CLI 프로필 `bjs`, 리전 `ap-northeast-2` 설정 완료

---

## 1. 리소스별 태그 설계 테이블

| 리소스 | 태그 키 | 태그 값 | 검증 목적 |
|--------|---------|---------|-----------|
| **모든 리소스** | `Monitoring` | `on` | Alarm Engine 수집 대상 식별 |
| **모든 리소스** | `Project` | `lb-tg-alarm-lab` | 테스트 리소스 식별 |
| **모든 리소스** | `Environment` | `test` | 환경 구분 |
| EC2 | `Name` | `lb-tg-alarm-lab-ec2` | 리소스 식별 |
| EC2 | `Threshold_CPU` | `70` | 기본값(80) 오버라이드 검증 |
| ALB | `Name` | `lb-tg-alarm-lab-alb` | 리소스 식별 |
| ALB | `Threshold_RequestCount` | `5000` | 하드코딩 메트릭 태그 임계치 오버라이드 |
| NLB | `Name` | `lb-tg-alarm-lab-nlb` | 리소스 식별 |
| NLB | `Threshold_ProcessedBytes` | `1000000` | 동적 메트릭 알람 생성 검증 |
| NLB | `Threshold_ActiveFlowCount` | `100` | 복수 동적 메트릭 알람 검증 |
| ALB TG | `Name` | `lb-tg-alarm-lab-alb-tg` | 리소스 식별 |
| ALB TG | `Threshold_RequestCount` | `3000` | TG 알람 미생성 갭 확인 |
| NLB TG | `Name` | `lb-tg-alarm-lab-nlb-tg` | 리소스 식별 |
| NLB TG | `Threshold_HealthyHostCount` | `1` | TG 알람 미생성 갭 확인 |

---

## 2. 예상 알람 결과 테이블

| 리소스 | 리소스 타입 | 메트릭 | 알람 생성 | 알람 유형 | 사유 |
|--------|-----------|--------|:---------:|----------|------|
| EC2 | EC2 | CPUUtilization | ✅ | 하드코딩 | `_EC2_ALARMS`에 정의, `Threshold_CPU=70` 적용 |
| EC2 | EC2 | mem_used_percent | ✅ | 하드코딩 | `_EC2_ALARMS`에 정의 (CWAgent 미설치 시 INSUFFICIENT_DATA) |
| EC2 | EC2 | disk_used_percent | ✅ | 하드코딩 | `_EC2_ALARMS`에 정의 (CWAgent 미설치 시 INSUFFICIENT_DATA) |
| ALB | ELB | RequestCount | ✅ | 하드코딩 | `_ELB_ALARMS`에 `AWS/ApplicationELB` RequestCount 정의 |
| NLB | ELB | RequestCount | ⚠️ | 하드코딩 | `_ELB_ALARMS`가 `AWS/ApplicationELB` namespace만 사용 → NLB에 적용 시 namespace 불일치로 INSUFFICIENT_DATA |
| NLB | ELB | ProcessedBytes | ⭕/❌ | 동적 | `_parse_threshold_tags()` → `_resolve_metric_dimensions()` → CloudWatch에 메트릭 데이터 존재 시 생성, 미존재 시 skip |
| NLB | ELB | ActiveFlowCount | ⭕/❌ | 동적 | 위와 동일. 트래픽 발생 후 약 15분 대기 필요 |
| ALB TG | TG | RequestCount | ❌ | - | `_get_alarm_defs("TG")` → 빈 리스트 반환, TG 알람 정의 없음 |
| ALB TG | TG | HealthyHostCount | ❌ | - | 동일 사유 |
| NLB TG | TG | HealthyHostCount | ❌ | - | 동일 사유 + 복합 디멘션(`TargetGroup` + `LoadBalancer`) 미지원 |

### 범례

- ✅ : 현재 동작함 (알람 정상 생성)
- ⚠️ : 알람은 생성되나 namespace 불일치로 무의미 (INSUFFICIENT_DATA)
- ⭕/❌ : 조건부 (CloudWatch에 메트릭 데이터 존재 여부에 따라 결정)
- ❌ : 미구현(갭) — 알람 생성 안 됨

---

## 3. 검증 시나리오

### 시나리오 (a): EC2 기본 알람 생성 검증

**상태: 현재 동작함 ✅**

EC2 인스턴스에 `Monitoring=on` + `Threshold_CPU=70` 태그가 부착되어 있으므로,
Alarm Engine이 `_EC2_ALARMS` 하드코딩 목록(CPU/Memory/Disk)에 따라 알람을 생성한다.

#### 확인 명령어

```bash
# EC2 알람 조회 (알람 이름 접두사 "[EC2]"로 검색)
aws cloudwatch describe-alarms \
  --profile bjs \
  --region ap-northeast-2 \
  --alarm-name-prefix "[EC2]" \
  --query 'MetricAlarms[?Dimensions[?Value==`<EC2_INSTANCE_ID>`]].[AlarmName,MetricName,Namespace,StateValue]' \
  --output table
```

#### 예상 결과

| 메트릭 | Namespace | 알람 상태 | 비고 |
|--------|-----------|----------|------|
| CPUUtilization | AWS/EC2 | OK 또는 ALARM | 임계치 70 (태그 오버라이드) |
| mem_used_percent | CWAgent | INSUFFICIENT_DATA | CWAgent 미설치 시 |
| disk_used_percent | CWAgent | INSUFFICIENT_DATA | CWAgent 미설치 시 |

---

### 시나리오 (b): ALB LB 레벨 알람 생성 검증

**상태: 현재 동작함 ✅**

ALB에 `Monitoring=on` + `Threshold_RequestCount=5000` 태그가 부착되어 있으므로,
`_ELB_ALARMS`에 정의된 `AWS/ApplicationELB` RequestCount 하드코딩 알람이 생성된다.

#### 확인 명령어

```bash
# ALB 알람 조회
aws cloudwatch describe-alarms \
  --profile bjs \
  --region ap-northeast-2 \
  --alarm-name-prefix "[ELB]" \
  --query 'MetricAlarms[?Namespace==`AWS/ApplicationELB`].[AlarmName,MetricName,Threshold,StateValue]' \
  --output table

# ALB 메트릭 존재 확인
aws cloudwatch list-metrics \
  --profile bjs \
  --region ap-northeast-2 \
  --namespace AWS/ApplicationELB \
  --metric-name RequestCount \
  --output table
```

#### 예상 결과

- `[ELB] lb-tg-alarm-lab-alb RequestCount ...` 형태의 알람 1개 생성
- Namespace: `AWS/ApplicationELB`, Threshold: `5000` (태그 오버라이드)
- Dimension: `LoadBalancer` = ALB ARN suffix

---

### 시나리오 (c): NLB LB 레벨 동적 메트릭 알람 검증

**상태: 조건부 동작 ⭕/❌ (동적 알람) + namespace 불일치 ⚠️ (하드코딩 알람)**

NLB에 `Threshold_ProcessedBytes=1000000`, `Threshold_ActiveFlowCount=100` 태그가 부착되어 있다.

- **하드코딩 알람 (RequestCount)**: `_ELB_ALARMS`에 `AWS/ApplicationELB` namespace만 정의되어 있어 NLB(`AWS/NetworkELB`)에는 무의미한 알람이 생성됨 (INSUFFICIENT_DATA)
- **동적 알람 (ProcessedBytes, ActiveFlowCount)**: `_parse_threshold_tags()`가 태그를 파싱하고, `_resolve_metric_dimensions()`가 `AWS/NetworkELB` namespace에서 메트릭을 검색. CloudWatch에 데이터가 존재하면 알람 생성

#### 확인 명령어

```bash
# NLB 관련 알람 조회
aws cloudwatch describe-alarms \
  --profile bjs \
  --region ap-northeast-2 \
  --alarm-name-prefix "[ELB]" \
  --query 'MetricAlarms[?Namespace==`AWS/NetworkELB` || (Namespace==`AWS/ApplicationELB` && contains(AlarmName, `nlb`))].[AlarmName,MetricName,Namespace,Threshold,StateValue]' \
  --output table

# NLB 메트릭 존재 확인 (동적 알람 생성 가능 여부 판단)
aws cloudwatch list-metrics \
  --profile bjs \
  --region ap-northeast-2 \
  --namespace AWS/NetworkELB \
  --output table

# ProcessedBytes 메트릭 확인
aws cloudwatch list-metrics \
  --profile bjs \
  --region ap-northeast-2 \
  --namespace AWS/NetworkELB \
  --metric-name ProcessedBytes \
  --output table

# ActiveFlowCount 메트릭 확인
aws cloudwatch list-metrics \
  --profile bjs \
  --region ap-northeast-2 \
  --namespace AWS/NetworkELB \
  --metric-name ActiveFlowCount \
  --output table
```

#### 예상 결과

| 메트릭 | 알람 유형 | 생성 여부 | 조건 |
|--------|----------|:---------:|------|
| RequestCount | 하드코딩 | ⚠️ | 생성되나 `AWS/ApplicationELB` namespace → INSUFFICIENT_DATA |
| ProcessedBytes | 동적 | ⭕/❌ | CloudWatch에 메트릭 데이터 존재 시 생성 (트래픽 필요) |
| ActiveFlowCount | 동적 | ⭕/❌ | CloudWatch에 메트릭 데이터 존재 시 생성 (트래픽 필요) |

> **참고**: 동적 알람 생성을 위해서는 NLB에 실제 트래픽이 발생하여 CloudWatch에 메트릭 데이터가 기록되어야 한다. 배포 직후에는 메트릭이 없을 수 있으므로, 트래픽 발생 후 약 15분 대기 후 재확인한다.

---

### 시나리오 (d): TG 메트릭 존재 및 디멘션 확인

**상태: 메트릭은 존재하나 알람 엔진이 활용하지 못함 (미구현 갭)**

ALB TG와 NLB TG에 `Monitoring=on` + `Threshold_*` 태그가 부착되어 있지만,
Alarm Engine은 TG 리소스에 대한 알람 정의가 없어 알람을 생성하지 않는다.
다만 CloudWatch에는 TG 레벨 메트릭이 존재하며, 복합 디멘션 구조를 확인할 수 있다.

#### 확인 명령어

```bash
# Target Group 목록 조회
aws elbv2 describe-target-groups \
  --profile bjs \
  --region ap-northeast-2 \
  --query 'TargetGroups[?contains(TargetGroupName, `lb-tg-alarm-lab`)].[TargetGroupName,TargetGroupArn,LoadBalancerArns]' \
  --output table

# TG 태그 확인 (Monitoring, Threshold_* 태그 부착 여부)
aws elbv2 describe-tags \
  --profile bjs \
  --region ap-northeast-2 \
  --resource-arns <ALB_TG_ARN> <NLB_TG_ARN> \
  --output table

# ALB TG 메트릭 확인 (복합 디멘션: TargetGroup + LoadBalancer)
aws cloudwatch list-metrics \
  --profile bjs \
  --region ap-northeast-2 \
  --namespace AWS/ApplicationELB \
  --dimensions Name=TargetGroup,Value=<ALB_TG_ARN_SUFFIX> \
  --output table

# NLB TG 메트릭 확인 (복합 디멘션: TargetGroup + LoadBalancer)
aws cloudwatch list-metrics \
  --profile bjs \
  --region ap-northeast-2 \
  --namespace AWS/NetworkELB \
  --dimensions Name=TargetGroup,Value=<NLB_TG_ARN_SUFFIX> \
  --output table
```

#### 예상 결과

- TG 리소스에 `Monitoring=on`, `Threshold_*` 태그가 정상 부착됨
- CloudWatch에 TG 레벨 메트릭(RequestCount, HealthyHostCount 등)이 존재함
- 메트릭 디멘션이 **복합 구조**임을 확인:
  - ALB TG: `TargetGroup=targetgroup/xxx` + `LoadBalancer=app/xxx`
  - NLB TG: `TargetGroup=targetgroup/xxx` + `LoadBalancer=net/xxx`
- 이 복합 디멘션은 현재 Alarm Engine의 `_resolve_metric_dimensions()`가 처리하지 못함

---

### 시나리오 (e): TG 알람 자동 생성 미지원 확인

**상태: 미구현(갭) ❌**

TG 리소스에 대해 Alarm Engine이 알람을 생성하지 않음을 확인한다.

#### 확인 명령어

```bash
# TG 관련 알람이 존재하지 않음을 확인
# (TG 전용 알람 접두사가 없으므로, 알람 전체에서 TG ARN suffix 검색)
aws cloudwatch describe-alarms \
  --profile bjs \
  --region ap-northeast-2 \
  --query 'MetricAlarms[?Dimensions[?Name==`TargetGroup`]].[AlarmName,MetricName,Namespace]' \
  --output table
```

#### 예상 결과

- **결과 없음** (빈 테이블) — TG 디멘션을 사용하는 알람이 존재하지 않음
- 이는 Alarm Engine이 TG 알람을 생성하지 않기 때문 (아래 코드 레벨 분석 참조)

---

## 4. TG 알람 미지원 사유 — 코드 레벨 분석

TG 알람이 생성되지 않는 3가지 코드 레벨 원인:

### 원인 1: `_get_alarm_defs("TG")` → 빈 리스트

`common/alarm_manager.py`의 `_get_alarm_defs()` 함수는 EC2/RDS/ELB만 분기 처리한다:

```python
def _get_alarm_defs(resource_type: str) -> list[dict]:
    if resource_type == "EC2":
        return _EC2_ALARMS
    elif resource_type == "RDS":
        return _RDS_ALARMS
    elif resource_type == "ELB":
        return _ELB_ALARMS
    return []          # ← TG는 여기에 해당 → 빈 리스트 반환
```

TG용 `_TG_ALARMS` 정의가 존재하지 않으므로, 하드코딩 알람이 생성되지 않는다.

### 원인 2: `_DIMENSION_KEY_MAP`에 TG 매핑 없음

```python
_DIMENSION_KEY_MAP: dict[str, str] = {
    "EC2": "InstanceId",
    "RDS": "DBInstanceIdentifier",
    "ELB": "LoadBalancer",
    # TG 매핑 없음 → dim_key = "" (빈 문자열)
}
```

TG 메트릭은 `TargetGroup` 디멘션 키가 필요하지만, 매핑이 없어 `_resolve_metric_dimensions()`에서
빈 문자열로 `list_metrics`를 호출하게 되어 메트릭을 찾지 못한다.

### 원인 3: `_resolve_metric_dimensions()` 단일 디멘션 검색

```python
def _resolve_metric_dimensions(resource_id, metric_name, resource_type):
    ...
    for namespace in namespaces:
        resp = cw.list_metrics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=[
                {"Name": dim_key, "Value": dim_value},  # ← 단일 디멘션만 전달
            ],
        )
```

TG 메트릭은 **복합 디멘션**이 필요하다:
- `TargetGroup=targetgroup/my-tg/abc123`
- `LoadBalancer=app/my-alb/def456` (또는 `net/my-nlb/...`)

현재 코드는 단일 디멘션(`LoadBalancer`)으로만 검색하므로, TG의 복합 디멘션 메트릭을 해석할 수 없다.

---

## 5. NLB 하드코딩 알람 부재 사유

### 원인: `_ELB_ALARMS`에 `AWS/ApplicationELB` namespace만 정의

```python
_ELB_ALARMS = [
    {
        "metric": "RequestCount",
        "namespace": "AWS/ApplicationELB",   # ← ALB 전용 namespace
        "metric_name": "RequestCount",
        "dimension_key": "LoadBalancer",
        "stat": "Sum",
        "comparison": "GreaterThanThreshold",
        "period": 60,
        "evaluation_periods": 1,
    },
]
```

NLB(type=`network`)도 `resource_type="ELB"`로 분류되므로 동일한 `_ELB_ALARMS`가 적용된다.
그러나 NLB의 CloudWatch namespace는 `AWS/NetworkELB`이므로:

- `AWS/ApplicationELB` namespace로 생성된 RequestCount 알람은 NLB 메트릭과 매칭되지 않음
- 결과적으로 해당 알람은 **INSUFFICIENT_DATA** 상태가 됨
- NLB 전용 하드코딩 알람(`AWS/NetworkELB` namespace)은 `_ELB_ALARMS`에 정의되어 있지 않음

> **동적 알람은 가능**: `_parse_threshold_tags()`가 `Threshold_ProcessedBytes` 등 태그를 파싱하고,
> `_resolve_metric_dimensions()`가 `_NAMESPACE_MAP["ELB"]`에 포함된 `AWS/NetworkELB`에서
> 메트릭을 검색하므로, CloudWatch에 데이터가 존재하면 동적 알람은 정상 생성된다.

---

## 6. AWS CLI 명령어 요약

모든 명령어는 `--profile bjs --region ap-northeast-2`를 사용한다.

### 알람 조회

```bash
# EC2 알람
aws cloudwatch describe-alarms \
  --profile bjs \
  --region ap-northeast-2 \
  --alarm-name-prefix "[EC2]"

# ELB 알람 (ALB + NLB)
aws cloudwatch describe-alarms \
  --profile bjs \
  --region ap-northeast-2 \
  --alarm-name-prefix "[ELB]"
```

### 메트릭 조회

```bash
# ALB 메트릭
aws cloudwatch list-metrics \
  --profile bjs \
  --region ap-northeast-2 \
  --namespace AWS/ApplicationELB

# NLB 메트릭
aws cloudwatch list-metrics \
  --profile bjs \
  --region ap-northeast-2 \
  --namespace AWS/NetworkELB
```

### TG 리소스 조회

```bash
# Target Group 목록
aws elbv2 describe-target-groups \
  --profile bjs \
  --region ap-northeast-2

# TG 태그 확인
aws elbv2 describe-tags \
  --profile bjs \
  --region ap-northeast-2 \
  --resource-arns <TG_ARN>
```

---

## 7. 검증 결과 요약

| 범위 | 상태 | 비고 |
|------|:----:|------|
| EC2 하드코딩 알람 (CPU/Memory/Disk) | ✅ 동작함 | Memory/Disk는 CWAgent 필요 |
| ALB 하드코딩 알람 (RequestCount) | ✅ 동작함 | `AWS/ApplicationELB` namespace |
| NLB 하드코딩 알람 (RequestCount) | ⚠️ 부분 | namespace 불일치 → INSUFFICIENT_DATA |
| NLB 동적 알람 (ProcessedBytes, ActiveFlowCount) | ⭕/❌ 조건부 | 트래픽 발생 시 동작 |
| ALB TG 알람 | ❌ 미구현 | `_get_alarm_defs("TG")` → 빈 리스트 |
| NLB TG 알람 | ❌ 미구현 | 동일 + 복합 디멘션 미지원 |
