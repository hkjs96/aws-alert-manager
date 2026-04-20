# Requirements Document

## Introduction

AWS 모니터링 엔진에 ElastiCache(Redis)와 NAT Gateway 두 개의 새 리소스 타입을 추가한다.
기존 아키텍처(alarm_registry, alarm_naming, alarm_builder, Collector 패턴)를 그대로 따르며,
`Monitoring=on` 태그가 있는 리소스에 대해 CloudWatch 알람을 자동 생성/삭제/동기화한다.

엑셀 표준 메트릭 정의에 따라 ElastiCache는 5개 메트릭, NAT Gateway는 2개 메트릭을 하드코딩 알람으로 등록한다.

## Glossary

- **Monitoring_Engine**: AWS 모니터링 엔진 시스템 전체. CloudWatch 알람 자동 생성/삭제/동기화를 수행한다
- **Alarm_Registry**: `common/alarm_registry.py` 모듈. 리소스 유형별 알람 정의, 메트릭 키 매핑, 네임스페이스/디멘션 매핑을 관리한다
- **Collector**: `common/collectors/` 하위 모듈. `CollectorProtocol`을 구현하여 `Monitoring=on` 리소스를 수집하고 CloudWatch 메트릭을 조회한다
- **ElastiCache_Collector**: ElastiCache(Redis) 리소스를 수집하는 Collector 모듈
- **NATGateway_Collector**: NAT Gateway 리소스를 수집하는 Collector 모듈
- **Alarm_Manager**: `common/alarm_manager.py` 모듈. 알람 동기화(생성/업데이트/삭제) 로직을 담당한다
- **Remediation_Handler**: `remediation_handler/lambda_handler.py`. CloudTrail 이벤트를 수신하여 리소스 변경에 대응한다
- **Daily_Monitor**: `daily_monitor/lambda_handler.py`. 매일 1회 실행되어 알람 동기화 및 메트릭 임계치 비교를 수행한다
- **HARDCODED_DEFAULTS**: `common/__init__.py`의 기본 임계치 딕셔너리
- **CacheClusterId**: ElastiCache Redis 노드의 CloudWatch 디멘션 키
- **NatGatewayId**: NAT Gateway의 CloudWatch 디멘션 키

## Requirements

### Requirement 1: ElastiCache(Redis) 알람 레지스트리 등록

**User Story:** As a 운영자, I want ElastiCache(Redis) 노드에 대한 하드코딩 알람 정의가 Alarm_Registry에 등록되기를, so that `Monitoring=on` 태그 시 표준 메트릭 알람이 자동 생성된다.

#### Acceptance Criteria

1. THE Alarm_Registry SHALL define `_ELASTICACHE_ALARMS` with the following 5 metrics: CPUUtilization (GreaterThanOrEqualToThreshold, 90, Percent), EngineCPUUtilization (GreaterThanOrEqualToThreshold, 90, Percent), SwapUsage (GreaterThanOrEqualToThreshold, 1.0, Bytes), Evictions (GreaterThanOrEqualToThreshold, 5.0, Count), CurrConnections (GreaterThanOrEqualToThreshold, 200.0, Count)
2. THE Alarm_Registry SHALL use namespace `AWS/ElastiCache` and dimension_key `CacheClusterId` for all ElastiCache alarm definitions
3. THE Alarm_Registry SHALL return `_ELASTICACHE_ALARMS` from `_get_alarm_defs()` WHEN resource_type is `ElastiCache`
4. THE Alarm_Registry SHALL include `ElastiCache` in `_HARDCODED_METRIC_KEYS` with keys `{CPU, EngineCPU, SwapUsage, Evictions, CurrConnections}`
5. THE Alarm_Registry SHALL include `ElastiCache` in `_NAMESPACE_MAP` with value `["AWS/ElastiCache"]`
6. THE Alarm_Registry SHALL include `ElastiCache` in `_DIMENSION_KEY_MAP` with value `CacheClusterId`
7. THE Alarm_Registry SHALL add ElastiCache metric entries to `_metric_name_to_key()` mapping: CPUUtilization→CPU, EngineCPUUtilization→EngineCPU, SwapUsage→SwapUsage, Evictions→Evictions, CurrConnections→CurrConnections
8. THE Alarm_Registry SHALL add ElastiCache metric entries to `_METRIC_DISPLAY`: CPU→(CPUUtilization, >=, %), EngineCPU→(EngineCPUUtilization, >=, %), SwapUsage→(SwapUsage, >=, Bytes), Evictions→(Evictions, >=, ), CurrConnections→(CurrConnections, >=, )

### Requirement 2: NAT Gateway 알람 레지스트리 등록

**User Story:** As a 운영자, I want NAT Gateway에 대한 하드코딩 알람 정의가 Alarm_Registry에 등록되기를, so that `Monitoring=on` 태그 시 표준 메트릭 알람이 자동 생성된다.

#### Acceptance Criteria

1. THE Alarm_Registry SHALL define `_NATGW_ALARMS` with the following 2 metrics: PacketsDropCount (GreaterThanThreshold, 1.0, Count), ErrorPortAllocation (GreaterThanThreshold, 1.0, Count)
2. THE Alarm_Registry SHALL use namespace `AWS/NATGateway` and dimension_key `NatGatewayId` for all NAT Gateway alarm definitions
3. THE Alarm_Registry SHALL return `_NATGW_ALARMS` from `_get_alarm_defs()` WHEN resource_type is `NATGateway`
4. THE Alarm_Registry SHALL include `NATGateway` in `_HARDCODED_METRIC_KEYS` with keys `{PacketsDropCount, ErrorPortAllocation}`
5. THE Alarm_Registry SHALL include `NATGateway` in `_NAMESPACE_MAP` with value `["AWS/NATGateway"]`
6. THE Alarm_Registry SHALL include `NATGateway` in `_DIMENSION_KEY_MAP` with value `NatGatewayId`
7. THE Alarm_Registry SHALL add NAT Gateway metric entries to `_metric_name_to_key()` mapping: PacketsDropCount→PacketsDropCount, ErrorPortAllocation→ErrorPortAllocation
8. THE Alarm_Registry SHALL add NAT Gateway metric entries to `_METRIC_DISPLAY`: PacketsDropCount→(PacketsDropCount, >, ), ErrorPortAllocation→(ErrorPortAllocation, >, )

### Requirement 3: 공통 상수 등록

**User Story:** As a 개발자, I want ElastiCache와 NAT Gateway의 기본 임계치와 리소스 타입이 공통 상수에 등록되기를, so that 임계치 해석 체인(태그→환경변수→HARDCODED_DEFAULTS)이 정상 동작한다.

#### Acceptance Criteria

1. THE Monitoring_Engine SHALL include `ElastiCache` and `NATGateway` in `SUPPORTED_RESOURCE_TYPES` list
2. THE Monitoring_Engine SHALL add the following entries to `HARDCODED_DEFAULTS`: CPU→90.0, EngineCPU→90.0, SwapUsage→1.0, Evictions→5.0, CurrConnections→200.0, PacketsDropCount→1.0, ErrorPortAllocation→1.0
3. WHEN `HARDCODED_DEFAULTS` already contains a key `CPU` with value 80.0, THE Monitoring_Engine SHALL keep the existing value and use a distinct key for ElastiCache CPU (the ElastiCache CPU default of 90.0 is applied via the alarm definition's threshold, not by overwriting the shared `CPU` key)


### Requirement 4: ElastiCache Collector 구현

**User Story:** As a 운영자, I want `Monitoring=on` 태그가 있는 ElastiCache(Redis) 노드가 자동 수집되기를, so that Daily_Monitor가 해당 노드의 알람을 동기화하고 메트릭을 조회할 수 있다.

#### Acceptance Criteria

1. THE ElastiCache_Collector SHALL implement `collect_monitored_resources()` returning `list[ResourceInfo]` for ElastiCache Redis nodes with `Monitoring=on` tag (case-insensitive)
2. THE ElastiCache_Collector SHALL implement `get_metrics(resource_id, resource_tags)` returning CloudWatch metrics for the given CacheClusterId using namespace `AWS/ElastiCache` and dimension `CacheClusterId`
3. THE ElastiCache_Collector SHALL use `boto3.client("elasticache")` with `functools.lru_cache` singleton pattern per coding governance §1
4. THE ElastiCache_Collector SHALL skip nodes with status `deleting` or `deleted` and log the skip reason
5. THE ElastiCache_Collector SHALL filter only Redis engine nodes (engine == "redis")
6. WHEN a CloudWatch metric has no data points, THE ElastiCache_Collector SHALL skip that metric and log an info message
7. WHEN `describe_cache_clusters` API call fails, THE ElastiCache_Collector SHALL raise the `ClientError` after logging

### Requirement 5: NAT Gateway Collector 구현

**User Story:** As a 운영자, I want `Monitoring=on` 태그가 있는 NAT Gateway가 자동 수집되기를, so that Daily_Monitor가 해당 NAT Gateway의 알람을 동기화하고 메트릭을 조회할 수 있다.

#### Acceptance Criteria

1. THE NATGateway_Collector SHALL implement `collect_monitored_resources()` returning `list[ResourceInfo]` for NAT Gateways with `Monitoring=on` tag (case-insensitive)
2. THE NATGateway_Collector SHALL implement `get_metrics(resource_id, resource_tags)` returning CloudWatch metrics for the given NatGatewayId using namespace `AWS/NATGateway` and dimension `NatGatewayId`
3. THE NATGateway_Collector SHALL use `boto3.client("ec2")` with `functools.lru_cache` singleton pattern per coding governance §1
4. THE NATGateway_Collector SHALL skip NAT Gateways with state `deleting` or `deleted` and log the skip reason
5. WHEN a CloudWatch metric has no data points, THE NATGateway_Collector SHALL skip that metric and log an info message
6. WHEN `describe_nat_gateways` API call fails, THE NATGateway_Collector SHALL raise the `ClientError` after logging

### Requirement 6: Daily Monitor Collector 등록

**User Story:** As a 개발자, I want ElastiCache_Collector와 NATGateway_Collector가 Daily_Monitor에 등록되기를, so that 매일 자동 실행 시 새 리소스 타입도 처리된다.

#### Acceptance Criteria

1. THE Daily_Monitor SHALL import `elasticache` and `natgw` collector modules from `common.collectors`
2. THE Daily_Monitor SHALL include both collector modules in `_COLLECTOR_MODULES` list

### Requirement 7: CloudTrail 이벤트 등록 (ElastiCache)

**User Story:** As a 운영자, I want ElastiCache 리소스의 생명주기 이벤트(생성/삭제/태그변경)가 감지되기를, so that 알람이 실시간으로 생성/삭제된다.

#### Acceptance Criteria

1. THE Monitoring_Engine SHALL add `CreateCacheCluster` to `MONITORED_API_EVENTS["CREATE"]`
2. THE Monitoring_Engine SHALL add `DeleteCacheCluster` to `MONITORED_API_EVENTS["DELETE"]`
3. THE Monitoring_Engine SHALL add `ModifyCacheCluster` to `MONITORED_API_EVENTS["MODIFY"]`
4. THE Monitoring_Engine SHALL add `AddTagsToResource` to `MONITORED_API_EVENTS["TAG_CHANGE"]` (ElastiCache uses the same API name as RDS; already registered if shared)
5. THE Remediation_Handler SHALL add ElastiCache API events to `_API_MAP` with resource_type `ElastiCache` and appropriate ID extractor functions
6. WHEN `CreateCacheCluster` event is received, THE Remediation_Handler SHALL extract CacheClusterId from `responseElements`
7. THE template.yaml CloudTrailModifyRule SHALL include `CreateCacheCluster`, `DeleteCacheCluster`, `ModifyCacheCluster` in the eventName list
8. THE template.yaml CloudTrailModifyRule SHALL include `aws.elasticache` in the source list

### Requirement 8: CloudTrail 이벤트 등록 (NAT Gateway)

**User Story:** As a 운영자, I want NAT Gateway 리소스의 생명주기 이벤트(생성/삭제/태그변경)가 감지되기를, so that 알람이 실시간으로 생성/삭제된다.

#### Acceptance Criteria

1. THE Monitoring_Engine SHALL add `CreateNatGateway` to `MONITORED_API_EVENTS["CREATE"]`
2. THE Monitoring_Engine SHALL add `DeleteNatGateway` to `MONITORED_API_EVENTS["DELETE"]`
3. THE Monitoring_Engine SHALL add `CreateTags` and `DeleteTags` to `MONITORED_API_EVENTS["TAG_CHANGE"]` for NAT Gateway (already registered for EC2; NAT Gateway uses the same EC2 tag API)
4. THE Remediation_Handler SHALL add NAT Gateway API events to `_API_MAP` with resource_type `NATGateway` and appropriate ID extractor functions
5. WHEN `CreateNatGateway` event is received, THE Remediation_Handler SHALL extract NatGatewayId from `responseElements`
6. THE template.yaml CloudTrailModifyRule SHALL include `CreateNatGateway`, `DeleteNatGateway` in the eventName list

### Requirement 9: 태그 기반 임계치 오버라이드

**User Story:** As a 운영자, I want ElastiCache와 NAT Gateway 리소스에 `Threshold_*` 태그를 설정하여 기본 임계치를 오버라이드하기를, so that 리소스별 맞춤 임계치를 적용할 수 있다.

#### Acceptance Criteria

1. WHEN an ElastiCache resource has a `Threshold_CurrConnections=300` tag, THE Monitoring_Engine SHALL create the CurrConnections alarm with threshold 300.0 instead of the default 200.0
2. WHEN a NATGateway resource has a `Threshold_PacketsDropCount=5` tag, THE Monitoring_Engine SHALL create the PacketsDropCount alarm with threshold 5.0 instead of the default 1.0
3. THE Monitoring_Engine SHALL support dynamic alarms for ElastiCache and NATGateway via `Threshold_*` tags for metrics not in the hardcoded list, using `_NAMESPACE_SEARCH_MAP` for dimension resolution

### Requirement 10: SRE 골든 시그널 커버리지 검토

**User Story:** As a SRE, I want ElastiCache와 NAT Gateway의 하드코딩 메트릭이 SRE 4대 골든 시그널을 적절히 커버하기를, so that 핵심 장애 시그널을 놓치지 않는다.

#### Acceptance Criteria

1. THE Monitoring_Engine SHALL cover the following golden signals for ElastiCache: Saturation (CPUUtilization, EngineCPUUtilization, SwapUsage, CurrConnections), Errors (Evictions as cache eviction indicates saturation/capacity issue)
2. THE Monitoring_Engine SHALL cover the following golden signals for NAT Gateway: Errors (PacketsDropCount, ErrorPortAllocation)
3. WHEN a golden signal is not covered by hardcoded alarms (e.g., ElastiCache Latency, NAT Gateway Traffic), THE Monitoring_Engine SHALL allow coverage via dynamic `Threshold_*` tags (e.g., `Threshold_StringGetLatency`, `Threshold_BytesOutToDestination`)

### Requirement 11: 거버넌스 §12 태그-메트릭 매핑 테이블 업데이트

**User Story:** As a 개발자, I want ElastiCache와 NAT Gateway의 태그-메트릭 매핑이 거버넌스 문서에 기록되기를, so that 향후 유지보수 시 매핑 관계를 쉽게 파악할 수 있다.

#### Acceptance Criteria

1. THE Alarm_Registry SHALL maintain the following ElastiCache tag-metric mapping: Threshold_CPU→CPU→CPUUtilization (AWS/ElastiCache, 90, %), Threshold_EngineCPU→EngineCPU→EngineCPUUtilization (AWS/ElastiCache, 90, %), Threshold_SwapUsage→SwapUsage→SwapUsage (AWS/ElastiCache, 1.0, Bytes), Threshold_Evictions→Evictions→Evictions (AWS/ElastiCache, 5.0, Count), Threshold_CurrConnections→CurrConnections→CurrConnections (AWS/ElastiCache, 200.0, Count)
2. THE Alarm_Registry SHALL maintain the following NATGateway tag-metric mapping: Threshold_PacketsDropCount→PacketsDropCount→PacketsDropCount (AWS/NATGateway, 1.0, Count), Threshold_ErrorPortAllocation→ErrorPortAllocation→ErrorPortAllocation (AWS/NATGateway, 1.0, Count)
