# Requirements Document

## Introduction

DocumentDB(DocDB)를 새로운 모니터링 리소스 타입("DocDB")으로 AWS Monitoring Engine에 추가한다. DocumentDB는 MongoDB 호환 문서 데이터베이스로, Aurora RDS와 유사한 클러스터/인스턴스 구조를 가진다. CloudWatch 네임스페이스는 `AWS/DocDB`를 사용하며, 디멘션은 인스턴스 레벨(`DBInstanceIdentifier`)과 클러스터 레벨(`DBClusterIdentifier`)로 구분된다. 기존 RDS/Aurora 모니터링 패턴을 재사용하되, DocDB 전용 네임스페이스와 메트릭을 반영한다.

### SRE 골든 시그널 기반 메트릭 선정 (§11-7)

| 시그널 | 하드코딩 메트릭 | 판단 근거 |
|--------|---------------|----------|
| Latency | ReadLatency, WriteLatency | 쿼리 응답 시간 직결, 사용자 체감 영향 |
| Traffic | - | DocumentDB는 RequestCount 등 트래픽 메트릭이 제한적, OpcountersQuery 등은 워크로드별 차이가 커서 동적 알람 후보 |
| Errors | - | DatabaseConnectionsAttempts 등은 워크로드별 차이가 커서 동적 알람 후보 |
| Saturation | CPUUtilization, FreeableMemory, FreeLocalStorage, DatabaseConnections | 리소스 포화도 직결 메트릭 |

### 인스턴스 변형별 메트릭 가용성 (§11-8)

| 메트릭 | Provisioned | Elastic Cluster | 비고 |
|--------|------------|-----------------|------|
| CPUUtilization | ✅ | ✅ | 공통 |
| FreeableMemory | ✅ | ✅ | 공통 |
| FreeLocalStorage | ✅ | ✅ | 공통 |
| DatabaseConnections | ✅ | ✅ | 공통 |
| ReadLatency | ✅ | ✅ | 공통 |
| WriteLatency | ✅ | ✅ | 공통 |

## Glossary

- **Monitoring_Engine**: Daily Monitor와 Remediation Handler Lambda로 구성된 AWS Monitoring Engine 시스템
- **DocDB_Collector**: DocumentDB 인스턴스를 수집하는 새 Collector 모듈 (`common/collectors/docdb.py`)
- **Alarm_Manager**: CloudWatch 알람 CRUD, 동기화, 정의를 담당하는 `common/alarm_manager.py` 모듈
- **Daily_Monitor**: 매일 실행되어 리소스 스캔, 알람 동기화, 메트릭 점검을 수행하는 Lambda 함수
- **Remediation_Handler**: CloudTrail 생명주기 이벤트에 실시간 반응하는 Lambda 함수
- **HARDCODED_DEFAULTS**: `common/__init__.py`의 폴백 임계치 딕셔너리
- **SUPPORTED_RESOURCE_TYPES**: `common/__init__.py`의 지원 리소스 타입 목록
- **DocDB**: 새 리소스 타입 식별자 문자열. 알람 이름, 알람 정의, 리소스 분류에 사용
- **DBInstanceIdentifier**: DocumentDB 인스턴스 레벨 CloudWatch 디멘션 키

## Requirements

### Requirement 1: DocumentDB Collector 구현

**User Story:** As a 모니터링 운영자, I want Monitoring=on 태그가 있는 DocumentDB 인스턴스를 자동으로 수집하고 싶다, so that DocumentDB 리소스가 모니터링 대상에 포함된다.

#### Acceptance Criteria

1. THE DocDB_Collector SHALL `describe_db_instances` API를 호출하여 Engine 필드가 "docdb"인 인스턴스를 수집한다
2. WHEN DocumentDB 인스턴스에 `Monitoring=on` 태그(대소문자 무관)가 있으면, THE DocDB_Collector SHALL 해당 인스턴스를 리소스 목록에 type "DocDB"로 포함한다
3. WHEN DocumentDB 인스턴스의 상태가 "deleting" 또는 "deleted"이면, THE DocDB_Collector SHALL 해당 인스턴스를 건너뛰고 스킵 사유를 로그에 기록한다
4. THE DocDB_Collector SHALL `common/collectors/base.py`의 `CollectorProtocol`을 구현하여 `collect_monitored_resources()`와 `get_metrics()` 메서드를 제공한다
5. THE DocDB_Collector SHALL Engine 필드가 정확히 "docdb"인 인스턴스만 수집하고, "aurora" 등 다른 엔진은 제외한다

### Requirement 2: DocumentDB 메트릭 수집

**User Story:** As a 모니터링 운영자, I want DocumentDB 인스턴스의 CloudWatch 메트릭을 수집하고 싶다, so that 임계치 비교에 올바른 데이터를 사용할 수 있다.

#### Acceptance Criteria

1. WHEN DocDB 인스턴스의 메트릭을 수집할 때, THE DocDB_Collector SHALL 네임스페이스 "AWS/DocDB"에서 디멘션 "DBInstanceIdentifier"로 다음 메트릭을 조회한다: CPUUtilization, FreeableMemory, FreeLocalStorage, DatabaseConnections, ReadLatency, WriteLatency
2. WHEN FreeableMemory 메트릭 값을 조회하면, THE DocDB_Collector SHALL bytes에서 GB로 변환하여 키 "FreeMemoryGB"로 반환한다
3. WHEN FreeLocalStorage 메트릭 값을 조회하면, THE DocDB_Collector SHALL bytes에서 GB로 변환하여 키 "FreeLocalStorageGB"로 반환한다
4. WHEN CPUUtilization 메트릭 값을 조회하면, THE DocDB_Collector SHALL 키 "CPU"로 반환한다
5. WHEN DatabaseConnections 메트릭 값을 조회하면, THE DocDB_Collector SHALL 키 "Connections"로 반환한다
6. WHEN ReadLatency 메트릭 값을 조회하면, THE DocDB_Collector SHALL 원시 값(초 단위)을 키 "ReadLatency"로 반환한다
7. WHEN WriteLatency 메트릭 값을 조회하면, THE DocDB_Collector SHALL 원시 값(초 단위)을 키 "WriteLatency"로 반환한다
8. IF 개별 메트릭에 데이터가 없으면, THEN THE DocDB_Collector SHALL 해당 메트릭을 건너뛰고 info 레벨로 로그를 기록한다
9. IF 모든 메트릭에 데이터가 없으면, THEN THE DocDB_Collector SHALL None을 반환한다

### Requirement 3: DocumentDB 알람 정의

**User Story:** As a 모니터링 운영자, I want DocumentDB 인스턴스에 기본 알람이 자동 생성되길 원한다, so that 올바른 메트릭과 임계치로 모니터링된다.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL 다음 메트릭에 대한 알람 정의를 포함하는 `_DOCDB_ALARMS` 목록을 정의한다: CPUUtilization, FreeableMemory, FreeLocalStorage, DatabaseConnections, ReadLatency, WriteLatency
2. WHEN 리소스 타입이 "DocDB"이면, THE Alarm_Manager SHALL `_get_alarm_defs()`에서 `_DOCDB_ALARMS` 정의를 반환한다
3. THE Alarm_Manager SHALL CPUUtilization 알람을 네임스페이스 "AWS/DocDB", 디멘션 키 "DBInstanceIdentifier", 비교 "GreaterThanThreshold", 통계 "Average"로 구성한다
4. THE Alarm_Manager SHALL FreeableMemory 알람을 네임스페이스 "AWS/DocDB", 디멘션 키 "DBInstanceIdentifier", 비교 "LessThanThreshold", GB에서 bytes로 변환하는 `transform_threshold`(승수 1073741824), 통계 "Average"로 구성한다
5. THE Alarm_Manager SHALL FreeLocalStorage 알람을 네임스페이스 "AWS/DocDB", 디멘션 키 "DBInstanceIdentifier", 비교 "LessThanThreshold", GB에서 bytes로 변환하는 `transform_threshold`(승수 1073741824), 통계 "Average"로 구성한다
6. THE Alarm_Manager SHALL DatabaseConnections 알람을 네임스페이스 "AWS/DocDB", 디멘션 키 "DBInstanceIdentifier", 비교 "GreaterThanThreshold", 통계 "Average"로 구성한다
7. THE Alarm_Manager SHALL ReadLatency 알람을 네임스페이스 "AWS/DocDB", 디멘션 키 "DBInstanceIdentifier", 비교 "GreaterThanThreshold", 통계 "Average"로 구성한다
8. THE Alarm_Manager SHALL WriteLatency 알람을 네임스페이스 "AWS/DocDB", 디멘션 키 "DBInstanceIdentifier", 비교 "GreaterThanThreshold", 통계 "Average"로 구성한다

### Requirement 4: HARDCODED_DEFAULTS 및 SUPPORTED_RESOURCE_TYPES 등록

**User Story:** As a 모니터링 운영자, I want DocumentDB 메트릭에 합리적인 폴백 임계치가 있길 원한다, so that 태그 오버라이드 없이도 올바른 기본값으로 알람이 생성된다.

#### Acceptance Criteria

1. THE Monitoring_Engine SHALL `SUPPORTED_RESOURCE_TYPES` 목록에 "DocDB"를 포함한다
2. THE Monitoring_Engine SHALL 공유 메트릭의 기존 `HARDCODED_DEFAULTS` 항목을 재사용한다: "CPU" (80.0), "FreeMemoryGB" (2.0), "FreeLocalStorageGB" (10.0), "Connections" (100.0), "ReadLatency" (0.02), "WriteLatency" (0.02)

### Requirement 5: 알람 이름 및 메타데이터 표시

**User Story:** As a 모니터링 운영자, I want DocumentDB 알람이 일반 RDS 알람과 명확히 구분되길 원한다, so that 리소스 타입을 한눈에 식별할 수 있다.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL DocumentDB 인스턴스의 알람 이름에 리소스 타입 접두사 "[DocDB]"를 사용한다
2. THE Alarm_Manager SHALL AlarmDescription JSON 메타데이터에 `"resource_type": "DocDB"`를 포함한다
3. THE Alarm_Manager SHALL `_build_dimensions()`에서 리소스 타입 "DocDB"에 대해 디멘션 키 "DBInstanceIdentifier"를 사용하여 RDS와 동일한 디멘션 구조를 생성한다

### Requirement 6: Alarm Manager 매핑 테이블 등록

**User Story:** As a 개발자, I want DocumentDB 관련 매핑이 alarm_manager의 모든 조회 테이블에 등록되길 원한다, so that 동적 알람과 알람 검색이 올바르게 동작한다.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL `_HARDCODED_METRIC_KEYS`에 "DocDB" 항목을 등록한다: {"CPU", "FreeMemoryGB", "FreeLocalStorageGB", "Connections", "ReadLatency", "WriteLatency"}
2. THE Alarm_Manager SHALL `_NAMESPACE_MAP`에 "DocDB" 항목을 등록한다: ["AWS/DocDB"]
3. THE Alarm_Manager SHALL `_DIMENSION_KEY_MAP`에 "DocDB" 항목을 등록한다: "DBInstanceIdentifier"
4. THE Alarm_Manager SHALL `_find_alarms_for_resource()`의 기본 type_prefixes 폴백 목록에 "DocDB"를 포함한다

### Requirement 7: Daily Monitor 통합

**User Story:** As a 모니터링 운영자, I want Daily Monitor가 DocumentDB 인스턴스를 다른 리소스 타입과 함께 처리하길 원한다, so that 알람이 동기화되고 메트릭이 매일 점검된다.

#### Acceptance Criteria

1. THE Daily_Monitor SHALL `_COLLECTOR_MODULES`에 DocDB Collector 모듈을 포함하여 일일 실행 시 DocumentDB 인스턴스를 스캔한다
2. WHEN Daily_Monitor가 type "DocDB"인 리소스를 만나면, THE Daily_Monitor SHALL `sync_alarms_for_resource()`를 리소스 타입 "DocDB"로 호출한다
3. WHEN Daily_Monitor가 type "DocDB"인 리소스를 만나면, THE Daily_Monitor SHALL DocDB Collector의 `get_metrics()`를 호출하여 임계치를 비교한다
4. THE Daily_Monitor SHALL `_process_resource()`에서 "FreeMemoryGB", "FreeLocalStorageGB" 메트릭에 대해 "낮을수록 위험" 비교(current_value < threshold)를 적용한다

### Requirement 8: 고아 알람 정리

**User Story:** As a 모니터링 운영자, I want 삭제된 DocumentDB 인스턴스의 고아 알람이 자동 정리되길 원한다, so that 오래된 알람이 남아있지 않는다.

#### Acceptance Criteria

1. THE Daily_Monitor SHALL `_cleanup_orphan_alarms()`의 `alive_checkers` 맵에 "DocDB"를 등록한다 (DocumentDB 인스턴스는 동일한 `describe_db_instances` API를 사용하므로 `_find_alive_rds_instances()` 함수를 재사용한다)
2. WHEN `_classify_alarm()` 함수가 접두사 "[DocDB]"인 알람을 만나면, THE Daily_Monitor SHALL 해당 알람을 리소스 타입 "DocDB"로 분류한다
3. WHEN DocDB 알람이 더 이상 존재하지 않는 DB 인스턴스를 참조하면, THE Daily_Monitor SHALL 해당 고아 알람을 삭제한다

### Requirement 9: 알람 검색 호환성

**User Story:** As a 모니터링 운영자, I want 알람 검색이 DocumentDB 알람을 올바르게 찾길 원한다, so that 동기화 및 삭제 작업이 DocDB 인스턴스에 대해 동작한다.

#### Acceptance Criteria

1. WHEN DocDB 리소스의 알람을 검색할 때, THE Alarm_Manager SHALL 접두사 "[DocDB] "로 검색하고 접미사 "({db_instance_id})"로 필터링한다
2. THE Alarm_Manager SHALL `_find_alarms_for_resource()`에서 resource_type이 지정되지 않았을 때 기본 type_prefixes 폴백 목록에 "DocDB"를 포함한다

### Requirement 10: Remediation Handler DocDB 지원

**User Story:** As a 모니터링 운영자, I want Remediation Handler가 CloudTrail 이벤트에서 DocumentDB 인스턴스를 올바르게 식별하길 원한다, so that 실시간 알람 관리가 DocumentDB 리소스에 대해 동작한다.

#### Acceptance Criteria

1. WHEN CreateDBInstance CloudTrail 이벤트가 DocDB 엔진에 대해 수신되면, THE Remediation_Handler SHALL 리소스 타입을 "DocDB"로 해석한다
2. WHEN DeleteDBInstance CloudTrail 이벤트가 DocDB 인스턴스에 대해 수신되면, THE Remediation_Handler SHALL 리소스 타입을 "DocDB"로 해석하고 관련 알람을 삭제한다
3. WHEN ModifyDBInstance CloudTrail 이벤트가 DocDB 인스턴스에 대해 수신되면, THE Remediation_Handler SHALL 리소스 타입을 "DocDB"로 해석하고 알람을 재동기화한다
4. WHEN AddTagsToResource 또는 RemoveTagsFromResource CloudTrail 이벤트가 DocDB 인스턴스에 대해 수신되면, THE Remediation_Handler SHALL 리소스 타입을 "DocDB"로 해석한다
5. THE Remediation_Handler SHALL `_resolve_rds_aurora_type()` 함수를 확장하여 Engine 필드가 "docdb"인 경우 "DocDB"를 반환한다 (함수명은 `_resolve_rds_engine_type()`으로 변경 권장)

### Requirement 11: 태그 기반 임계치 오버라이드

**User Story:** As a 모니터링 운영자, I want 태그를 통해 DocumentDB 알람 임계치를 오버라이드하고 싶다, so that 인스턴스별로 모니터링을 커스터마이즈할 수 있다.

#### Acceptance Criteria

1. WHEN DocDB 인스턴스에 `Threshold_CPU` 태그가 있으면, THE Alarm_Manager SHALL 태그 값을 CPUUtilization 알람 임계치로 사용한다
2. WHEN DocDB 인스턴스에 `Threshold_FreeMemoryGB` 태그가 있으면, THE Alarm_Manager SHALL 태그 값(GB 단위)을 FreeableMemory 알람 임계치로 사용한다
3. WHEN DocDB 인스턴스에 `Threshold_FreeLocalStorageGB` 태그가 있으면, THE Alarm_Manager SHALL 태그 값(GB 단위)을 FreeLocalStorage 알람 임계치로 사용한다
4. WHEN DocDB 인스턴스에 `Threshold_Connections` 태그가 있으면, THE Alarm_Manager SHALL 태그 값을 DatabaseConnections 알람 임계치로 사용한다
5. WHEN DocDB 인스턴스에 `Threshold_ReadLatency` 태그가 있으면, THE Alarm_Manager SHALL 태그 값을 ReadLatency 알람 임계치로 사용한다
6. WHEN DocDB 인스턴스에 `Threshold_WriteLatency` 태그가 있으면, THE Alarm_Manager SHALL 태그 값을 WriteLatency 알람 임계치로 사용한다
7. THE Alarm_Manager SHALL DocDB에 대해 하드코딩 목록에 없는 메트릭의 `Threshold_*` 태그를 통한 동적 알람을 지원한다 ("AWS/DocDB" 네임스페이스 내 `list_metrics` API 해석 사용)

### Requirement 12: CloudTrail 이벤트 등록

**User Story:** As a 개발자, I want DocumentDB 생명주기 API가 모니터링 이벤트 목록에 등록되길 원한다, so that CloudTrail 이벤트가 올바르게 라우팅된다.

#### Acceptance Criteria

1. THE Monitoring_Engine SHALL DocumentDB가 RDS와 동일한 CloudTrail API를 사용하므로 `MONITORED_API_EVENTS`에 추가 등록이 필요하지 않음을 확인한다 (CreateDBInstance, DeleteDBInstance, ModifyDBInstance, AddTagsToResource, RemoveTagsFromResource는 이미 등록됨)
2. THE Remediation_Handler SHALL `_API_MAP`의 기존 RDS 매핑을 통해 DocDB 이벤트를 수신하고, `_resolve_rds_aurora_type()` (또는 확장된 함수)에서 Engine 기반으로 "DocDB"를 판별한다

### Requirement 13: TypedDict 및 타입 어노테이션 업데이트

**User Story:** As a 개발자, I want 타입 어노테이션이 새 DocDB 리소스 타입을 반영하길 원한다, so that 코드가 자기 문서화되고 타입 안전하다.

#### Acceptance Criteria

1. THE Monitoring_Engine SHALL `ResourceInfo` TypedDict의 `type` 필드 주석에 "DocDB"를 유효한 값으로 포함한다
2. THE Monitoring_Engine SHALL `AlertMessage` TypedDict의 `resource_type` 필드 주석에 "DocDB"를 유효한 값으로 포함한다
3. THE Monitoring_Engine SHALL `RemediationAlertMessage` TypedDict의 `resource_type` 필드 주석에 "DocDB"를 유효한 값으로 포함한다
4. THE Monitoring_Engine SHALL `LifecycleAlertMessage` TypedDict의 `resource_type` 필드 주석에 "DocDB"를 유효한 값으로 포함한다

### Requirement 14: Remediation Handler 실행 지원

**User Story:** As a 모니터링 운영자, I want Remediation Handler가 DocDB 인스턴스에 대해 Auto-Remediation을 수행할 수 있길 원한다, so that 무단 변경 시 자동 대응이 가능하다.

#### Acceptance Criteria

1. WHEN DocDB 인스턴스에 대해 MODIFY 이벤트가 수신되고 Monitoring=on 태그가 있으면, THE Remediation_Handler SHALL `stop_db_instance()` API를 호출하여 인스턴스를 중지한다
2. THE Remediation_Handler SHALL `_execute_remediation()`에 "DocDB" 케이스를 추가하여 `stop_db_instance()` 호출 후 "STOPPED"를 반환한다
3. THE Remediation_Handler SHALL `_remediation_action_name()`에 "DocDB" 매핑을 추가하여 "STOPPED"를 반환한다

### Requirement 15: Tag Resolver DocDB 지원

**User Story:** As a 개발자, I want tag_resolver가 DocDB 리소스의 태그를 올바르게 조회하길 원한다, so that 태그 기반 임계치 해석이 동작한다.

#### Acceptance Criteria

1. THE tag_resolver SHALL `get_resource_tags()` 함수에서 "DocDB"를 "RDS"와 동일하게 처리한다 (둘 다 `describe_db_instances` + `list_tags_for_resource` 사용)
