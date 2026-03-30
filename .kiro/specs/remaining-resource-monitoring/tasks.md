# Implementation Plan: Remaining Resource Monitoring

## Overview

AWS Monitoring Engine에 미구현 8개 리소스 타입(Lambda, VPN, API Gateway, ACM, AWS Backup, Amazon MQ, CLB, OpenSearch)을 추가한다. TDD 레드-그린-리팩터링 사이클(거버넌스 §8)을 따르며, 설계 문서의 Correctness Properties 10개에 대한 PBT 테스트를 포함한다.

변경 파일: `common/alarm_registry.py`, `common/__init__.py`, `common/collectors/lambda_fn.py` (NEW), `common/collectors/vpn.py` (NEW), `common/collectors/apigw.py` (NEW), `common/collectors/acm.py` (NEW), `common/collectors/backup.py` (NEW), `common/collectors/mq.py` (NEW), `common/collectors/clb.py` (NEW), `common/collectors/opensearch.py` (NEW), `common/alarm_builder.py`, `common/alarm_search.py`, `common/dimension_builder.py`, `common/tag_resolver.py`, `daily_monitor/lambda_handler.py`, `remediation_handler/lambda_handler.py`, `template.yaml`, `tests/test_collectors.py`, `tests/test_alarm_manager.py`, `tests/test_daily_monitor.py`, `tests/test_remediation_handler.py`, `tests/test_pbt_remaining_resource_alarm_defs.py` (NEW)

## Tasks

- [ ] 1. Alarm Registry 데이터 등록 — 8개 리소스 타입 알람 정의 일괄 추가
  - [ ] 1.1 Red: `tests/test_alarm_manager.py`에 8개 신규 리소스 타입 알람 정의 실패 테스트 작성
    - `_get_alarm_defs("Lambda")` → 2개 알람 (Duration, Errors), namespace `AWS/Lambda`, dimension_key `FunctionName`
    - `_get_alarm_defs("VPN")` → 1개 알람 (TunnelState), namespace `AWS/VPN`, dimension_key `VpnId`, `treat_missing_data="breaching"`
    - `_get_alarm_defs("APIGW", {"_api_type": "REST"})` → 3개 (ApiLatency, Api4XXError, Api5XXError), dimension_key `ApiName`
    - `_get_alarm_defs("APIGW", {"_api_type": "HTTP"})` → 3개 (ApiLatency, Api4xx, Api5xx), dimension_key `ApiId`
    - `_get_alarm_defs("APIGW", {"_api_type": "WEBSOCKET"})` → 4개 (WsConnectCount, WsMessageCount, WsIntegrationError, WsExecutionError), dimension_key `ApiId`
    - `_get_alarm_defs("ACM")` → 1개 (DaysToExpiry), namespace `AWS/CertificateManager`, dimension_key `CertificateArn`, comparison `LessThanThreshold`, period `86400`
    - `_get_alarm_defs("Backup")` → 2개 (BackupJobsFailed, BackupJobsAborted), namespace `AWS/Backup`, dimension_key `BackupVaultName`
    - `_get_alarm_defs("MQ")` → 4개 (MqCPU, HeapUsage, JobSchedulerStoreUsage, StoreUsage), namespace `AWS/AmazonMQ`, dimension_key `Broker`
    - `_get_alarm_defs("CLB")` → 7개 (CLBUnHealthyHost, CLB5XX, CLB4XX, CLBBackend5XX, CLBBackend4XX, SurgeQueueLength, SpilloverCount), namespace `AWS/ELB`, dimension_key `LoadBalancerName`
    - `_get_alarm_defs("OpenSearch")` → 8개 (ClusterStatusRed, ClusterStatusYellow, OSFreeStorageSpace, ClusterIndexWritesBlocked, OsCPU, JVMMemoryPressure, MasterCPU, MasterJVMMemoryPressure), namespace `AWS/ES`, dimension_key `DomainName`, `needs_client_id=True`
    - `_HARDCODED_METRIC_KEYS` 8개 타입 키 집합 검증
    - `_NAMESPACE_MAP` 8개 타입 네임스페이스 검증
    - `_DIMENSION_KEY_MAP` 8개 타입 디멘션 키 검증
    - `_METRIC_DISPLAY` 모든 신규 메트릭 매핑 존재 검증
    - `_metric_name_to_key()` 신규 매핑 round-trip 검증
    - 실행 → 실패 확인
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 3-B.5, 3-B.6, 3-C.10, 3-C.11, 3-D.15, 3-D.16, 4.1, 4.2, 5.1, 5.2, 6.1, 6.2, 7.1, 7.2, 8.1, 8.2, 9.1–9.8, 14.1–14.7_

  - [ ] 1.2 Green: `common/alarm_registry.py`에 8개 알람 정의 리스트 및 매핑 테이블 추가
    - `_LAMBDA_ALARMS` (2개: Duration, Errors)
    - `_VPN_ALARMS` (1개: TunnelState, `treat_missing_data="breaching"`)
    - `_APIGW_REST_ALARMS` (3개), `_APIGW_HTTP_ALARMS` (3개), `_APIGW_WEBSOCKET_ALARMS` (4개)
    - `_get_apigw_alarm_defs(resource_tags)` 함수 추가 (Aurora 패턴 준용)
    - `_ACM_ALARMS` (1개: DaysToExpiry, period=86400, comparison=LessThanThreshold)
    - `_BACKUP_ALARMS` (2개), `_MQ_ALARMS` (4개), `_CLB_ALARMS` (7개)
    - `_OPENSEARCH_ALARMS` (8개, `needs_client_id=True`)
    - `_get_alarm_defs()` 분기에 8개 타입 추가
    - `_HARDCODED_METRIC_KEYS`, `_NAMESPACE_MAP`, `_DIMENSION_KEY_MAP` 확장
    - `_METRIC_DISPLAY` 확장 (모든 신규 메트릭)
    - `_metric_name_to_key()` 매핑 확장
    - 실행 → 통과 확인
    - _Requirements: 9.1–9.8_

  - [ ] 1.3 Refactor: 알람 정의 정리 및 전체 테스트 재실행
    - VPN `treat_missing_data` 필드 확인, OpenSearch `needs_client_id` 플래그 확인
    - APIGW REST/HTTP/WS 메트릭 키 중복 없음 확인 (ApiLatency 공유는 의도적)
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 9.3, 9.8_

- [ ] 2. Common Constants 확장 — `common/__init__.py`
  - [ ] 2.1 Red: `tests/test_alarm_manager.py`에 상수 검증 실패 테스트 작성
    - `SUPPORTED_RESOURCE_TYPES`에 8개 신규 타입 포함 검증
    - `HARDCODED_DEFAULTS`에 모든 신규 메트릭 키 존재 + 값 검증 (Duration=2500, Errors=0, TunnelState=1, ApiLatency=3000, DaysToExpiry=14, MqCPU=90, OSFreeStorageSpace=20480 등)
    - `MONITORED_API_EVENTS` CREATE/DELETE/TAG_CHANGE에 신규 이벤트 포함 검증
    - 실행 → 실패 확인
    - _Requirements: 1.6, 1.7, 2.7, 2.8, 3-A.1, 3-F.23, 4.7, 4.8, 5.6, 5.7, 6.6, 6.7, 7.6, 7.7, 8.7, 8.8, 10.1_

  - [ ] 2.2 Green: `common/__init__.py` 상수 확장
    - `SUPPORTED_RESOURCE_TYPES`에 `"Lambda", "VPN", "APIGW", "ACM", "Backup", "MQ", "CLB", "OpenSearch"` 추가
    - `HARDCODED_DEFAULTS`에 모든 신규 메트릭 기본 임계치 추가
    - `MONITORED_API_EVENTS` CREATE/DELETE/TAG_CHANGE에 신규 이벤트 추가
    - 실행 → 통과 확인
    - _Requirements: 1.6, 1.7, 2.7, 2.8, 3-A.1, 3-F.23, 4.7, 4.8, 5.6, 5.7, 6.6, 6.7, 7.6, 7.7, 8.7, 8.8, 10.1_

- [ ] 3. Checkpoint — Alarm Registry + Constants 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Collectors 구현 — 8개 모듈 (common/collectors/)
  - [ ] 4.1 Red: `tests/test_collectors.py`에 Lambda Collector 실패 테스트 작성
    - `moto`로 Lambda mock 환경 구성, `Monitoring=on` 태그 함수 + 태그 없는 함수 생성
    - `collect_monitored_resources()` → `Monitoring=on` 함수만 수집, `type == "Lambda"` 검증
    - `get_metrics(function_name)` → `Duration`, `Errors` 키 반환 검증
    - 모든 메트릭 데이터 없을 때 `None` 반환 검증
    - 실행 → `ImportError`로 실패 확인
    - _Requirements: 1.3, 1.4_

  - [ ] 4.2 Green: `common/collectors/lambda_fn.py` 모듈 생성
    - `functools.lru_cache` 기반 `_get_lambda_client()` 싱글턴
    - `collect_monitored_resources()`: `list_functions()` paginator → `list_tags(Resource=arn)` → `Monitoring=on` 필터 → `ResourceInfo(type="Lambda", id=function_name)` 반환
    - `get_metrics(function_name, resource_tags=None)`: AWS/Lambda, FunctionName 디멘션, Duration(Average), Errors(Sum)
    - `base.py`의 `query_metric()` 사용, 데이터 없으면 skip + info 로그
    - 실행 → 통과 확인
    - _Requirements: 1.3, 1.4_

  - [ ] 4.3 Red: `tests/test_collectors.py`에 VPN Collector 실패 테스트 작성
    - `moto`로 VPN mock 환경 구성, `Monitoring=on` 태그 VPN + 태그 없는 VPN 생성
    - `collect_monitored_resources()` → `Monitoring=on` VPN만 수집, `type == "VPN"` 검증
    - `State == "deleted"` VPN skip 검증
    - `get_metrics(vpn_id)` → `TunnelState` 키 반환 검증
    - 실행 → `ImportError`로 실패 확인
    - _Requirements: 2.4, 2.5_

  - [ ] 4.4 Green: `common/collectors/vpn.py` 모듈 생성
    - `_get_ec2_client()` 싱글턴
    - `collect_monitored_resources()`: `describe_vpn_connections()` paginator → `Filter=[tag:Monitoring=on]` → deleted/deleting skip → `ResourceInfo(type="VPN", id=vpn_connection_id)` 반환
    - `get_metrics(vpn_id, resource_tags=None)`: AWS/VPN, VpnId 디멘션, TunnelState(Maximum)
    - 실행 → 통과 확인
    - _Requirements: 2.4, 2.5_

  - [ ] 4.5 Red: `tests/test_collectors.py`에 APIGW Collector 실패 테스트 작성
    - REST/HTTP/WebSocket 3가지 타입 혼합 수집 테스트
    - REST: `apigateway` mock, `Monitoring=on` 태그 → `_api_type="REST"`, `id=api_name` 검증
    - HTTP: `apigatewayv2` mock, `ProtocolType=HTTP`, `Monitoring=on` → `_api_type="HTTP"`, `id=api_id` 검증
    - WebSocket: `apigatewayv2` mock, `ProtocolType=WEBSOCKET`, `Monitoring=on` → `_api_type="WEBSOCKET"`, `id=api_id` 검증
    - `get_metrics()` _api_type별 디멘션 키/메트릭 이름 분기 검증
    - 실행 → `ImportError`로 실패 확인
    - _Requirements: 3-A.2, 3-B.7, 3-B.8, 3-C.12, 3-C.13, 3-D.17, 3-D.18, 3-E.20, 3-E.21, 3-E.22_

  - [ ] 4.6 Green: `common/collectors/apigw.py` 모듈 생성
    - `_get_apigw_client()`, `_get_apigwv2_client()` 싱글턴
    - `collect_monitored_resources()`: REST(`get_rest_apis` + `get_tags`) + HTTP/WS(`get_apis` + Tags 필드) 수집, `_api_type` Internal_Tag 설정
    - REST API 실패 시 REST skip, HTTP/WS 계속 (반대도 동일)
    - `get_metrics(resource_id, resource_tags=None)`: `_api_type`에 따라 디멘션 키(ApiName/ApiId)와 메트릭 이름 분기
    - 실행 → 통과 확인
    - _Requirements: 3-B.9, 3-C.14, 3-D.19, 3-E.20, 3-E.21, 3-E.22_

  - [ ] 4.7 Red: `tests/test_collectors.py`에 ACM Collector 실패 테스트 작성
    - `moto`로 ACM mock, ISSUED/PENDING/EXPIRED 인증서 혼합 생성
    - `collect_monitored_resources()` → ISSUED만 수집, 태그 무관 (Full_Collection) 검증
    - 반환된 ResourceInfo의 `tags["Monitoring"] == "on"` 자동 삽입 검증
    - `get_metrics(certificate_arn)` → `DaysToExpiry` 키 반환 검증
    - 실행 → `ImportError`로 실패 확인
    - _Requirements: 4.3, 4.4, 4.5, 4.9, 13.1, 13.2, 13.3_

  - [ ] 4.8 Green: `common/collectors/acm.py` 모듈 생성
    - `_get_acm_client()` 싱글턴
    - `collect_monitored_resources()`: `list_certificates(CertificateStatuses=["ISSUED"])` paginator → 전체 수집 → `tags["Monitoring"] = "on"` 자동 삽입 → `ResourceInfo(type="ACM", id=certificate_arn)` 반환
    - `get_metrics(certificate_arn, resource_tags=None)`: AWS/CertificateManager, CertificateArn 디멘션, DaysToExpiry(Minimum)
    - 실행 → 통과 확인
    - _Requirements: 4.3, 4.4, 4.5, 4.9, 13.1, 13.2, 13.3, 13.4_

  - [ ] 4.9 Red: `tests/test_collectors.py`에 Backup Collector 실패 테스트 작성
    - `moto`로 Backup mock, `Monitoring=on` 태그 vault + 태그 없는 vault 생성
    - `collect_monitored_resources()` → `Monitoring=on` vault만 수집, `type == "Backup"` 검증
    - `get_metrics(vault_name)` → `BackupJobsFailed`, `BackupJobsAborted` 키 반환 검증
    - 실행 → `ImportError`로 실패 확인
    - _Requirements: 5.3, 5.4_

  - [ ] 4.10 Green: `common/collectors/backup.py` 모듈 생성
    - `_get_backup_client()` 싱글턴
    - `collect_monitored_resources()`: `list_backup_vaults()` paginator → `list_tags(ResourceArn=vault_arn)` → `Monitoring=on` 필터 → `ResourceInfo(type="Backup", id=vault_name)` 반환
    - `get_metrics(vault_name, resource_tags=None)`: AWS/Backup, BackupVaultName 디멘션, NumberOfBackupJobsFailed(Sum), NumberOfBackupJobsAborted(Sum)
    - 실행 → 통과 확인
    - _Requirements: 5.3, 5.4_

  - [ ] 4.11 Red: `tests/test_collectors.py`에 MQ Collector 실패 테스트 작성
    - `moto`로 MQ mock, `Monitoring=on` 태그 broker + 태그 없는 broker 생성
    - `collect_monitored_resources()` → `Monitoring=on` broker만 수집, `type == "MQ"` 검증
    - `get_metrics(broker_name)` → `MqCPU`, `HeapUsage`, `JobSchedulerStoreUsage`, `StoreUsage` 키 반환 검증
    - 실행 → `ImportError`로 실패 확인
    - _Requirements: 6.3, 6.4_

  - [ ] 4.12 Green: `common/collectors/mq.py` 모듈 생성
    - `_get_mq_client()` 싱글턴
    - `collect_monitored_resources()`: `list_brokers()` paginator → `describe_broker(BrokerId)` 태그 조회 → `Monitoring=on` 필터 → `ResourceInfo(type="MQ", id=broker_name)` 반환
    - `get_metrics(broker_name, resource_tags=None)`: AWS/AmazonMQ, Broker 디멘션, CpuUtilization(Average)→MqCPU, HeapUsage(Average), JobSchedulerStorePercentUsage(Average)→JobSchedulerStoreUsage, StorePercentUsage(Average)→StoreUsage
    - 실행 → 통과 확인
    - _Requirements: 6.3, 6.4_

  - [ ] 4.13 Red: `tests/test_collectors.py`에 CLB Collector 실패 테스트 작성
    - `moto`로 ELB Classic mock, `Monitoring=on` 태그 CLB + 태그 없는 CLB 생성
    - `collect_monitored_resources()` → `Monitoring=on` CLB만 수집, `type == "CLB"` 검증
    - `get_metrics(lb_name)` → 7개 메트릭 키 반환 검증
    - 실행 → `ImportError`로 실패 확인
    - _Requirements: 7.3, 7.4_

  - [ ] 4.14 Green: `common/collectors/clb.py` 모듈 생성
    - `_get_elb_client()` 싱글턴 (`boto3.client("elb")`)
    - `collect_monitored_resources()`: `describe_load_balancers()` paginator → `describe_tags(LoadBalancerNames=[name])` → `Monitoring=on` 필터 → `ResourceInfo(type="CLB", id=lb_name)` 반환
    - `get_metrics(lb_name, resource_tags=None)`: AWS/ELB, LoadBalancerName 디멘션, 7개 메트릭 조회
    - 실행 → 통과 확인
    - _Requirements: 7.3, 7.4_

  - [ ] 4.15 Red: `tests/test_collectors.py`에 OpenSearch Collector 실패 테스트 작성
    - `moto`로 OpenSearch mock, `Monitoring=on` 태그 도메인 + 태그 없는 도메인 생성
    - `collect_monitored_resources()` → `Monitoring=on` 도메인만 수집, `type == "OpenSearch"` 검증
    - `_client_id` Internal_Tag 설정 검증 (AWS 계정 ID)
    - `get_metrics(domain_name, resource_tags)` → 8개 메트릭 키 반환 검증
    - Compound_Dimension: DomainName + ClientId 2개 디멘션 사용 검증
    - 실행 → `ImportError`로 실패 확인
    - _Requirements: 8.3, 8.4, 8.5_

  - [ ] 4.16 Green: `common/collectors/opensearch.py` 모듈 생성
    - `_get_opensearch_client()`, `_get_sts_client()` 싱글턴
    - `collect_monitored_resources()`: `list_domain_names()` → `describe_domains()` → `list_tags(ARN)` → `Monitoring=on` 필터 → `_client_id` Internal_Tag (STS `get_caller_identity` 또는 ARN 파싱) → `ResourceInfo(type="OpenSearch", id=domain_name)` 반환
    - `get_metrics(domain_name, resource_tags=None)`: AWS/ES, DomainName + ClientId Compound_Dimension, 8개 메트릭 조회
    - OpenSearch `CPUUtilization` → `OsCPU` 키로 직접 반환 (기존 `CPU` 매핑 충돌 회피)
    - 실행 → 통과 확인
    - _Requirements: 8.3, 8.4, 8.5_

  - [ ] 4.17 Refactor: 8개 Collector 코드 정리 및 전체 테스트 재실행
    - 공통 패턴 (`_collect_metric` 헬퍼) 중복 확인 및 정리
    - 로깅 메시지에 resource_id 컨텍스트 포함 확인
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 1.3, 1.4, 2.4, 2.5, 3-E.20–22, 4.3–4.5, 5.3, 5.4, 6.3, 6.4, 7.3, 7.4, 8.3–8.5_

- [ ] 5. Checkpoint — 8개 Collector 구현 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. CloudTrail 이벤트 + Remediation Handler — `remediation_handler/lambda_handler.py`
  - [ ] 6.1 Red: `tests/test_remediation_handler.py`에 8개 신규 리소스 이벤트 실패 테스트 작성
    - `_API_MAP`에 신규 이벤트 매핑 존재 검증: CreateFunction20150331, DeleteFunction20150331, DeleteVpnConnection, CreateRestApi, DeleteRestApi, CreateApi, DeleteApi, DeleteCertificate, CreateBackupVault, DeleteBackupVault, CreateBroker, DeleteBroker, CreateDomain, DeleteDomain, TagResource, UntagResource
    - 각 이벤트별 `(resource_type, id_extractor)` 매핑 검증
    - TagResource/UntagResource ARN 기반 서비스 판별 로직 검증 (Lambda ARN → "Lambda", APIGW ARN → "APIGW" 등)
    - ID 추출 실패 시 에러 로깅 + 이벤트 skip 검증
    - 실행 → 실패 확인
    - _Requirements: 10.1, 10.2, 10.4_

  - [ ] 6.2 Green: Remediation Handler에 8개 신규 리소스 이벤트 매핑 추가
    - `_API_MAP`에 Lambda/VPN/APIGW/ACM/Backup/MQ/OpenSearch 이벤트 매핑 추가
    - 각 리소스별 `_extract_*_ids()` ID 추출 함수 구현
    - `TagResource`/`UntagResource`: `"MULTI"` 타입 + ARN 기반 서비스 판별 함수 구현
    - CLB는 기존 ELB 이벤트(`CreateLoadBalancer`/`DeleteLoadBalancer`)와 source로 구분
    - VPN은 기존 EC2 태그 API(`CreateTags`/`DeleteTags`)로 커버
    - 실행 → 통과 확인
    - _Requirements: 10.1, 10.2, 10.4_

  - [ ] 6.3 Refactor: Remediation Handler 정리 및 전체 테스트 재실행
    - ID 추출 함수 네이밍 일관성 확인
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 10.2_

- [ ] 7. Tag Resolver 확장 — `common/tag_resolver.py`
  - [ ] 7.1 Red: `tests/test_collectors.py`에 8개 신규 리소스 태그 조회 실패 테스트 작성
    - `get_resource_tags(resource_id, "Lambda")` → Lambda 태그 반환 검증
    - `get_resource_tags(resource_id, "VPN")` → EC2 태그 경로 사용 검증
    - `get_resource_tags(resource_id, "APIGW")` → APIGW 태그 반환 검증
    - `get_resource_tags(resource_id, "ACM")` → ACM 태그 반환 검증
    - `get_resource_tags(resource_id, "Backup")` → Backup 태그 반환 검증
    - `get_resource_tags(resource_id, "MQ")` → MQ 태그 반환 검증
    - `get_resource_tags(resource_id, "CLB")` → CLB 태그 반환 검증
    - `get_resource_tags(resource_id, "OpenSearch")` → OpenSearch 태그 반환 검증
    - 실행 → 미지원 타입으로 빈 dict 반환 확인
    - _Requirements: 1.3, 2.4, 3-B.7, 4.3, 5.3, 6.3, 7.3, 8.3_

  - [ ] 7.2 Green: `common/tag_resolver.py`의 `get_resource_tags()`에 8개 신규 타입 분기 추가
    - Lambda: `lambda` 클라이언트 `list_tags(Resource=arn)`
    - VPN: `ec2` 클라이언트 `describe_vpn_connections` → Tags
    - APIGW: `_api_type`에 따라 `apigateway`/`apigatewayv2` 태그 조회
    - ACM: `acm` 클라이언트 `list_tags_for_certificate`
    - Backup: `backup` 클라이언트 `list_tags`
    - MQ: `mq` 클라이언트 `describe_broker` → Tags
    - CLB: `elb` 클라이언트 `describe_tags`
    - OpenSearch: `opensearch` 클라이언트 `list_tags`
    - 실행 → 통과 확인
    - _Requirements: 1.3, 2.4, 3-B.7, 4.3, 5.3, 6.3, 7.3, 8.3_

- [ ] 8. Checkpoint — CloudTrail + Tag Resolver 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Daily Monitor 통합 — `daily_monitor/lambda_handler.py`
  - [ ] 9.1 Red: `tests/test_daily_monitor.py`에 8개 신규 Collector 통합 실패 테스트 작성
    - `_COLLECTOR_MODULES`에 8개 신규 모듈 포함 검증
    - `alive_checkers`에 8개 신규 타입 키 존재 + callable 검증
    - "낮을수록 위험" 메트릭 세트에 `TunnelState`, `DaysToExpiry`, `OSFreeStorageSpace` 추가 검증
    - 실행 → 실패 확인
    - _Requirements: 1.5, 2.6, 3-A.4, 4.6, 5.5, 6.5, 7.5, 8.6, 12.1, 12.3_

  - [ ] 9.2 Green: Daily Monitor에 8개 신규 Collector 등록
    - 8개 import 추가: `lambda_fn`, `vpn`, `apigw`, `acm`, `backup`, `mq`, `clb`, `opensearch`
    - `_COLLECTOR_MODULES`에 8개 모듈 추가
    - `alive_checkers`에 8개 타입별 `_find_alive_*` 함수 등록
    - 8개 `_find_alive_*` 함수 구현 (각 리소스 타입별 존재 확인 API 호출)
    - `_process_resource()` "낮을수록 위험" 메트릭 세트에 `TunnelState`, `DaysToExpiry`, `OSFreeStorageSpace` 추가
    - 실행 → 통과 확인
    - _Requirements: 1.5, 2.6, 3-A.4, 4.6, 5.5, 6.5, 7.5, 8.6, 12.1, 12.3_

  - [ ] 9.3 Refactor: Daily Monitor 정리 및 전체 테스트 재실행
    - `_find_alive_*` 함수 패턴 일관성 확인
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 12.2_

- [ ] 10. Checkpoint — Daily Monitor 통합 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. template.yaml IAM + EventBridge 확장
  - [ ] 11.1 Red: `template.yaml` 변경 사항 검증 테스트 작성 (수동 검증 또는 CFN lint)
    - Daily Monitor Role에 8개 신규 리소스 Describe/List/Tags API 권한 추가 필요 확인
    - Remediation Handler Role에 8개 신규 리소스 생명주기 API 권한 추가 필요 확인
    - CloudTrailModifyRule EventPattern에 신규 source + eventName 추가 필요 확인
    - _Requirements: 10.3, 11.1, 11.2, 11.3_

  - [ ] 11.2 Green: `template.yaml` IAM 및 EventBridge 확장
    - Daily Monitor Role 추가 권한: `lambda:ListFunctions`, `lambda:ListTags`, `ec2:DescribeVpnConnections`, `apigateway:GET`, `apigateway:GetRestApis`, `apigateway:GetTags`, `apigatewayv2:GetApis`, `apigatewayv2:GetTags`, `acm:ListCertificates`, `acm:ListTagsForCertificate`, `backup:ListBackupVaults`, `backup:ListTags`, `mq:ListBrokers`, `mq:DescribeBroker`, `es:ListDomainNames`, `es:DescribeDomains`, `es:ListTags`, `sts:GetCallerIdentity`
    - Remediation Handler Role 추가 권한: `lambda:ListTags`, `lambda:GetFunction`, `ec2:DescribeVpnConnections`, `apigateway:GET`, `apigatewayv2:GetApis`, `acm:ListTagsForCertificate`, `backup:ListTags`, `mq:DescribeBroker`, `es:DescribeDomains`, `es:ListTags`
    - CloudTrailModifyRule EventPattern source에 `aws.lambda`, `aws.apigateway`, `aws.acm`, `aws.backup`, `aws.amazonmq`, `aws.es` 추가
    - CloudTrailModifyRule EventPattern eventName에 신규 16개 이벤트 추가
    - CLB는 기존 `elasticloadbalancing` source/권한으로 커버, VPN은 기존 `ec2` source로 커버
    - 실행 → 통과 확인
    - _Requirements: 10.3, 11.1, 11.2, 11.3_

- [ ] 12. Checkpoint — template.yaml 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. Alarm Manager 확장 — `treat_missing_data` + OpenSearch Compound Dimension
  - [ ] 13.1 Red: `tests/test_alarm_manager.py`에 treat_missing_data 및 OpenSearch 디멘션 실패 테스트 작성
    - VPN 알람 생성 시 `put_metric_alarm`의 `TreatMissingData` 파라미터가 `"breaching"`인지 검증
    - 기존 리소스 알람 생성 시 `TreatMissingData`가 `"missing"` (기본값)인지 검증
    - OpenSearch 알람 생성 시 `_build_dimensions()`가 `DomainName` + `ClientId` 2개 디멘션 반환 검증
    - `_client_id` 누락 시 `ClientId` 디멘션 없이 1개만 반환 검증
    - 실행 → 실패 확인
    - _Requirements: 2.3, 8.2, 8.5_

  - [ ] 13.2 Green: `common/alarm_builder.py` treat_missing_data 지원 + `common/dimension_builder.py` OpenSearch 분기 추가
    - `_create_standard_alarm()`: `alarm_def.get("treat_missing_data", "missing")`을 `TreatMissingData` 파라미터로 전달
    - `_create_single_alarm()`: 동일하게 `treat_missing_data` 지원 추가
    - `_recreate_standard_alarm()`: 동일하게 `treat_missing_data` 지원 추가
    - `_build_dimensions()`: `resource_type == "OpenSearch"` 분기 추가 → `DomainName` + `ClientId` (resource_tags `_client_id`에서 조회) Compound_Dimension 구성
    - 실행 → 통과 확인
    - _Requirements: 2.3, 8.2, 8.5_

  - [ ] 13.3 Refactor: Alarm Builder/Dimension Builder 정리 및 전체 테스트 재실행
    - 기존 알람의 `TreatMissingData="missing"` 동작 변경 없음 확인
    - 전체 테스트 재실행하여 회귀 없음 확인
    - _Requirements: 2.3, 8.2_

- [ ] 14. Alarm Search 확장 — 신규 리소스 타입 접두사
  - [ ] 14.1 Red: `tests/test_alarm_manager.py`에 신규 타입 알람 검색 실패 테스트 작성
    - `_find_alarms_for_resource(resource_id)` (resource_type 미지정) 호출 시 기본 폴백 목록에 8개 신규 타입 포함 검증
    - `_find_alarms_for_resource(resource_id, "Lambda")` → `"[Lambda] "` 접두사 검색 검증
    - 8개 신규 타입 각각에 대해 `"[{type}] "` 접두사 검색 검증
    - 실행 → 실패 확인
    - _Requirements: 12.2_

  - [ ] 14.2 Green: `common/alarm_search.py`의 `_find_alarms_for_resource()` 기본 폴백 목록에 8개 신규 타입 추가
    - 기본 `type_prefixes` 폴백 리스트에 `"Lambda", "VPN", "APIGW", "ACM", "Backup", "MQ", "CLB", "OpenSearch"` 추가
    - 실행 → 통과 확인
    - _Requirements: 12.2_

- [ ] 15. Checkpoint — Alarm Manager + Search 확장 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 16. PBT — 설계 문서 Correctness Properties 10개
  - [ ]* 16.1 PBT Property 1: Alarm Definition Structural Correctness
    - **Property 1: Alarm Definition Structural Correctness**
    - **Validates: Requirements 1.1, 1.2, 2.1, 2.2, 3-B.5, 3-B.6, 3-C.10, 3-C.11, 3-D.15, 3-D.16, 4.1, 4.2, 5.1, 5.2, 6.1, 6.2, 7.1, 7.2, 8.1, 8.2, 9.1, 9.2, 14.1–14.7**
    - 파일: `tests/test_pbt_remaining_resource_alarm_defs.py`
    - 8개 신규 resource_type 중 랜덤 선택 + 랜덤 resource_tags 생성
    - `_get_alarm_defs(resource_type, resource_tags)` 반환값이 non-empty이고 모든 정의가 올바른 namespace, dimension_key, metric set, comparison direction을 갖는지 검증

  - [ ]* 16.2 PBT Property 2: Registry Mapping Table Completeness
    - **Property 2: Registry Mapping Table Completeness**
    - **Validates: Requirements 9.4, 9.5, 9.6, 9.7, 9.8, 1.7, 2.8, 3-F.23, 4.8, 5.7, 6.7, 7.7, 8.8**
    - 파일: `tests/test_pbt_remaining_resource_alarm_defs.py`
    - 8개 신규 타입의 모든 alarm_def에 대해 `_HARDCODED_METRIC_KEYS`, `_NAMESPACE_MAP`, `_DIMENSION_KEY_MAP`, `_METRIC_DISPLAY`, `HARDCODED_DEFAULTS` 매핑 존재 검증

  - [ ]* 16.3 PBT Property 3: Tag-Based Collector Filtering (Monitoring=on)
    - **Property 3: Tag-Based Collector Filtering (Monitoring=on)**
    - **Validates: Requirements 1.3, 2.4, 5.3, 6.3, 7.3, 8.3**
    - 파일: `tests/test_pbt_remaining_resource_alarm_defs.py`
    - 랜덤 리소스 집합 (Monitoring=on/off 혼합) 생성 → moto mock → 6개 tag-based collector (Lambda, VPN, Backup, MQ, CLB, OpenSearch)가 정확히 Monitoring=on 리소스만 반환하는지 검증

  - [ ]* 16.4 PBT Property 4: ACM Full_Collection with Auto-Injected Tag
    - **Property 4: ACM Full_Collection with Auto-Injected Tag**
    - **Validates: Requirements 4.3, 4.4, 4.9, 13.1, 13.2, 13.3**
    - 파일: `tests/test_pbt_remaining_resource_alarm_defs.py`
    - 랜덤 ACM 인증서 집합 (ISSUED/PENDING/EXPIRED 혼합, 태그 유무 혼합) 생성 → ACM collector가 ISSUED만 반환하고 모두 `Monitoring=on` 태그 포함 검증

  - [ ]* 16.5 PBT Property 5: APIGW _api_type Routing Correctness
    - **Property 5: APIGW _api_type Routing Correctness**
    - **Validates: Requirements 3-A.2, 3-A.3, 3-B.5, 3-B.6, 3-B.8, 3-C.10, 3-C.11, 3-C.13, 3-D.15, 3-D.16, 3-D.18, 3-E.22, 9.3**
    - 파일: `tests/test_pbt_remaining_resource_alarm_defs.py`
    - `_api_type` 값 `{"REST", "HTTP", "WEBSOCKET"}` 중 랜덤 선택 → `_get_apigw_alarm_defs()` 반환값의 dimension_key와 metric set 검증

  - [ ]* 16.6 PBT Property 6: OpenSearch Compound Dimension Construction
    - **Property 6: OpenSearch Compound Dimension Construction**
    - **Validates: Requirements 8.2, 8.5**
    - 파일: `tests/test_pbt_remaining_resource_alarm_defs.py`
    - 랜덤 domain_name + 랜덤 12자리 account_id → `_build_dimensions()` 호출 → DomainName + ClientId 2개 디멘션 포함 검증

  - [ ]* 16.7 PBT Property 7: VPN treat_missing_data=breaching
    - **Property 7: VPN treat_missing_data=breaching**
    - **Validates: Requirements 2.3**
    - 파일: `tests/test_pbt_remaining_resource_alarm_defs.py`
    - `_VPN_ALARMS` 모든 정의에 `treat_missing_data="breaching"` 존재 검증
    - 다른 7개 타입 알람 정의에는 `treat_missing_data` 없거나 `"missing"` 검증

  - [ ]* 16.8 PBT Property 8: Alive Checker Coverage
    - **Property 8: Alive Checker Coverage**
    - **Validates: Requirements 12.1**
    - 파일: `tests/test_pbt_remaining_resource_alarm_defs.py`
    - 8개 신규 resource_type에 대해 `alive_checkers` dict에 해당 키 존재 + callable 검증

  - [ ]* 16.9 PBT Property 9: metric_name_to_key Round Trip
    - **Property 9: metric_name_to_key Round Trip**
    - **Validates: Requirements 9.8**
    - 파일: `tests/test_pbt_remaining_resource_alarm_defs.py`
    - 8개 신규 타입의 모든 alarm_def에 대해 `_metric_name_to_key(alarm_def["metric_name"]) == alarm_def["metric"]` round-trip 검증

  - [ ]* 16.10 PBT Property 10: HARDCODED_DEFAULTS Threshold Direction Consistency
    - **Property 10: HARDCODED_DEFAULTS Threshold Direction Consistency**
    - **Validates: Requirements 1.7, 2.8, 4.8, 8.8**
    - 파일: `tests/test_pbt_remaining_resource_alarm_defs.py`
    - LessThanThreshold 메트릭 (TunnelState, DaysToExpiry, OSFreeStorageSpace)에 대해 랜덤 current_value와 threshold 생성 → 비교 방향 올바른지 검증

- [ ] 17. Final checkpoint — 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- `*` 표시된 태스크는 선택적이며 빠른 MVP를 위해 건너뛸 수 있음
- 각 태스크는 특정 요구사항을 참조하여 추적 가능
- TDD 레드-그린-리팩터링 사이클을 모듈별로 반복
- PBT 테스트는 설계 문서의 Correctness Properties 10개를 모두 커버
- OpenSearch `CPUUtilization` → `OsCPU` 키로 직접 반환하여 기존 `CPU` 매핑 충돌 회피
- MQ `CpuUtilization`(소문자 p)과 EC2/RDS `CPUUtilization`(대문자 P)은 대소문자 구분으로 충돌 없음
- APIGW는 단일 모듈에서 REST/HTTP/WebSocket 3가지 타입을 수집하며, `_api_type` Internal_Tag로 분기
- ACM은 유일하게 Full_Collection (태그 필터 없이 전체 ISSUED 인증서 수집)
- VPN은 유일하게 `treat_missing_data=breaching` 설정 (Miss_Data_Alarm)
- CLB/VPN은 기존 CloudTrail 이벤트/IAM 권한과 일부 공유
