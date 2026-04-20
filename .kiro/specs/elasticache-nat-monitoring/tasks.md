# Implementation Plan: ElastiCache & NAT Gateway Monitoring

## Overview

기존 AWS Monitoring Engine에 ElastiCache(Redis)와 NAT Gateway 리소스 타입을 추가한다.
TDD red-green-refactor 사이클(거버넌스 §8)을 따르며, 데이터 등록 → Collector 구현 → 이벤트 등록 → 인프라 → 통합 순서로 진행한다.
Python 3.12, pytest + hypothesis + moto 사용.

## Tasks

- [x] 1. alarm_registry 데이터 등록 (ElastiCache + NAT Gateway)
  - [x] 1.1 `_ELASTICACHE_ALARMS` 정의 추가 (`common/alarm_registry.py`)
    - 5개 메트릭: CPU(CPUUtilization, >=, 90), EngineCPU(EngineCPUUtilization, >=, 90), SwapUsage(SwapUsage, >=, 1.0), Evictions(Evictions, >=, 5.0), CurrConnections(CurrConnections, >=, 200.0)
    - namespace `AWS/ElastiCache`, dimension_key `CacheClusterId`, stat `Average`, period 300, evaluation_periods 1
    - `_get_alarm_defs()` 에 `ElastiCache` 분기 추가
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 1.2 `_NATGW_ALARMS` 정의 추가 (`common/alarm_registry.py`)
    - 2개 메트릭: PacketsDropCount(PacketsDropCount, >, 1.0), ErrorPortAllocation(ErrorPortAllocation, >, 1.0)
    - namespace `AWS/NATGateway`, dimension_key `NatGatewayId`, stat `Sum`, period 300, evaluation_periods 1
    - `_get_alarm_defs()` 에 `NATGateway` 분기 추가
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 1.3 매핑 테이블 확장 (`common/alarm_registry.py`)
    - `_HARDCODED_METRIC_KEYS` 에 ElastiCache, NATGateway 키 집합 추가
    - `_NAMESPACE_MAP` 에 ElastiCache → `["AWS/ElastiCache"]`, NATGateway → `["AWS/NATGateway"]` 추가
    - `_DIMENSION_KEY_MAP` 에 ElastiCache → `CacheClusterId`, NATGateway → `NatGatewayId` 추가
    - `_metric_name_to_key()` 에 EngineCPUUtilization→EngineCPU, SwapUsage→SwapUsage, Evictions→Evictions, CurrConnections→CurrConnections, PacketsDropCount→PacketsDropCount, ErrorPortAllocation→ErrorPortAllocation 추가
    - `_METRIC_DISPLAY` 에 ElastiCache/NATGateway 메트릭 표시 정보 추가
    - _Requirements: 1.4, 1.5, 1.6, 1.7, 1.8, 2.4, 2.5, 2.6, 2.7, 2.8, 11.1, 11.2_

  - [x] 1.4 `common/__init__.py` 상수 확장
    - `SUPPORTED_RESOURCE_TYPES` 에 `"ElastiCache"`, `"NATGateway"` 추가
    - `HARDCODED_DEFAULTS` 에 EngineCPU→90.0, SwapUsage→1.0, Evictions→5.0, CurrConnections→200.0, PacketsDropCount→1.0, ErrorPortAllocation→1.0 추가 (기존 CPU 80.0 유지)
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ]* 1.5 PBT: Property 1 — 신규 리소스 타입 레지스트리 완전성
    - **Property 1: 신규 리소스 타입 레지스트리 완전성**
    - **Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.2, 2.3**
    - 파일: `tests/test_pbt_elasticache_natgw_registry.py`
    - `@given(rt=st.sampled_from(["ElastiCache", "NATGateway"]))` 로 검증
    - `_get_alarm_defs(rt)` 반환값이 비어있지 않고, 모든 필수 필드 포함, metric 집합이 `_HARDCODED_METRIC_KEYS[rt]`와 일치, namespace/dimension_key 정확성 검증

- [x] 2. Checkpoint — 레지스트리 데이터 검증
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. ElastiCache Collector 구현
  - [x] 3.1 `common/collectors/elasticache.py` — `collect_monitored_resources()` 구현
    - `boto3.client("elasticache")` lru_cache 싱글턴 (거버넌스 §1)
    - `describe_cache_clusters(ShowCacheNodeInfo=True)` 페이지네이션
    - engine == "redis" 필터, status deleting/deleted 제외 + 로그
    - `list_tags_for_resource` 로 태그 조회, Monitoring=on (case-insensitive) 필터
    - `ClientError` 시 로깅 후 re-raise (describe), 빈 dict 반환 (tags)
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.7_

  - [x] 3.2 `common/collectors/elasticache.py` — `get_metrics()` 구현
    - `base.query_metric()` 사용, namespace `AWS/ElastiCache`, dimension `CacheClusterId`
    - 5개 메트릭: CPUUtilization, EngineCPUUtilization, SwapUsage, Evictions, CurrConnections
    - 데이터 없는 메트릭 skip + info 로그, 모두 없으면 None 반환
    - _Requirements: 4.2, 4.6_

  - [ ]* 3.3 PBT: Property 2 — ElastiCache Collector 필터링
    - **Property 2: ElastiCache Collector 필터링**
    - **Validates: Requirements 4.1, 4.4, 4.5**
    - 파일: `tests/test_pbt_elasticache_collector_filter.py`
    - moto `@mock_aws` 로 ElastiCache 환경 모킹
    - 랜덤 engine(redis/memcached), status(available/creating/deleting/deleted), tag(Monitoring=on/off/absent) 조합 생성
    - `collect_monitored_resources()` 결과가 redis AND not deleting/deleted AND Monitoring=on 인 것만 포함하는지 검증

- [x] 4. NAT Gateway Collector 구현
  - [x] 4.1 `common/collectors/natgw.py` — `collect_monitored_resources()` 구현
    - `boto3.client("ec2")` lru_cache 싱글턴 (거버넌스 §1)
    - `describe_nat_gateways` 페이지네이션, Filter `tag:Monitoring=on`
    - state deleting/deleted 제외 + 로그
    - `ClientError` 시 로깅 후 re-raise
    - _Requirements: 5.1, 5.3, 5.4, 5.6_

  - [x] 4.2 `common/collectors/natgw.py` — `get_metrics()` 구현
    - `base.query_metric()` 사용, namespace `AWS/NATGateway`, dimension `NatGatewayId`
    - 2개 메트릭: PacketsDropCount, ErrorPortAllocation (stat `Sum`)
    - 데이터 없는 메트릭 skip + info 로그, 모두 없으면 None 반환
    - _Requirements: 5.2, 5.5_

  - [ ]* 4.3 PBT: Property 3 — NATGateway Collector 필터링
    - **Property 3: NATGateway Collector 필터링**
    - **Validates: Requirements 5.1, 5.4**
    - 파일: `tests/test_pbt_natgw_collector_filter.py`
    - moto `@mock_aws` 로 EC2/NAT Gateway 환경 모킹
    - 랜덤 state(available/pending/deleting/deleted), tag(Monitoring=on/off/absent) 조합 생성
    - `collect_monitored_resources()` 결과가 not deleting/deleted AND Monitoring=on 인 것만 포함하는지 검증

- [x] 5. Checkpoint — Collector 검증
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Remediation Handler 이벤트 등록
  - [x] 6.1 `common/__init__.py` — `MONITORED_API_EVENTS` 확장
    - CREATE: `CreateCacheCluster`, `CreateNatGateway` 추가
    - DELETE: `DeleteCacheCluster`, `DeleteNatGateway` 추가
    - MODIFY: `ModifyCacheCluster` 추가
    - _Requirements: 7.1, 7.2, 7.3, 8.1, 8.2_

  - [x] 6.2 `remediation_handler/lambda_handler.py` — `_API_MAP` 확장
    - `_extract_elasticache_ids(params)`: `params["cacheClusterId"]` 추출
    - `_extract_natgw_ids(params)`: `params["natGatewayId"]` 추출
    - `_extract_natgw_create_ids(resp)`: `resp["natGateway"]["natGatewayId"]` 추출 (CREATE는 responseElements)
    - `_API_MAP` 에 CreateCacheCluster, DeleteCacheCluster, ModifyCacheCluster, CreateNatGateway, DeleteNatGateway 매핑 추가
    - _Requirements: 7.5, 7.6, 8.4, 8.5_

  - [ ]* 6.3 PBT: Property 4 — CloudTrail 이벤트 ID 추출 정확성
    - **Property 4: CloudTrail 이벤트 ID 추출 정확성**
    - **Validates: Requirements 7.5, 7.6, 8.4, 8.5**
    - 파일: `tests/test_pbt_elasticache_natgw_event.py`
    - 랜덤 CacheClusterId/NatGatewayId 생성
    - 5개 API(CreateCacheCluster, DeleteCacheCluster, ModifyCacheCluster, CreateNatGateway, DeleteNatGateway) 이벤트 구조 생성
    - `parse_cloudtrail_event()` 가 올바른 resource_id, resource_type, event_category를 반환하는지 검증

- [x] 7. tag_resolver 확장
  - [x] 7.1 `common/tag_resolver.py` — `get_resource_tags()` 에 ElastiCache/NATGateway 분기 추가
    - ElastiCache: `_get_elasticache_tags(resource_id)` — `elasticache.list_tags_for_resource(ResourceName=arn)` 사용
    - NATGateway: `_get_ec2_tags_by_resource(resource_id)` — `ec2.describe_tags(Filters=[{Name: "resource-id", Values: [natgw_id]}])` 사용
    - lru_cache 싱글턴 패턴 (elasticache client)
    - _Requirements: 9.1, 9.2_

  - [ ]* 7.2 PBT: Property 5 — 신규 메트릭 태그 임계치 오버라이드
    - **Property 5: 신규 메트릭 태그 임계치 오버라이드**
    - **Validates: Requirements 9.1, 9.2**
    - 파일: `tests/test_pbt_elasticache_natgw_threshold.py`
    - `@given(metric=st.sampled_from(["EngineCPU", "SwapUsage", "Evictions", "CurrConnections", "PacketsDropCount", "ErrorPortAllocation"]), val=positive_float)`
    - `Threshold_{metric}={val}` 태그 설정 시 `get_threshold(tags, metric)` 가 해당 값을 반환하는지 검증

  - [ ]* 7.3 PBT: Property 6 — 신규 리소스 타입 동적 알람 하드코딩 키 제외
    - **Property 6: 신규 리소스 타입 동적 알람 하드코딩 키 제외**
    - **Validates: Requirements 9.3**
    - 파일: `tests/test_pbt_elasticache_natgw_dynamic.py`
    - `@given(rt=st.sampled_from(["ElastiCache", "NATGateway"]))`
    - 하드코딩 메트릭 + 비하드코딩 메트릭 태그 조합 생성
    - `_parse_threshold_tags(tags, rt)` 가 하드코딩 키를 제외하고 비하드코딩 키만 포함하는지 검증

- [x] 8. Checkpoint — 이벤트 등록 및 태그 검증
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Daily Monitor 통합 등록
  - [x] 9.1 `daily_monitor/lambda_handler.py` — Collector 등록
    - `from common.collectors import elasticache as elasticache_collector` 추가
    - `from common.collectors import natgw as natgw_collector` 추가
    - `_COLLECTOR_MODULES` 에 `elasticache_collector`, `natgw_collector` 추가
    - _Requirements: 6.1, 6.2_

  - [x] 9.2 `daily_monitor/lambda_handler.py` — 고아 알람 정리 확장
    - `alive_checkers` 에 `"ElastiCache": _find_alive_elasticache_clusters` 추가
    - `alive_checkers` 에 `"NATGateway": _find_alive_nat_gateways` 추가
    - `_find_alive_elasticache_clusters(cluster_ids)`: `describe_cache_clusters` 로 존재 확인
    - `_find_alive_nat_gateways(natgw_ids)`: `describe_nat_gateways` 로 존재 확인
    - _Requirements: 6.1, 6.2_

  - [x] 9.3 `common/alarm_search.py` — 폴백 타입 목록 확장
    - `_find_alarms_for_resource()` 의 resource_type 미지정 시 검색 대상에 `"ElastiCache"`, `"NATGateway"` 추가
    - _Requirements: 1.3, 2.3_

- [x] 10. template.yaml 인프라 확장
  - [x] 10.1 CloudTrailModifyRule EventPattern 확장
    - `source` 에 `aws.elasticache` 추가
    - `detail.eventName` 에 `CreateCacheCluster`, `DeleteCacheCluster`, `ModifyCacheCluster`, `CreateNatGateway`, `DeleteNatGateway` 추가
    - _Requirements: 7.7, 7.8, 8.6_

  - [x] 10.2 IAM Policy 확장
    - Daily Monitor Role (`MonitoringEngineRole`): `elasticache:DescribeCacheClusters`, `elasticache:ListTagsForResource`, `ec2:DescribeNatGateways` 추가
    - Remediation Handler Role (`RemediationHandlerRole`): `elasticache:DescribeCacheClusters`, `elasticache:ListTagsForResource` 추가
    - _Requirements: 7.7, 7.8, 8.6_

- [x] 11. alarm_manager re-export 확장
  - `common/alarm_manager.py` 의 re-export 블록에 `_ELASTICACHE_ALARMS`, `_NATGW_ALARMS` 추가 (backward compatibility)
  - _Requirements: 1.3, 2.3_

- [x] 12. Final checkpoint — 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.
  - 기존 PBT(`test_pbt_registry_completeness.py`, `test_pbt_expand_alarm_defs.py` 등) 회귀 없음 확인
  - 신규 6개 PBT 모두 통과 확인

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation after each major phase
- Property tests validate universal correctness properties from the design document
- TDD red-green-refactor cycle: write failing test → minimal implementation → refactor (거버넌스 §8)
- 기존 `CPU` 키의 `HARDCODED_DEFAULTS` 값 80.0은 변경하지 않음 (Requirement 3.3)
