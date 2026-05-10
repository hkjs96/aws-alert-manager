---
inclusion: fileMatch
fileMatchPattern: '**/*.py'
---

# Collector 인터페이스 & 새 리소스 추가 체크리스트

## §5. Collector 인터페이스

새 Collector 추가 시 `common/collectors/base.py`의 `CollectorProtocol`을 구현한다.
필수 메서드:
- `collect_monitored_resources() -> list[ResourceInfo]`
- `get_metrics(resource_id: str, resource_tags: dict) -> dict[str, float] | None`
- `resolve_alive_ids(tag_names: set[str]) -> set[str]`

메트릭 조회는 `common/collectors/base.py`의 공통 `query_metric()` 유틸리티를 사용한다.

### 5-1. resolve_alive_ids 구현 규칙

- 각 Collector는 자기 리소스의 alive 체크를 `resolve_alive_ids`에서 직접 담당한다
- `daily_monitor/lambda_handler.py`에 alive 체크 로직을 하드코딩하지 않는다
- 입력: 알람 TagName 집합 (알람 이름의 `(TagName: ...)` 부분에서 추출된 값)
- 출력: 실제 AWS 리소스가 존재하는 TagName 부분집합
- TagName은 `_shorten_elb_resource_id()`가 생성한 short ID 형식이므로, collector가 이를 원본 리소스 식별자로 역매핑해야 한다
- 역매핑이 필요한 리소스 타입 (TagName ≠ resource_id):
  - MQ: `{broker_name}-{1|2}` → suffix 제거 후 broker name으로 조회
  - APIGW HTTP/WS: `{api_name}/{api_id}` → split 후 api_id로 조회
  - ACM: 도메인명 → `list_certificates` + `describe_certificate`로 도메인 매칭
  - ALB/NLB/TG: short ID (`{name}/{hash}`) → ARN이 아닌 경우 보수적으로 alive 처리
- 역매핑이 불필요한 리소스 타입 (TagName == resource_id): EC2, RDS, CLB, ElastiCache, NAT, Lambda, VPN, Backup, OpenSearch, DocDB
- 에러 처리: `ClientError`만 catch, 기존 collector의 boto3 클라이언트 싱글턴 재사용

## §11. 새 리소스 타입 추가 체크리스트

새로운 AWS 리소스 타입(예: Lambda, S3, ECS 등)을 모니터링 대상에 추가할 때 아래 항목을 모두 확인한다.

### 11-1. 메트릭 및 디멘션 확인 (AWS 공식 문서 필수)

- AWS CloudWatch 공식 문서에서 해당 리소스의 메트릭 목록, 네임스페이스, 디멘션을 확인한다
- LB 레벨 vs TG 레벨 등 디멘션 계층 구분이 있는 경우 반드시 구분한다 (§6-1 참조)
- 커스텀 에이전트 메트릭(CWAgent 등)이 필요한 경우 별도 네임스페이스/디멘션 확인

### 11-2. CloudTrail 이벤트 확인 (리소스 생명주기)

- AWS API 공식 문서에서 해당 리소스의 생명주기 API를 확인한다:
  - **CREATE**: 리소스 생성 API (예: `RunInstances`, `CreateLoadBalancer`)
  - **MODIFY**: 리소스 변경 API (예: `ModifyInstanceAttribute`, `ModifyLoadBalancerAttributes`)
  - **DELETE**: 리소스 삭제 API (예: `TerminateInstances`, `DeleteLoadBalancer`, `DeleteTargetGroup`)
  - **TAG_CHANGE**: 태그 변경 API (예: `CreateTags`, `AddTags`)
- 확인된 API를 아래 3개 레이어에 모두 등록한다:
  1. `common/__init__.py` → `MONITORED_API_EVENTS` 해당 카테고리에 추가
  2. `template.yaml` → `CloudTrailModifyRule` EventPattern `detail.eventName`에 추가
  3. `remediation_handler/lambda_handler.py` → `_API_MAP`에 (resource_type, id_extractor) 매핑 추가
- CREATE 이벤트는 `responseElements`에서 ID를 추출하는 경우가 많으므로 주의

### 11-3. 필수 알람 자동 생성 (Monitoring=on)

- `Monitoring=on` (대소문자 무관) 태그가 있는 리소스에 대해 기본 알람을 자동 생성한다
- `common/alarm_manager.py`의 하드코딩 알람 정의(`_*_ALARMS`)에 필수 메트릭 추가
- `common/__init__.py`의 `HARDCODED_DEFAULTS`에 기본 임계치 추가
- `common/__init__.py`의 `SUPPORTED_RESOURCE_TYPES`에 리소스 타입 추가

### 11-4. 태그 기반 임계치 조정

- `Threshold_{MetricName}={Value}` 태그로 하드코딩 기본 임계치를 오버라이드할 수 있다
- 하드코딩 알람 정의의 `metric_key`가 태그 suffix와 매칭되어야 한다 (예: `Threshold_CPU=90`)
- 동적 알람: 하드코딩 목록에 없는 메트릭도 `Threshold_*` 태그로 알람 생성 가능
  - `_resolve_metric_dimensions()`가 `list_metrics` API로 네임스페이스/디멘션을 자동 해석
  - 해당 리소스의 탐색 네임스페이스를 `_NAMESPACE_SEARCH_MAP`에 등록해야 한다
- 임계치 조회 우선순위: 태그 → 환경 변수(`DEFAULT_{METRIC}_THRESHOLD`) → `HARDCODED_DEFAULTS`

### 11-5. 커스텀 메트릭 환산 (단위 변환이 필요한 경우)

- AWS 메트릭이 사용자 친화적 단위가 아닌 경우 환산 로직이 필요할 수 있다
  - 예: RDS `FreeableMemory` (bytes) → `FreeMemoryGB` (GB 단위로 태그/임계치 관리)
  - 예: RDS `FreeStorageSpace` (bytes) → `FreeStorageGB`
- 환산이 필요한 경우:
  1. 알람 정의에 `multiplier` 필드를 추가하여 임계치 변환 (예: GB → bytes: `multiplier=1073741824`)
  2. `metric_key`는 사용자 친화적 이름 사용 (예: `FreeMemoryGB`), `metric_name`은 실제 CloudWatch 메트릭 이름 사용
  3. 알람 이름의 `display_metric`과 `unit`도 환산된 단위로 표시
- 새 리소스 추가 시 이런 환산 케이스가 있는지 사전에 확인하고, 있으면 설계 단계에서 조율한다
- CWAgent 등 커스텀 에이전트 메트릭은 에이전트 설정에서 단위를 제어할 수 있으므로 환산 불필요한 경우가 많다

### 11-6. Collector 구현

- `common/collectors/` 하위에 새 Collector 모듈을 추가한다 (§5 참조)
- `collect_monitored_resources()`: `Monitoring=on` 태그 필터링 + 리소스 정보 수집
- `get_metrics()`: CloudWatch 메트릭 조회 (§6-1 디멘션 규칙 준수)
- `resolve_alive_ids()`: 알람 TagName → AWS 리소스 존재 여부 확인 (§5-1 참조)
- `daily_monitor/lambda_handler.py`의 `_COLLECTOR_MODULES` 리스트에 새 Collector 등록
- `daily_monitor/lambda_handler.py`의 `_RESOURCE_TYPE_TO_COLLECTOR` dict에 리소스 타입 → collector 매핑 추가
  - 타입 alias가 있는 경우 모두 등록 (예: `AuroraRDS` → `rds_collector`, `NATGateway` → `natgw_collector`)
- `_shorten_elb_resource_id()`에서 TagName 변환이 필요한 경우 (TagName ≠ resource_id), `resolve_alive_ids`에서 역매핑 로직을 반드시 구현한다
- alive 체크 로직을 `lambda_handler.py`에 직접 작성하지 않는다 (§5-1 위반)

### 11-7. SRE 골든 시그널 기반 메트릭 선정 (필수 검토)

새 리소스 타입의 하드코딩 알람을 정의할 때, SRE 4대 골든 시그널을 기준으로 메트릭 커버리지를 검토한다.
모든 시그널을 반드시 하드코딩할 필요는 없지만, 각 시그널에 해당하는 메트릭이 있는지 확인하고 판단 근거를 기록한다.

| 시그널 | 설명 | 하드코딩 기준 | 동적 알람 후보 기준 |
|--------|------|-------------|-------------------|
| **Latency** (응답 시간) | 요청 처리 지연 | 사용자 체감 직결 메트릭 (예: TargetResponseTime) | DB 쿼리 레이턴시 등 워크로드별 차이가 큰 메트릭 |
| **Traffic** (처리량) | 요청/데이터 처리량 | 과부하 감지용 (예: RequestCount) | 급증/급감 감지가 필요한 세부 메트릭 |
| **Errors** (에러율) | 실패/에러 발생 | 서비스 가용성 직결 (예: 5XX, StatusCheckFailed) | 애플리케이션 레벨 에러 (Deadlocks, LoginFailures 등) |
| **Saturation** (포화도) | 리소스 사용률 | CPU, 메모리, 스토리지, 연결 수 | I/O 병목 (DiskQueueDepth), 스왑 등 |

#### 검토 절차

1. AWS CloudWatch 공식 문서에서 해당 리소스의 전체 메트릭 목록을 확인한다
2. 각 메트릭을 4대 시그널로 분류한다
3. 시그널별 최소 1개 이상의 하드코딩 메트릭을 선정한다:
   - Latency: 사용자 체감 응답 시간 메트릭 우선
   - Traffic: 전체 처리량 메트릭 (Count 또는 Bytes)
   - Errors: 서비스 중단 직결 에러 메트릭
   - Saturation: CPU, 메모리, 스토리지 중 해당 리소스에 적용 가능한 것
4. 하드코딩에 포함하지 않는 메트릭은 동적 알람(`Threshold_*` 태그)으로 활용 가능한지 확인한다
5. 메트릭별 비교 방향(GreaterThan vs LessThan)을 명시한다:
   - "높을수록 위험": `GreaterThanThreshold` (CPU, Latency, Errors, Connections 등)
   - "낮을수록 위험": `LessThanThreshold` (FreeMemory, FreeStorage, HealthyHostCount 등)
   - 동적 알람에서 "낮을수록 위험" 메트릭은 `Threshold_LT_` prefix 사용 안내 필요

#### 현재 리소스별 골든 시그널 커버리지

| 리소스 | Latency | Traffic | Errors | Saturation |
|--------|---------|---------|--------|------------|
| EC2 | - | - | StatusCheckFailed | CPU, Memory, Disk |
| RDS | ReadLatency, WriteLatency | - | - | CPU, FreeMemoryGB, FreeStorageGB, Connections |
| Aurora Prov. | ReadLatency, WriteLatency | - | - | CPU, FreeMemoryGB, FreeLocalStorageGB, Connections, ReplicaLag |
| Aurora SV2 | - | - | - | CPU, ACUUtilization, Connections |
| ALB | TargetResponseTime | RequestCount | ELB5XX | - |
| NLB | - | ProcessedBytes | - | ActiveFlowCount, NewFlowCount, TCPClientReset, TCPTargetReset |
| TG | TGResponseTime | RequestCountPerTarget | - | HealthyHostCount, UnHealthyHostCount |

**빈 칸은 동적 알람으로 커버 가능** (예: Aurora `CommitLatency`, `Deadlocks` 등)

### 11-8. 인스턴스 변형별 메트릭 가용성 확인

동일 리소스 타입이라도 인스턴스 클래스/역할에 따라 발행되는 메트릭이 다를 수 있다.
새 리소스 추가 시 아래 사항을 확인한다:

- **인스턴스 클래스별 차이**: 예) Aurora Serverless v2는 `FreeLocalStorage` 미발행 (KI-006)
- **역할별 차이**: 예) Aurora Writer만 `AuroraReplicaLagMaximum` 발행, Reader만 `AuroraReplicaLag` 발행 (KI-007)
- **구성별 차이**: 예) Writer-only 클러스터는 ReplicaLag 메트릭 미발행
- 확인된 차이는 `_get_alarm_defs()`에서 `resource_tags` 기반 조건부 분기로 처리한다
- 메트릭 가용성 매트릭스를 스펙 문서에 기록하고, E2E 테스트로 검증한다

### 11-9. 퍼센트 기반 임계치 검토

메모리, 스토리지 등 절대값 메트릭은 인스턴스 사양에 따라 의미가 달라진다.
새 리소스 추가 시 아래 사항을 검토한다:

- 인스턴스 클래스별 총 용량이 다른 메트릭이 있는지 확인 (예: FreeableMemory, FreeStorageSpace)
- 해당 메트릭에 퍼센트 기반 임계치가 적합한지 판단
- 적합한 경우:
  1. Collector에서 `_total_{resource}_bytes` 내부 태그를 설정
  2. `_INSTANCE_CLASS_MEMORY_MAP` 등 lookup 테이블에 인스턴스 클래스 추가
  3. `_resolve_free_memory_threshold()` 패턴을 참고하여 퍼센트 해석 로직 구현
- Serverless/Auto-scaling 리소스는 용량이 동적 변동하므로 퍼센트 기반이 부적합할 수 있음 (ACUUtilization 등 대체 메트릭 사용)

### 11-10. E2E 테스트 인프라 정리 시 주의사항

CloudFormation 스택 삭제 시 일부 리소스는 내부 데이터가 남아있으면 `DELETE_FAILED`가 발생한다.
새 리소스를 E2E 테스트 인프라에 추가할 때 아래 패턴을 확인하고, 필요하면 cleanup CustomResource를 추가한다.

| 리소스 | 삭제 실패 원인 | 해결 방법 |
|--------|-------------|----------|
| Backup Vault | recovery point가 남아있음 | CustomResource로 `delete_recovery_point` 선호출 (template 참조) |
| S3 Bucket | 객체가 남아있음 | CustomResource로 `delete_objects` + `delete_bucket` |
| ECR Repository | 이미지가 남아있음 | CustomResource로 `batch_delete_image` |
| OpenSearch Domain | 삭제에 10~15분 소요 | `DeletionPolicy: Delete` (기본값), 타임아웃 주의 |

- E2E 테스트 template(`infra-test/`)에 새 리소스 추가 시, 해당 리소스가 내부 데이터를 생성하는지 확인한다
- 내부 데이터가 생성되는 경우, 스택 삭제 전에 데이터를 정리하는 CustomResource Lambda를 함께 추가한다
- CustomResource의 Delete 핸들러에서 에러 발생 시에도 `SUCCESS`를 반환하여 스택 삭제가 블로킹되지 않도록 한다

### 11-10. Container Insights 의존 메트릭 (ECS/EKS)

ECS/EKS의 일부 메트릭은 기본 `AWS/ECS` 네임스페이스가 아닌 `ECS/ContainerInsights` 네임스페이스에서만 발행된다.
Container Insights를 활성화하지 않으면 해당 메트릭이 존재하지 않아 알람이 항상 INSUFFICIENT_DATA 상태가 된다.

| 메트릭 | 기본 네임스페이스 | Container Insights 네임스페이스 | 비고 |
|--------|------------------|-------------------------------|------|
| CPUUtilization | AWS/ECS | ECS/ContainerInsights | 기본 발행 |
| MemoryUtilization | AWS/ECS | ECS/ContainerInsights | 기본 발행 |
| RunningTaskCount | - | ECS/ContainerInsights | **Container Insights 전용** |
| NetworkRxBytes | - | ECS/ContainerInsights | Container Insights 전용 |
| NetworkTxBytes | - | ECS/ContainerInsights | Container Insights 전용 |

- 현재 ECS 하드코딩 알람은 `AWS/ECS` 네임스페이스의 CPUUtilization/MemoryUtilization만 포함
- RunningTaskCount는 Container Insights 활성화 시 동적 알람(`Threshold_RunningTaskCount` 태그)으로 사용 가능
- 향후 Container Insights 지원 시 `_get_alarm_defs("ECS")` 분기에서 `_has_container_insights` Internal_Tag 기반으로 RunningTaskCount 포함 여부를 결정
- EKS 지원 추가 시에도 동일 패턴 적용 (EKS 메트릭은 `ContainerInsights` 네임스페이스)
