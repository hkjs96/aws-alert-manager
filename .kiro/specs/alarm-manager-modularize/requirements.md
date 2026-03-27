# Requirements Document

## Introduction

`alarm_manager.py`(2086줄)를 책임별 7개 모듈로 분리하고, 알람 정의를 데이터 드리븐 레지스트리로 전환하며, 중복 임계치 해석 로직을 통합 패턴으로 추출하는 리팩터링이다. 외부 인터페이스 시그니처 변경 없이 기존 607개 테스트 전부 통과를 보장한다.

## Glossary

- **Alarm_Manager**: CloudWatch Alarm 자동 생성/삭제/동기화를 담당하는 기존 단일 모듈 (`common/alarm_manager.py`)
- **Facade**: 기존 외부 인터페이스 시그니처를 유지하면서 내부 모듈에 위임하는 진입점 모듈
- **Alarm_Registry**: 모든 리소스 유형별 알람 정의 데이터를 단일 레지스트리로 관리하는 모듈 (`common/alarm_registry.py`)
- **Threshold_Resolver**: FreeMemoryGB/FreeLocalStorageGB 퍼센트 기반 임계치 해석을 포함한 통합 임계치 해석 모듈 (`common/threshold_resolver.py`)
- **Dimension_Builder**: CloudWatch 디멘션 구성과 네임스페이스 해석을 전담하는 모듈 (`common/dimension_builder.py`)
- **Alarm_Naming**: 알람 이름 생성, 메타데이터 빌드/파싱, Short ID 추출을 전담하는 모듈 (`common/alarm_naming.py`)
- **Alarm_Builder**: CloudWatch `put_metric_alarm` 호출을 담당하는 알람 생성 전담 모듈 (`common/alarm_builder.py`)
- **Alarm_Search**: CloudWatch 알람 검색과 삭제를 전담하는 모듈 (`common/alarm_search.py`)
- **Alarm_Sync**: Daily Monitor용 알람 동기화를 전담하는 모듈 (`common/alarm_sync.py`)
- **AlarmDef**: 알람 정의 레코드 (metric, namespace, metric_name, dimension_key, stat, comparison, period, evaluation_periods 등을 포함하는 dict)
- **Re-export**: Facade 모듈에서 내부 모듈의 심볼을 기존 이름으로 다시 내보내어 import 호환성을 유지하는 패턴
- **DAG**: Directed Acyclic Graph — 순환 없는 방향 그래프 (모듈 의존성 구조)
- **SUPPORTED_RESOURCE_TYPES**: EC2, RDS, ALB, NLB, TG, AuroraRDS, DocDB 7개 리소스 유형

## Requirements

### Requirement 1: 모듈 분리 구조

**User Story:** As a 개발자, I want alarm_manager.py를 책임별 모듈로 분리하고 싶다, so that 각 모듈의 책임이 명확해지고 유지보수성이 향상된다.

#### Acceptance Criteria

1. WHEN 리팩터링이 완료되면, THE Alarm_Manager SHALL Facade 역할만 수행하며 `create_alarms_for_resource`, `delete_alarms_for_resource`, `sync_alarms_for_resource` 3개 public 함수를 내부 모듈에 위임한다
2. WHEN 리팩터링이 완료되면, THE Alarm_Registry SHALL 모든 리소스 유형별 알람 정의 데이터(`_EC2_ALARMS`, `_RDS_ALARMS`, `_ALB_ALARMS`, `_NLB_ALARMS`, `_TG_ALARMS`, `_AURORA_RDS_ALARMS`, `_DOCDB_ALARMS`)와 매핑 테이블(`_HARDCODED_METRIC_KEYS`, `_NAMESPACE_MAP`, `_DIMENSION_KEY_MAP`, `_METRIC_DISPLAY`, `_metric_name_to_key`)을 보유한다
3. WHEN 리팩터링이 완료되면, THE Threshold_Resolver SHALL FreeMemoryGB/FreeLocalStorageGB 퍼센트 기반 해석과 transform_threshold 적용을 포함한 모든 임계치 해석 로직을 단일 `resolve_threshold()` 함수로 통합한다
4. WHEN 리팩터링이 완료되면, THE Dimension_Builder SHALL CloudWatch 디멘션 구성(`_build_dimensions`, `_extract_elb_dimension`, `_resolve_tg_namespace`, `_resolve_metric_dimensions`, `_select_best_dimensions`, `_get_disk_dimensions`)을 전담한다
5. WHEN 리팩터링이 완료되면, THE Alarm_Naming SHALL 알람 이름 생성(`_pretty_alarm_name`, `_alarm_name`), 메타데이터 빌드/파싱(`_build_alarm_description`, `_parse_alarm_metadata`), Short ID 추출(`_shorten_elb_resource_id`)을 전담한다
6. WHEN 리팩터링이 완료되면, THE Alarm_Builder SHALL 표준/Disk/동적 알람 생성과 재생성 로직(`_create_standard_alarm`, `_create_disk_alarms`, `_create_dynamic_alarm`, `_create_single_alarm`, `_recreate_alarm_by_name`)을 전담한다
7. WHEN 리팩터링이 완료되면, THE Alarm_Search SHALL 알람 검색(`_find_alarms_for_resource`), 삭제(`_delete_all_alarms_for_resource`, `_delete_alarm_names`), 배치 describe(`_describe_alarms_batch`)를 전담한다
8. WHEN 리팩터링이 완료되면, THE Alarm_Sync SHALL 하드코딩/Disk/동적 알람 동기화와 off 태그 처리(`_sync_standard_alarms`, `_sync_disk_alarms`, `_sync_off_hardcoded`, `_sync_dynamic_alarms`, `_apply_sync_changes`)를 전담한다

### Requirement 2: 모듈 의존성 DAG 보장

**User Story:** As a 개발자, I want 모듈 간 의존성이 순환 없는 DAG를 형성하길 원한다, so that import 순서 문제나 순환 참조가 발생하지 않는다.

#### Acceptance Criteria

1. THE Alarm_Registry SHALL 다른 내부 모듈에 의존하지 않는 순수 데이터 모듈이다
2. THE Threshold_Resolver SHALL Alarm_Registry와 `common.tag_resolver`에만 의존한다
3. THE Alarm_Naming SHALL Alarm_Registry에만 의존한다
4. THE Dimension_Builder SHALL Alarm_Registry와 Alarm_Naming에만 의존한다
5. THE Alarm_Search SHALL Alarm_Naming에만 의존한다
6. THE Alarm_Builder SHALL Alarm_Registry, Threshold_Resolver, Dimension_Builder, Alarm_Naming에만 의존한다
7. THE Alarm_Sync SHALL Alarm_Registry, Threshold_Resolver, Alarm_Builder, Alarm_Search에만 의존한다
8. THE Alarm_Manager(Facade) SHALL Alarm_Builder, Alarm_Search, Alarm_Sync, Alarm_Registry에만 의존한다
9. THE 모듈 의존성 그래프 SHALL DAG(Directed Acyclic Graph)를 형성하며 순환 의존성이 존재하지 않는다

### Requirement 3: 외부 인터페이스 호환성

**User Story:** As a 기존 코드 사용자, I want 리팩터링 후에도 기존 import 경로와 함수 시그니처가 동일하게 동작하길 원한다, so that 기존 코드를 수정하지 않아도 된다.

#### Acceptance Criteria

1. THE Alarm_Manager(Facade) SHALL `create_alarms_for_resource(resource_id, resource_type, resource_tags) -> list[str]` 시그니처를 변경 없이 유지한다
2. THE Alarm_Manager(Facade) SHALL `delete_alarms_for_resource(resource_id, resource_type) -> list[str]` 시그니처를 변경 없이 유지한다
3. THE Alarm_Manager(Facade) SHALL `sync_alarms_for_resource(resource_id, resource_type, resource_tags) -> dict` 시그니처를 변경 없이 유지한다
4. WHEN 기존 테스트 코드가 `from common.alarm_manager import X` 형태로 내부 심볼을 참조하면, THE Alarm_Manager(Facade) SHALL re-export를 통해 동일한 심볼을 제공한다
5. WHEN 리팩터링이 완료되면, THE 전체 테스트 스위트(607개) SHALL 코드 수정 없이 전부 통과한다

### Requirement 4: 데이터 드리븐 알람 레지스트리

**User Story:** As a 개발자, I want 알람 정의가 단일 레지스트리에서 관리되길 원한다, so that 새 메트릭 추가 시 테스트 하드코딩 개수를 수동 업데이트하지 않아도 된다.

#### Acceptance Criteria

1. THE Alarm_Registry SHALL `get_alarm_defs(resource_type, resource_tags)` 함수를 통해 리소스 유형별 알람 정의 목록을 반환한다
2. WHEN 지원하지 않는 resource_type이 전달되면, THE Alarm_Registry SHALL 빈 리스트를 반환한다
3. WHEN resource_type이 "TG"이고 `_target_type`이 "alb"이면, THE Alarm_Registry SHALL 빈 리스트를 반환한다
4. WHEN resource_type이 "TG"이고 `_lb_type`이 "network"이면, THE Alarm_Registry SHALL RequestCountPerTarget과 TGResponseTime을 제외한 알람 정의를 반환한다
5. WHEN resource_type이 "AuroraRDS"이면, THE Alarm_Registry SHALL resource_tags 기반으로 Serverless v2와 Provisioned 변형을 구분하여 동적으로 알람 정의를 빌드한다
6. THE Alarm_Registry SHALL `get_hardcoded_metric_keys(resource_type, resource_tags)` 함수를 통해 해당 타입의 하드코딩 메트릭 키 집합을 반환한다
7. THE Alarm_Registry SHALL `metric_name_to_key(metric_name)` 함수를 통해 CloudWatch 메트릭 이름을 내부 키로 변환한다
8. THE Alarm_Registry SHALL `METRIC_DISPLAY`, `NAMESPACE_MAP`, `DIMENSION_KEY_MAP` 매핑 데이터를 보유하고 조회 함수를 제공한다

### Requirement 5: 통합 임계치 해석

**User Story:** As a 개발자, I want 4곳에 중복된 FreeMemoryGB/FreeLocalStorageGB 임계치 해석 분기를 단일 함수로 통합하고 싶다, so that 임계치 해석 로직 변경 시 한 곳만 수정하면 된다.

#### Acceptance Criteria

1. THE Threshold_Resolver SHALL `resolve_threshold(alarm_def, resource_tags) -> (display_threshold, cw_threshold)` 단일 진입점을 제공한다
2. WHEN alarm_def의 metric이 "FreeMemoryGB"이면, THE Threshold_Resolver SHALL `resolve_free_memory_threshold(resource_tags)` 결과와 동일한 값을 반환한다
3. WHEN alarm_def의 metric이 "FreeLocalStorageGB"이면, THE Threshold_Resolver SHALL `resolve_free_local_storage_threshold(resource_tags)` 결과와 동일한 값을 반환한다
4. WHEN alarm_def에 `transform_threshold` 함수가 존재하면, THE Threshold_Resolver SHALL `cw_threshold = transform(display_threshold)`를 적용한다
5. WHEN alarm_def에 `transform_threshold`가 없고 metric이 FreeMemoryGB/FreeLocalStorageGB가 아니면, THE Threshold_Resolver SHALL `display_threshold == cw_threshold == get_threshold(tags, metric)`을 반환한다
6. THE Threshold_Resolver의 `resolve_threshold()` SHALL 기존 `_create_standard_alarm`, `_sync_standard_alarms`, `_create_single_alarm`, `_recreate_standard_alarm` 4개 함수의 if/elif 분기와 동일한 결과를 생성한다

### Requirement 6: 알람 정의 데이터 완전성

**User Story:** As a 개발자, I want 레지스트리로 이동한 알람 정의가 기존 데이터와 완전히 동일하길 원한다, so that 리팩터링으로 인한 알람 동작 변경이 없다.

#### Acceptance Criteria

1. WHEN 리팩터링이 완료되면, THE Alarm_Registry의 `get_alarm_defs(resource_type)` 반환 메트릭 집합 SHALL 리팩터링 전 `_get_alarm_defs(resource_type)` 반환 메트릭 집합과 동일하다
2. WHEN 리팩터링이 완료되면, THE Alarm_Registry의 각 AlarmDef SHALL metric, namespace, metric_name, dimension_key, stat, comparison, period, evaluation_periods 필드가 기존 정의와 동일하다
3. WHEN 리팩터링이 완료되면, THE Alarm_Registry의 `HARDCODED_METRIC_KEYS` SHALL 기존 `_HARDCODED_METRIC_KEYS`와 동일한 매핑을 보유한다
4. WHEN 리팩터링이 완료되면, THE Alarm_Registry의 `METRIC_DISPLAY` SHALL 기존 `_METRIC_DISPLAY`와 동일한 매핑을 보유한다
5. WHEN 리팩터링이 완료되면, THE Alarm_Registry의 `NAMESPACE_MAP`과 `DIMENSION_KEY_MAP` SHALL 기존 매핑과 동일하다

### Requirement 7: 테스트 자동 참조

**User Story:** As a 개발자, I want 테스트에서 알람 개수 기대값을 레지스트리에서 자동으로 참조하길 원한다, so that 새 메트릭 추가 시 테스트 코드의 하드코딩 개수를 수동 업데이트하지 않아도 된다.

#### Acceptance Criteria

1. THE Alarm_Registry SHALL 테스트 코드에서 `get_alarm_defs(resource_type)`를 호출하여 기대 알람 개수를 동적으로 계산할 수 있는 public 인터페이스를 제공한다
2. WHEN 새 메트릭이 Alarm_Registry에 추가되면, THE 기존 테스트 코드 SHALL 수정 없이 새 기대값을 자동 반영한다

### Requirement 8: 단계별 리팩터링 안전성

**User Story:** As a 개발자, I want 각 모듈 추출 단계마다 전체 테스트가 통과하길 원한다, so that 리팩터링 중 회귀 버그를 즉시 감지할 수 있다.

#### Acceptance Criteria

1. WHEN 각 모듈이 추출될 때마다, THE 전체 테스트 스위트 SHALL 통과한다
2. WHEN 모듈 추출 후 테스트가 실패하면, THE 개발자 SHALL 즉시 롤백하고 원인을 분석한다
3. THE 리팩터링 실행 순서 SHALL 의존성 없는 모듈부터 추출한다 (alarm_registry → alarm_naming → threshold_resolver → dimension_builder → alarm_search → alarm_builder → alarm_sync → Facade 전환)

### Requirement 9: 코딩 거버넌스 준수

**User Story:** As a 개발자, I want 새 모듈들이 기존 코딩 거버넌스를 준수하길 원한다, so that 코드 품질이 일관되게 유지된다.

#### Acceptance Criteria

1. THE 각 새 모듈 SHALL `functools.lru_cache` 기반 싱글턴 패턴으로 boto3 클라이언트를 생성한다 (거버넌스 §1)
2. THE 각 새 모듈 SHALL 파일 상단에 모든 import를 위치시키고 stdlib → 서드파티 → 프로젝트 내부 순서를 따른다 (거버넌스 §2)
3. THE 각 새 모듈 SHALL 함수 복잡도 제한(로컬 변수 15개, statements 50개, branches 12개, 함수 인자 5개)을 준수한다 (거버넌스 §3)
4. THE 각 새 모듈 SHALL AWS API 호출 시 `botocore.exceptions.ClientError`만 catch한다 (거버넌스 §4)
5. THE 각 새 모듈 SHALL `logger = logging.getLogger(__name__)` 패턴으로 로깅한다 (거버넌스 §9)

### Requirement 10: 에러 처리 보존

**User Story:** As a 운영자, I want 리팩터링 후에도 기존 에러 처리 동작이 동일하길 원한다, so that 알람 생성/삭제/동기화 실패 시 동일한 로깅과 폴백이 수행된다.

#### Acceptance Criteria

1. IF CloudWatch API 호출(`put_metric_alarm`, `describe_alarms`, `delete_alarms`)이 `ClientError`를 발생시키면, THEN THE 각 모듈 SHALL `logger.error()`로 로깅하고 해당 알람을 스킵한 후 나머지 알람 처리를 계속한다
2. IF `Threshold_FreeMemoryPct` 태그 값이 비숫자이거나 범위 초과(0 < pct < 100)이면, THEN THE Threshold_Resolver SHALL `logger.warning()`으로 로깅하고 GB 절대값 폴백을 수행한다
3. IF `Threshold_FreeLocalStoragePct` 태그 값이 비숫자이거나 범위 초과이면, THEN THE Threshold_Resolver SHALL `logger.warning()`으로 로깅하고 GB 절대값 폴백을 수행한다

### Requirement 11: 성능 영향 최소화

**User Story:** As a 운영자, I want 모듈 분리로 인한 성능 저하가 없길 원한다, so that Lambda 실행 시간과 비용이 증가하지 않는다.

#### Acceptance Criteria

1. THE 각 새 모듈 SHALL 독립적인 `_get_cw_client()` 싱글턴을 유지하여 동일 boto3 클라이언트를 재사용한다
2. THE Alarm_Registry SHALL 모듈 로드 시 1회 초기화되며 런타임 조회 비용이 추가되지 않는다
3. THE 리팩터링 SHALL `get_alarm_defs()` 호출 빈도를 기존과 동일하게 유지하며 추가 호출을 발생시키지 않는다
