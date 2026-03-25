---
inclusion: fileMatch
fileMatchPattern: '**/*.py'
---

# 알람 관련 규칙

## §6. 알람 관련 규칙

- 알람 이름 포맷: `[{resource_type}] {label} {display_metric} {direction}{threshold}{unit} ({resource_id})`
  - EC2/RDS: `resource_id`는 인스턴스 ID / DB 식별자를 그대로 사용
  - ALB/NLB/TG: `resource_id` 부분에 전체 ARN 대신 Short_ID(`{name}/{hash}`)를 사용한다
    - Short_ID 추출: `_shorten_elb_resource_id(resource_id, resource_type)` 함수 사용
    - ALB ARN `...loadbalancer/app/{name}/{hash}` → `{name}/{hash}`
    - NLB ARN `...loadbalancer/net/{name}/{hash}` → `{name}/{hash}`
    - TG ARN `...targetgroup/{name}/{hash}` → `{name}/{hash}`
  - `AlarmDescription`의 `resource_id` 필드에는 항상 전체 ARN(Full_ARN)을 저장한다 (매칭/역추적용)
- 알람 이름 최대 255자 (CloudWatch API 제한). 초과 시 label → display_metric 순으로 truncate (`...` 접미사)
- 알람 매칭: 알람 메타데이터(Namespace, MetricName, Dimensions) 기반. 이름 문자열 매칭 금지
- 알람 생성 시 `AlarmDescription`에 메트릭 키를 포함하여 역추적 가능하게 한다 (최대 1024자)
- 새 포맷 알람 검색: resource_id prefix 기반 검색. 전체 알람 풀스캔 금지
- 알람 검색 시 ALB/NLB/TG는 Short_ID suffix와 레거시 Full_ARN suffix 모두 검색하여 호환성 유지

## §6-1. 메트릭별 CloudWatch 디멘션 규칙

새 메트릭을 하드코딩 알람 정의(`_*_ALARMS`)에 추가할 때, 반드시 AWS 공식 문서에서 해당 메트릭의 디멘션 구성을 확인하고 정확히 반영해야 한다.

### 리소스 유형별 디멘션 매핑 (AWS 공식 문서 기준)

| 리소스 유형 | 네임스페이스 | 기본 디멘션 | 비고 |
|------------|------------|-----------|------|
| EC2 | AWS/EC2 | `InstanceId` | 모든 EC2 메트릭 공통 |
| EC2 (CWAgent) | CWAgent | `InstanceId` + 메트릭별 추가 | Disk: `device`, `fstype`, `path` 추가 |
| RDS | AWS/RDS | `DBInstanceIdentifier` | 모든 RDS 메트릭 공통 |
| ALB | AWS/ApplicationELB | `LoadBalancer` | LB 레벨 메트릭 (5XX, RequestCount 등) |
| ALB (TG 메트릭) | AWS/ApplicationELB | `TargetGroup, LoadBalancer` | TG 레벨 메트릭 (HealthyHostCount, TargetResponseTime 등) |
| NLB | AWS/NetworkELB | `LoadBalancer` | 모든 NLB LB 레벨 메트릭 공통 |
| TG (ALB) | AWS/ApplicationELB | `TargetGroup, LoadBalancer` | 복합 디멘션 필수 |
| TG (NLB) | AWS/NetworkELB | `TargetGroup, LoadBalancer` | 복합 디멘션 필수 |

### 주요 메트릭별 디멘션 상세

| 메트릭 | 네임스페이스 | 디멘션 | 레벨 |
|--------|------------|--------|------|
| `HTTPCode_ELB_5XX_Count` | AWS/ApplicationELB | `LoadBalancer` | LB 전용 (TG 디멘션 불가) |
| `TargetResponseTime` | AWS/ApplicationELB | `TargetGroup, LoadBalancer` 또는 `LoadBalancer` | TG/LB 양쪽 가능 |
| `RequestCountPerTarget` | AWS/ApplicationELB | `TargetGroup` (필수) 또는 `LoadBalancer, TargetGroup` | TG 전용 |
| `TCP_Client_Reset_Count` | AWS/NetworkELB | `LoadBalancer` | LB 전용 |
| `TCP_Target_Reset_Count` | AWS/NetworkELB | `LoadBalancer` | LB 전용 |
| `StatusCheckFailed` | AWS/EC2 | `InstanceId` | 인스턴스 레벨 |
| `ReadLatency` | AWS/RDS | `DBInstanceIdentifier` | 인스턴스 레벨 |
| `WriteLatency` | AWS/RDS | `DBInstanceIdentifier` | 인스턴스 레벨 |

### 새 메트릭 추가 시 디멘션 확인 절차 (필수)

새 메트릭을 하드코딩 알람 정의에 추가할 때 반드시 아래 절차를 따른다:

1. **AWS 공식 문서에서 디멘션 확인**: 해당 메트릭의 CloudWatch 문서 페이지에서 "Dimensions" 열을 확인한다
   - EC2: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/viewing_metrics_with_cloudwatch.html
   - RDS: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/dimensions.html
   - ALB: https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-cloudwatch-metrics.html
   - NLB: https://docs.aws.amazon.com/elasticloadbalancing/latest/network/load-balancer-cloudwatch-metrics.html
2. **LB 레벨 vs TG 레벨 구분**: 메트릭이 LB 레벨인지 TG 레벨인지 확인한다. LB 레벨 메트릭에 TG 디멘션을 넣으면 데이터가 안 나온다 (`INSUFFICIENT_DATA`)
3. **알람 정의에 반영**: `dimension_key`를 정확히 명시하고, `_build_dimensions()` 헬퍼가 리소스 유형에 따라 올바른 디멘션을 생성하는지 확인한다
4. **테스트에서 검증**: 디멘션 조합이 올바른지 단위 테스트로 검증한다

### 디멘션 규칙
- ALB LB 레벨 메트릭(`HTTPCode_ELB_5XX_Count` 등)은 `LoadBalancer` 단일 디멘션만 사용
- TG 레벨 메트릭은 반드시 `TargetGroup` + `LoadBalancer` 복합 디멘션을 사용 (거버넌스 §6 알람 매칭 규칙)
- `RequestCountPerTarget`은 `TargetGroup` 디멘션이 필수이며, `LoadBalancer`는 선택적
- 디멘션 값 포맷: ALB/NLB는 `app/...` 또는 `net/...`, TG는 `targetgroup/...` (ARN suffix)
- 잘못된 디멘션 조합은 `INSUFFICIENT_DATA` 상태를 유발하므로 반드시 공식 문서 기준으로 확인

## §7. 태그 기반 동적 알람

- `Threshold_{MetricName}={Value}` 태그는 동적으로 파싱하여 알람을 생성한다
- 하드코딩 메트릭 목록(`_EC2_ALARMS` 등)은 기본 알람 정의로만 사용하고, 태그에서 발견된 추가 메트릭도 처리한다
- 디멘션 자동 해석: CloudWatch `list_metrics` API로 네임스페이스/디멘션을 조회한다
- AWS 태그 제약 준수:
  - 태그 키 최대 128자 → `Threshold_` 접두사(10자) 제외 시 메트릭 이름 최대 118자
  - 태그 값 최대 256자, 양의 숫자로 파싱 가능해야 함
  - 리소스당 태그 최대 50개 (Monitoring, Name 등 시스템 태그 포함)
  - 태그 허용 문자: 문자, 숫자, 공백, `_ . : / = + - @`
  - `aws:` 접두사 태그는 무시

## §12. 리소스별 태그-메트릭 매핑 테이블 유지 규칙

새 리소스 타입 또는 메트릭을 추가할 때, 아래 매핑 테이블을 반드시 업데이트한다.
이 테이블은 태그 키(Threshold_*)와 내부 metric key, CloudWatch metric_name 간의 관계를 정의한다.

### 규칙
- 새 하드코딩 알람 정의(`_*_ALARMS`)를 추가하면 이 테이블에 해당 행을 추가한다
- `_metric_name_to_key()` 매핑에도 동일하게 추가한다 (CW metric_name → 내부 키)
- `HARDCODED_DEFAULTS`에 기본 임계치를 추가한다
- `_METRIC_DISPLAY`에 표시 정보를 추가한다

### EC2

| 태그 키 | 내부 metric key | CW metric_name | Namespace | 기본 임계치 | 단위 |
|---------|----------------|----------------|-----------|-----------|------|
| Threshold_CPU | CPU | CPUUtilization | AWS/EC2 | 80 | % |
| Threshold_Memory | Memory | mem_used_percent | CWAgent | 80 | % |
| Threshold_Disk_{path} | Disk_{path} | disk_used_percent | CWAgent | 80 | % |
| Threshold_StatusCheckFailed | StatusCheckFailed | StatusCheckFailed | AWS/EC2 | 0 | Count |

### RDS

| 태그 키 | 내부 metric key | CW metric_name | Namespace | 기본 임계치 | 단위 | 변환 |
|---------|----------------|----------------|-----------|-----------|------|------|
| Threshold_CPU | CPU | CPUUtilization | AWS/RDS | 80 | % | - |
| Threshold_FreeMemoryGB | FreeMemoryGB | FreeableMemory | AWS/RDS | 2 | GB | GB→bytes |
| Threshold_FreeStorageGB | FreeStorageGB | FreeStorageSpace | AWS/RDS | 10 | GB | GB→bytes |
| Threshold_Connections | Connections | DatabaseConnections | AWS/RDS | 100 | Count | - |
| Threshold_ReadLatency | ReadLatency | ReadLatency | AWS/RDS | 0.02 | Seconds | - |
| Threshold_WriteLatency | WriteLatency | WriteLatency | AWS/RDS | 0.02 | Seconds | - |

### ALB

| 태그 키 | 내부 metric key | CW metric_name | Namespace | 기본 임계치 | 단위 |
|---------|----------------|----------------|-----------|-----------|------|
| Threshold_RequestCount | RequestCount | RequestCount | AWS/ApplicationELB | 10000 | Count |
| Threshold_ELB5XX | ELB5XX | HTTPCode_ELB_5XX_Count | AWS/ApplicationELB | 50 | Count |
| Threshold_TargetResponseTime | TargetResponseTime | TargetResponseTime | AWS/ApplicationELB | 5 | Seconds |

### NLB

| 태그 키 | 내부 metric key | CW metric_name | Namespace | 기본 임계치 | 단위 |
|---------|----------------|----------------|-----------|-----------|------|
| Threshold_ProcessedBytes | ProcessedBytes | ProcessedBytes | AWS/NetworkELB | 100000000 | Bytes |
| Threshold_ActiveFlowCount | ActiveFlowCount | ActiveFlowCount | AWS/NetworkELB | 10000 | Count |
| Threshold_NewFlowCount | NewFlowCount | NewFlowCount | AWS/NetworkELB | 5000 | Count |
| Threshold_TCPClientReset | TCPClientReset | TCP_Client_Reset_Count | AWS/NetworkELB | 100 | Count |
| Threshold_TCPTargetReset | TCPTargetReset | TCP_Target_Reset_Count | AWS/NetworkELB | 100 | Count |

### TG (Target Group)

| 태그 키 | 내부 metric key | CW metric_name | Namespace | 기본 임계치 | 단위 | 비고 |
|---------|----------------|----------------|-----------|-----------|------|------|
| Threshold_HealthyHostCount | HealthyHostCount | HealthyHostCount | ALB/NLB 분기 | 1 | Count | LessThan |
| Threshold_UnHealthyHostCount | UnHealthyHostCount | UnHealthyHostCount | ALB/NLB 분기 | 80 | Count | - |
| Threshold_RequestCountPerTarget | RequestCountPerTarget | RequestCountPerTarget | AWS/ApplicationELB | 1000 | Count | ALB TG only |
| Threshold_TGResponseTime | TGResponseTime | TargetResponseTime | AWS/ApplicationELB | 5 | Seconds | ALB TG only |

### 동적 알람 (Threshold_* 태그)

하드코딩 목록에 없는 `Threshold_{MetricName}={Value}` 태그는 동적 알람으로 처리된다.
단, CW metric_name이 하드코딩 내부 키의 별칭인 경우 동적 알람 생성을 방지한다 (KI-005 참조).
