# 알람 규칙 (Alarm Rules)

> 알람 네이밍/디멘전/임계치/Severity 계약의 단일 원본(SSOT).
> (구 `.kiro/steering/alarm-rules.md` + `phase2-severity-rules.md` + `resource-naming.md` 통합본)
> Python 알람 코드(`backend/common/alarm_*`, `collectors/`)를 수정할 때 반드시 이 문서를 기준으로 한다.

## §6. 알람 관련 규칙

- 알람 이름 포맷: `[{resource_type}] {label} {display_metric} {direction} {threshold}{unit} (TagName: {resource_id})`
  - EC2/RDS: `resource_id`는 인스턴스 ID / DB 식별자를 그대로 사용
  - **식별은 이름이 아니라 메타데이터로**: 알람→리소스 역해석은 `common/alarm_identity.py`
    `identify_alarm()`이 AlarmDescription JSON(`resource_id` Full ID) → 이름 `(TagName: …)` 순으로
    듀얼 리드한다. 이름의 short ID(ALB/NLB/TG/ACM/APIGW-HTTP)는 인벤토리 `resource_id`와 다르므로
    이름 정규식으로 리소스를 식별하는 코드를 새로 만들지 말 것 (AP-23).
  - ALB/NLB/TG: `resource_id` 부분에 전체 ARN 대신 Short_ID(`{name}/{hash}`)를 사용한다
    - Short_ID 추출: `_shorten_elb_resource_id(resource_id, resource_type)` 함수 사용
    - ALB ARN `...loadbalancer/app/{name}/{hash}` → `{name}/{hash}`
    - NLB ARN `...loadbalancer/net/{name}/{hash}` → `{name}/{hash}`
    - TG ARN `...targetgroup/{name}/{hash}` → `{name}/{hash}`
  - `AlarmDescription`의 `resource_id` 필드에는 항상 전체 ARN(Full_ARN)을 저장한다 (매칭/역추적용)
- 알람 이름 최대 255자 (CloudWatch API 제한). 초과 시 label → display_metric 순으로 truncate (`...` 접미사)
- 알람 매칭: 알람 메타데이터(Namespace, MetricName, Dimensions) 기반. 이름 문자열 매칭 금지 (AP-3)
- 알람 생성 시 `AlarmDescription`에 메트릭 키를 포함하여 역추적 가능하게 한다 (최대 1024자)
- 새 포맷 알람 검색: resource_id prefix 기반 검색. 전체 알람 풀스캔 금지 (AP-4)
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
- TG 레벨 메트릭은 반드시 `TargetGroup` + `LoadBalancer` 복합 디멘션을 사용 (§6 알람 매칭 규칙)
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

### AuroraRDS

| 태그 키 | 내부 metric key | CW metric_name | Namespace | 기본 임계치 | 단위 | 변환 |
|---------|----------------|----------------|-----------|-----------|------|------|
| Threshold_CPU | CPU | CPUUtilization | AWS/RDS | 80 | % | - |
| Threshold_FreeMemoryGB | FreeMemoryGB | FreeableMemory | AWS/RDS | 2 | GB | GB→bytes |
| Threshold_Connections | Connections | DatabaseConnections | AWS/RDS | 100 | Count | - |
| Threshold_FreeLocalStorageGB | FreeLocalStorageGB | FreeLocalStorage | AWS/RDS | 10 | GB | GB→bytes |
| Threshold_ReplicaLag | ReplicaLag | AuroraReplicaLagMaximum | AWS/RDS | 2000000 | μs | - |
| Threshold_ReaderReplicaLag | ReaderReplicaLag | AuroraReplicaLag | AWS/RDS | 2000000 | μs | - |
| Threshold_ACUUtilization | ACUUtilization | ACUUtilization | AWS/RDS | 80 | % | - |
| Threshold_ServerlessDatabaseCapacity | ServerlessDatabaseCapacity | ServerlessDatabaseCapacity | AWS/RDS | 128 | ACU | - |
| Threshold_FreeMemoryPct | FreeMemoryPct | (FreeableMemory 퍼센트 변환) | AWS/RDS | 20 | % | pct→bytes |

### 동적 알람 (Threshold_* 태그)

하드코딩 목록에 없는 `Threshold_{MetricName}={Value}` 태그는 동적 알람으로 처리된다.
단, CW metric_name이 하드코딩 내부 키의 별칭인 경우 동적 알람 생성을 방지한다 (KI-005 참조).

## §8. 글로벌 서비스 알람 규칙

CloudFront, Route53 등 글로벌 서비스의 메트릭은 us-east-1에서만 발행된다.
이 서비스들의 알람 생성/검색/삭제는 us-east-1 CloudWatch 클라이언트를 사용해야 한다.

### 8-1. 글로벌 서비스 리전 매핑

| 리소스 타입 | 메트릭 리전 | 알람 생성 리전 | 비고 |
|------------|-----------|-------------|------|
| CloudFront | us-east-1 | us-east-1 | `_GLOBAL_SERVICE_REGION` 매핑 |
| Route53 | us-east-1 | us-east-1 | `_GLOBAL_SERVICE_REGION` 매핑 |

- `alarm_registry.py`의 `_GLOBAL_SERVICE_REGION` dict에 글로벌 서비스 리전을 정의한다
- `alarm_manager.py`의 `sync_alarms_for_resource`/`create_alarms_for_resource`에서 글로벌 서비스면 `_get_cw_client_for_region(region)` 사용
- `alarm_builder.py`의 `_create_standard_alarm`/`_create_single_alarm`/`_recreate_standard_alarm`에서 `alarm_def.get("region")` 확인

### 8-2. 크로스 리전 SNS 제약

- CloudWatch 알람의 AlarmActions에는 **같은 리전의 SNS 토픽**만 사용 가능
- us-east-1 알람에 ap-northeast-2 SNS ARN을 넣으면 `Invalid region` 에러 발생
- 현재 글로벌 서비스 알람은 AlarmActions를 비워두는 임시 처리 적용
- 향후 us-east-1 SNS 토픽 + AWS Chatbot Slack 연동으로 개선 예정 (`docs/specs/global-service-alarm-notification/`)

### 8-3. 글로벌 서비스 디멘션 규칙

| 리소스 타입 | 필수 디멘션 | 비고 |
|------------|-----------|------|
| CloudFront | `DistributionId` + `Region: Global` | Region 디멘션 누락 시 메트릭 매칭 안 됨 |
| Route53 | `HealthCheckId` | Region 디멘션 불필요 |
| WAF | `WebACL` + `Rule` + `Region: {region}` | Region 디멘션 누락 시 메트릭 매칭 안 됨 |
| S3 (Request Metrics) | `BucketName` + `FilterId: EntireBucket` | FilterId 누락 시 4xx/5xx 메트릭 매칭 안 됨 |

## §9. TagResource/UntagResource ARN 변환 규칙

CloudTrail `TagResource`/`UntagResource` 이벤트는 `resourceArn`을 반환한다.
remediation handler에서 이 ARN을 실제 리소스 식별자로 변환해야 한다.

### 9-1. ARN → 리소스 ID 변환 매핑

| 리소스 타입 | ARN 패턴 | 추출 방법 | 예시 |
|------------|---------|----------|------|
| DynamoDB | `arn:aws:dynamodb:...:table/{name}` | 마지막 `/` 이후 | `table/my-table` → `my-table` |
| ECS | `arn:aws:ecs:...:service/{cluster}/{name}` | 마지막 `/` 이후 | `service/cluster/svc` → `svc` |
| EFS | `arn:aws:elasticfilesystem:...:file-system/{id}` | 마지막 `/` 이후 | `file-system/fs-xxx` → `fs-xxx` |
| SNS | `arn:aws:sns:{region}:{account}:{name}` | 마지막 `:` 이후 | `...:my-topic` → `my-topic` |
| MSK | `arn:aws:kafka:...:cluster/{name}/{uuid}` | 두 번째 `/` 부분 | `cluster/name/uuid` → `name` |
| Lambda, ACM, S3, SageMaker 등 | ARN 그대로 | 변환 불필요 | ARN이 resource_id |

- `_extract_id_from_arn(arn, resource_type)` 함수에서 변환 처리
- 새 리소스 타입 추가 시 ARN 패턴 확인 후 변환 로직 추가 필수
- `remediation_handler/lambda_handler.py` 수정 시 이 매핑과 코드가 일치하는지 확인한다

## §10. TreatMissingData 결정 규칙

새 알람 정의(`_*_ALARMS`)에 메트릭을 추가할 때 반드시 아래 표를 참고하여 `treat_missing_data` 값을 명시한다.
`alarm_builder.py`의 기본값은 `"notBreaching"`이며, 명시하지 않으면 이 값이 사용된다.

### 10-1. 선택 기준

| 메트릭 특성 | 적용 값 | 근거 |
|------------|---------|------|
| **연결/상태 메트릭** — `LessThan` + binary(0=down/1=up) | `"breaching"` | 데이터 없음 = 리소스 자체가 응답 안 함 = 이상 상태 |
| **클러스터 가용성 메트릭** — 클러스터 다운 시 메트릭도 미발행 | `"breaching"` | 데이터 없음 = 클러스터 이상으로 간주 |
| **이벤트/트래픽 기반** — 트래픽·요청 없으면 데이터 없음 | `"notBreaching"` | 데이터 없음 = 트래픽 없음 = 정상 |
| **항상 발행 메트릭** — 리소스 실행 중이면 항상 발행 (CPU, Memory 등) | `"notBreaching"` | 데이터 없음 = 리소스 중지됨 → 중지 상태에 알람 불필요 |
| **용량/잔량 메트릭** (`LessThan`, FreeMemory/FreeStorage 등) | `"notBreaching"` | 리소스 중지 시 데이터 없음 → 중지된 리소스에 알람 불필요 |
| **의도적 미발행 가능** — 분리·전환·재구성 시 정상적으로 데이터 없을 수 있음 | `"missing"` | 상태 유지가 false alarm 방지에 유리 |

### 10-2. 현재 `"breaching"` 적용 알람 (10개)

| 리소스 | 메트릭 | 이유 |
|--------|--------|------|
| VPN | TunnelState | 데이터 없음 = 터널 다운 |
| MSK | ActiveControllerCount | 데이터 없음 = 컨트롤러 없음 = 클러스터 이상 |
| MSK | UnderReplicatedPartitions | 브로커 다운 시 복제 상태 확인 불가 |
| Route53 | HealthCheckStatus | 데이터 없음 = 헬스체크 중단 |
| DX | ConnectionState | 데이터 없음 = Direct Connect 회선 단절 |
| TG | HealthyHostCount | 데이터 없음 = 타겟 0개 = 서비스 불가 |
| OpenSearch | ClusterStatusRed | 클러스터 완전 다운 시 메트릭 미발행 |
| OpenSearch | ClusterStatusYellow | 동일 |
| OpenSearch | OSFreeStorageSpace | 클러스터 다운 = 스토리지 확인 불가 |
| OpenSearch | ClusterIndexWritesBlocked | 클러스터 다운 = 쓰기 차단 확정 |

### 10-3. `"missing"` 예외 케이스 (4개 — 명시 필수)

| 리소스 | 메트릭 | 이유 |
|--------|--------|------|
| ACM | DaysToExpiry | 인증서를 리소스에서 의도적으로 분리했을 때 데이터 없음 |
| EFS | BurstCreditBalance | Provisioned Throughput 모드 전환 시 메트릭 미발행 가능 |
| AuroraRDS | ReplicaLag | Writer-only 구성 시 메트릭 없음 (의도적 구성) |
| AuroraRDS | ReaderReplicaLag | Reader 없는 구성 시 메트릭 없음 (의도적 구성) |

### 10-4. 동적 알람 (`Threshold_*` 태그) 기본값

`_create_dynamic_alarm()`의 기본값도 `"notBreaching"`. 사용자 정의 메트릭은 대부분 이벤트/트래픽 기반이므로 데이터 없음 = 정상으로 처리한다.

### 10-5. M-of-N 평가 정책 (Severity 기반 오탐 감소)

데이터포인트 1개 초과로 즉시 울리는 오탐(순간 스파이크)을 줄이기 위해,
`_get_alarm_defs()`가 Severity에 따라 M-of-N 평가를 자동 적용한다
(`alarm_registry._apply_eval_policy`). 개별 정의(`_*_ALARMS`)의
`evaluation_periods: 1`은 원본 기본값일 뿐, 실제 적용 값은 아래 표를 따른다.

| Severity | 평가 정책 (evaluation_periods / datapoints_to_alarm) | 근거 |
|----------|------------------------------------------------------|------|
| SEV-1 | **1 / 즉시 (정책 미적용)** | 가용성 직결 — 감지 지연 불가 |
| SEV-2 | 3 중 2 | 에러 급증: 15분 창에서 10분 이상 지속 시 |
| SEV-3 | 3 중 2 | 포화도: CPU/메모리는 지속성이 판단 기준 |
| SEV-4 | 5 중 3 | 성능 저하: 추세로 판단 |
| SEV-5 | 5 중 3 | 참고 지표 |

**정책 적용 제외 (즉시 평가 1/1 유지):**
- Severity가 SEV-1인 메트릭
- `treat_missing_data: "breaching"` — 데이터 없음=장애로 보는 메트릭.
  M-of-N을 얹으면 다운 감지 자체가 M배 늦어진다 (예: Aurora CPU/FreeableMemory).
- `period ≥ 3600` — 저빈도 메트릭(DaysToExpiry 등)은 알림만 일 단위로 늦어진다.
- 정의가 `datapoints_to_alarm`을 직접 명시한 경우 (개별 오버라이드).

**동적 알람**(`Threshold_*` 태그)도 동일 정책을 따른다
(`get_dynamic_eval_policy` — 미매핑 메트릭은 SEV-5 폴백 → 5 중 3).

정의(레지스트리)와 실물 알람의 평가 설정이 어긋나면 daily sync의
설정 드리프트 감지(`alarm_sync._config_drift`)가 재생성으로 교정한다.
정책 변경 시 별도 마이그레이션 없이 다음 sync에서 전체 알람에 전파된다.

### 10-6. 새 메트릭 추가 체크리스트

```
□ 메트릭이 항상 발행되는가? (리소스 실행 중)
  → YES: notBreaching (기본값, 명시 불필요)
  → NO: 아래로 진행

□ 데이터 없음이 곧 이상 상태를 의미하는가?
  (연결 끊김, 클러스터 다운, 타겟 없음 등)
  → YES: breaching (명시 필요)
  → NO: 아래로 진행

□ 의도적으로 데이터가 없을 수 있는가?
  (인증서 분리, 모드 전환, 구성 변경 등)
  → YES: missing (명시 필요)
  → NO: notBreaching (기본값, 명시 불필요)
```

### 10-7. 임계치 재보정 — Shadow 모드 (2026-08-31~)

`common/threshold_recalibration.py`가 주 1회(스냅샷 1시간 뒤) 리소스×메트릭별 제안을 계산해
ThresholdOverridesTable에 `status=shadow` 행으로만 남긴다. **알람은 바뀌지 않는다.**

| 단계 | 규칙 |
|------|------|
| 대상 | `GreaterThanThreshold` + 정책 표 메트릭(RequestCount·RequestCountPerTarget·ProcessedBytes·NewFlowCount / TargetResponseTime·ApiLatency / CPUUtilization) + SEV-3 이하 |
| 데이터 | 최근 28일 중 일 p99 21일 이상 (`insufficient_data`는 행 미기록) |
| 기준값 | 창 안 일 p99 최댓값 × 1.2 |
| 가드 | 절대 클램프(CPU 70~95) → 사이클당 변화율 ±25% → 현재 대비 5% 미만 변화는 유지(`hysteresis`) |
| 효과 추정 | 일 max 기준 현재/제안 임계치 초과 일수 (`breach_days_*`, 근사) |

제외: 가용성 이진(StatusCheckFailed·HealthyHostCount·TunnelState…), 에러 카운트(5XX), `LessThan`
계열, SEV-1/2. Shadow 2주 관측 후 PoC(EC2 CPU·ALB RequestCount·TargetResponseTime)로 실제 적용 예정 —
그때 resolver 체인(태그 → 오버라이드 → 기본값)에 연결한다. 수동(태그·고객사 설정)은 자동보다 항상 우선.

## §13. 알람 등급(Severity) 체계

> 참고: [PagerDuty Incident Response — Severity Levels](https://response.pagerduty.com/before/severity_levels/), ITIL Incident Priority Matrix, Splunk/Datadog 등급 체계를 참고하여 MSP 환경에 맞게 재정의.

### 13-1. 등급 정의 (5단계, SEV 체계)

업계 표준인 SEV-1~5 체계를 채택한다. 숫자가 낮을수록 심각.

| 등급 | 코드 | 명칭 | 설명 | 대응 시간 | 알림 방식 |
|------|------|------|------|----------|----------|
| SEV-1 | Critical | 서비스 장애 | 고객 서비스 전면 중단. 다수 사용자 영향. SLA 위반 위험. | 즉시 (5분 내 확인) | 전화 + Slack + 에스컬레이션 |
| SEV-2 | High | 주요 기능 장애 | 핵심 기능 심각한 성능 저하 또는 부분 중단. 다수 사용자 영향. | 15분 내 확인 | Slack + 에스컬레이션 |
| SEV-3 | Medium | 부분 장애 | 일부 기능 제한 또는 단일 리소스 장애. 우회 가능. SEV-2로 확대 가능성. | 30분 내 확인 | Slack |
| SEV-4 | Low | 경미한 이슈 | 성능 저하, 단일 노드 장애 등. 고객 사용에 직접 영향 없음. | 4시간 내 확인 | Slack (저우선) |
| SEV-5 | Info | 참고/모니터링 | 정상 범위 내 추세 관찰. 버그/코스메틱 이슈. | 다음 업무 시간 | 로그만 |

SEV-1, SEV-2는 "Major Incident"로 분류하여 인시던트 대응 프로세스를 트리거한다 (Phase2).

### 13-2. 메트릭별 기본 등급 매핑

`alarm_registry.py`에 `_DEFAULT_SEVERITY` dict로 관리한다.
기본 등급은 "해당 메트릭이 ALARM 상태일 때의 비즈니스 영향도"를 기준으로 부여한다.

| 등급 | 메트릭 | 기준 |
|------|--------|------|
| SEV-1 | StatusCheckFailed, HealthyHostCount(<1), TunnelState(<1), ClusterStatusRed, ConnectionState(<1), HealthCheckStatus(<1) | 서비스 완전 중단 또는 접근 불가 |
| SEV-2 | ELB5XX(>임계치), CLB5XX, Errors(Lambda), UnHealthyHostCount(>임계치) | 에러 급증, 서비스 품질 심각 저하 |
| SEV-3 | CPU, Memory, Disk, FreeMemoryGB, FreeStorageGB, FreeLocalStorageGB, EngineCPU, ACUUtilization, DaysToExpiry | 리소스 포화 근접, 조치 안 하면 장애 가능 |
| SEV-4 | ReadLatency, WriteLatency, TargetResponseTime, TGResponseTime, Duration, ApiLatency | 성능 저하, 사용자 체감 가능하나 서비스 중단 아님 |
| SEV-5 | RequestCount, Connections, ProcessedBytes, ActiveFlowCount, NewFlowCount, ConnectionAttempts, BytesInPerSec | 트래픽/용량 참고 지표, 추세 모니터링 |

기본 등급이 정의되지 않은 메트릭은 SEV-5(Info)로 폴백한다.

### 13-3. 기본 등급 오버라이드

기본 등급은 시스템 전역 기본값이며, 다음 레벨에서 오버라이드 가능하다:

```
조회 우선순위 (높은 것이 우선):
1. 리소스별 오버라이드  — 특정 리소스의 특정 메트릭 등급 변경
2. 고객사별 오버라이드  — 고객사 전체에 적용되는 등급 정책
3. 시스템 기본값        — _DEFAULT_SEVERITY dict
```

Phase1: 시스템 기본값만 사용 (코드 내 dict)
Phase2: DB 도입 후 고객사별/리소스별 오버라이드 지원

### 13-4. Severity 저장: CloudWatch 알람 태그

Severity는 AlarmDescription이 아닌 CloudWatch 알람 태그(Tags)에 저장한다.

```python
# 알람 생성 시
cw.put_metric_alarm(AlarmName=name, ...)
cw.tag_resource(
    ResourceARN=f"arn:aws:cloudwatch:{region}:{account}:alarm:{name}",
    Tags=[
        {"Key": "Severity", "Value": severity},   # "SEV-1" ~ "SEV-5"
        {"Key": "ManagedBy", "Value": "AlarmManager"},
    ]
)
```

선택 이유:
- severity 변경 시 `tag_resource`만 호출 (알람 재생성/PutMetricAlarm 불필요)
- DescribeAlarms + list_tags_for_resource로 조회 가능
- CloudWatch 네이티브, 별도 인프라 없음

### 13-5. Severity 변경

severity만 변경할 때는 `tag_resource`만 호출한다 (알람 재생성 없음).
Phase1: 코드에서 기본값 자동 부여만. UI에서는 읽기 전용 뱃지.
Phase2: UI에서 드롭다운으로 변경 가능 → tag_resource + DB 동시 업데이트.

## §14. Phase2 UI 범위 구분

### 14-1. 알람 매니징 (현재 범위)

알람 CRUD, 리소스 조회/필터링, 벌크 알람 설정, 고객사별 기본 임계치, 알람 동기화/드리프트 감지,
뮤트 규칙, 커버리지 리포트, xlsx 임포트, 템플릿 관리, 감사 로그, 동기화 상태,
Severity 읽기 전용 뱃지 + 기본값 dict + 알람 태그 저장, 알림(AWS Chatbot → Slack 기존 파이프라인).

### 14-2. 24x7 관제 (향후 범위)

알람 이벤트 수집 파이프라인, 알림 채널 등록/관리 UI, 알림 라우팅 규칙 엔진,
Severity 변경 UI, 에스컬레이션 체인, 인시던트 관리/Acknowledge, 실시간 알람 피드(WebSocket), 교대 근무 관리.

### 14-3. 현재 범위에서 미리 깔아둘 것

- `_DEFAULT_SEVERITY` dict를 `alarm_registry.py`에 유지
- 알람 생성 시 CloudWatch 알람 태그에 `Severity` 저장
- AlarmDescription에 `customer_id`, `account_id` 필드 예약 (멀티어카운트 대비)
- 고객사 데이터 모델에 severity 오버라이드 슬롯 예약 (DB 스키마)
- UI에서 Severity 읽기 전용 뱃지 표시 (변경은 24x7 관제 범위)

## §15. 알림 흐름

### 15-1. Phase1 (현재)

```
CloudWatch ALARM → SNS → AWS Chatbot → Slack (고객사별)
```

### 15-2. Phase2 (향후)

```
CloudWatch ALARM → SNS → Lambda(알림 라우터)
→ 알람 태그에서 Severity 조회
→ DB에서 라우팅 규칙 매칭 (severity + customer + resource_type)
→ 채널별 분기 (Slack/PagerDuty/Email/Webhook)
```

## §16. 서비스 확장 패턴

- **서비스 스위칭**: 상단 서비스 스위처 패턴. 현재 "Alarm Manager" 단독 → 향후 24x7 Monitoring, FinOps 등 추가. 글로벌 필터(고객사/어카운트)는 서비스 간 공유.
- **고객사 관리**: 현재 Settings 내 경량 관리 → 향후 플랫폼 코어로 승격 가능하도록 API 경계 분리.
- **멀티 클라우드**: 데이터 모델에 `provider` 필드 예약 (기본값: "aws"). UI 필터에 Cloud Provider 슬롯 예약.

---

## 부록 A. AWS 리소스 Name 태그 네이밍 컨벤션

### 포맷

```
{env}-{resource_type}-{service}-{seq}
```

| 세그먼트 | 설명 | 예시 |
|----------|------|------|
| `env` | 환경 | `dev`, `stg`, `prod` |
| `resource_type` | AWS 리소스 타입 약어 | 아래 표 참조 |
| `service` | 서비스/앱 이름 | `web`, `api`, `order` |
| `seq` | 순번 또는 용도 (선택) | `01`, `http`, `grpc` |

### 리소스 타입 약어

| 약어 | 리소스 | 비고 |
|------|--------|------|
| `ec2` | EC2 Instance | |
| `rds` | RDS Instance | |
| `alb` | Application Load Balancer | |
| `nlb` | Network Load Balancer | |
| `tg` | Target Group | LB 타입과 무관하게 `tg` 사용 |
| `sg` | Security Group | |
| `vpc` | VPC | |
| `sn` | Subnet | |
| `rt` | Route Table | |
| `igw` | Internet Gateway | |
| `nat` | NAT Gateway | |
| `s3` | S3 Bucket | |
| `lam` | Lambda Function | |
| `cw` | CloudWatch Alarm/Dashboard | |

### 규칙

- 소문자 + 숫자 + 하이픈(`-`)만 사용, 하이픈으로 시작/끝나지 않음
- TG·ALB/NLB 이름은 AWS 제한 32자 이내
- CloudFormation 스택 이름에 리소스 타입을 넣지 않음 (예: `nlb-alb-ec2-lab` 금지 → `monitoring-lab-dev`)
- 환경이 단일 계정에 하나뿐이면 `env` 생략 가능 (`alb-web`, `ec2-api-01`)

예시: `prod-alb-web`, `prod-tg-web-http`, `dev-ec2-web-01`, `dev-rds-order`, `stg-sg-web-public`
