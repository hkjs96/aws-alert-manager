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

메트릭 조회는 `common/collectors/base.py`의 공통 `query_metric()` 유틸리티를 사용한다.

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
- `daily_monitor/lambda_handler.py`에 새 Collector 등록
