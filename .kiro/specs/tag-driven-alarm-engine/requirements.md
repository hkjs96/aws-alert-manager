# Requirements Document

## Introduction

동적 태그 알람 엔진의 3가지 핵심 개선사항을 정의한다:
1. `_resolve_metric_dimensions()`의 디멘션 필터링 개선 — AZ 등 불필요한 디멘션이 포함되는 문제 해결
2. `Threshold_*=off` 태그로 개별 메트릭 알람 비활성화 지원
3. `sync_alarms_for_resource()` 경로에서 동적 태그 알람 생성/삭제/업데이트 지원

## Glossary

- **Alarm_Engine**: `common/alarm_manager.py` 모듈. CloudWatch 알람의 생성, 삭제, 동기화를 담당하는 핵심 엔진
- **Dimension_Resolver**: `_resolve_metric_dimensions()` 함수. `list_metrics` API를 호출하여 동적 메트릭의 네임스페이스와 디멘션을 자동 해석하는 컴포넌트
- **Dynamic_Alarm**: 하드코딩 알람 정의(`_*_ALARMS`)에 없는 메트릭에 대해 `Threshold_{MetricName}={Value}` 태그로 생성되는 알람
- **Hardcoded_Alarm**: `_EC2_ALARMS`, `_RDS_ALARMS`, `_ALB_ALARMS`, `_NLB_ALARMS`, `_TG_ALARMS`에 정의된 기본 알람
- **Primary_Dimension_Key**: 리소스 유형별 기본 디멘션 키. EC2→`InstanceId`, RDS→`DBInstanceIdentifier`, ALB/NLB→`LoadBalancer`, TG→`TargetGroup`
- **Create_Path**: `create_alarms_for_resource()` 함수. 기존 알람을 전체 삭제 후 재생성하는 경로
- **Sync_Path**: `sync_alarms_for_resource()` 함수. 메타데이터 기반 매칭으로 개별 알람을 업데이트하는 경로
- **Threshold_Tag**: `Threshold_{MetricName}={Value}` 형식의 AWS 리소스 태그. 알람 임계치를 제어한다
- **Off_Value**: Threshold_Tag의 값이 `off` (대소문자 무관)인 경우. 해당 메트릭 알람을 비활성화(생성 스킵 또는 삭제)한다

## Requirements

### Requirement 1: 디멘션 필터링 — Primary_Dimension_Key 우선 선택

**User Story:** As a 운영자, I want 동적 알람이 리소스 레벨 디멘션만 포함하도록, so that AZ별 디멘션이 포함된 불필요한 알람이 생성되지 않는다.

#### Acceptance Criteria

1. WHEN `list_metrics` API가 여러 디멘션 조합을 반환하면, THE Dimension_Resolver SHALL Primary_Dimension_Key만 포함된 디멘션 조합을 우선 선택한다
2. WHEN Primary_Dimension_Key만 포함된 디멘션 조합이 없으면, THE Dimension_Resolver SHALL 반환된 디멘션 조합 중 디멘션 수가 가장 적은 것을 선택한다
3. WHEN 디멘션 수가 동일한 조합이 여러 개이면, THE Dimension_Resolver SHALL `AvailabilityZone` 디멘션이 포함되지 않은 조합을 우선 선택한다
4. THE Dimension_Resolver SHALL `AvailabilityZone` 디멘션을 포함하는 조합을 기본적으로 제외한다
5. WHEN `AvailabilityZone` 디멘션이 포함되지 않은 조합이 없으면, THE Dimension_Resolver SHALL 가장 디멘션 수가 적은 조합을 선택한다 (AZ 포함 허용)

### Requirement 2: Threshold_*=off 지원 — 동적 알람 비활성화

**User Story:** As a 운영자, I want `Threshold_{MetricName}=off` 태그로 특정 동적 메트릭 알람을 비활성화하고 싶다, so that 불필요한 동적 알람을 태그 하나로 제어할 수 있다.

#### Acceptance Criteria

1. WHEN Threshold_Tag의 값이 Off_Value이면, THE Alarm_Engine SHALL `_parse_threshold_tags()` 결과에서 해당 메트릭을 제외한다
2. WHEN Threshold_Tag의 값이 `OFF`, `Off`, `oFf` 등 대소문자 변형이면, THE Alarm_Engine SHALL 동일하게 Off_Value로 인식한다

### Requirement 3: Threshold_*=off 지원 — 하드코딩 알람 비활성화

**User Story:** As a 운영자, I want `Threshold_CPU=off` 같은 태그로 하드코딩 알람도 비활성화하고 싶다, so that 리소스별로 불필요한 기본 알람을 선택적으로 끌 수 있다.

#### Acceptance Criteria

1. WHEN 하드코딩 메트릭에 대한 Threshold_Tag 값이 Off_Value이면, THE Create_Path SHALL 해당 메트릭 알람 생성을 스킵한다
2. WHEN 하드코딩 메트릭에 대한 Threshold_Tag 값이 Off_Value이면, THE Sync_Path SHALL 해당 메트릭의 기존 알람을 삭제한다
3. WHEN Disk 계열 태그(`Threshold_Disk_root=off` 등)의 값이 Off_Value이면, THE Alarm_Engine SHALL 해당 경로의 Disk 알람 생성을 스킵한다

### Requirement 4: Threshold_*=off — 기존 알람 삭제

**User Story:** As a 운영자, I want Off_Value 태그를 설정했을 때 이미 존재하는 알람이 자동 삭제되길 원한다, so that 수동으로 알람을 삭제할 필요가 없다.

#### Acceptance Criteria

1. WHEN Create_Path에서 Off_Value 메트릭에 대한 기존 알람이 존재하면, THE Alarm_Engine SHALL 해당 알람을 삭제한다
2. WHEN Sync_Path에서 Off_Value 메트릭에 대한 기존 알람이 존재하면, THE Alarm_Engine SHALL 해당 알람을 삭제한다
3. THE Alarm_Engine SHALL Off_Value로 인한 알람 삭제를 로그에 기록한다

### Requirement 5: Sync 경로 동적 알람 — 신규 생성

**User Story:** As a 운영자, I want sync 경로에서도 새로 추가된 동적 태그 알람이 자동 생성되길 원한다, so that Daily Monitor 실행 시 동적 알람이 누락되지 않는다.

#### Acceptance Criteria

1. WHEN Sync_Path 실행 시 `_parse_threshold_tags()`가 동적 메트릭을 반환하면, THE Sync_Path SHALL 기존 알람에 해당 메트릭이 없는 경우 새 Dynamic_Alarm을 생성한다
2. WHEN 새 Dynamic_Alarm이 생성되면, THE Sync_Path SHALL 결과의 `created` 목록에 해당 알람 이름을 포함한다

### Requirement 6: Sync 경로 동적 알람 — 삭제

**User Story:** As a 운영자, I want 동적 태그를 제거하면 sync 경로에서 해당 알람이 자동 삭제되길 원한다, so that 태그 제거만으로 알람 정리가 완료된다.

#### Acceptance Criteria

1. WHEN Sync_Path 실행 시 기존 Dynamic_Alarm의 metric_key에 대응하는 Threshold_Tag가 없으면, THE Sync_Path SHALL 해당 Dynamic_Alarm을 삭제한다
2. THE Sync_Path SHALL 삭제된 Dynamic_Alarm을 결과의 `deleted` 목록에 포함한다

### Requirement 7: Sync 경로 동적 알람 — 임계치 업데이트

**User Story:** As a 운영자, I want 동적 태그 임계치를 변경하면 sync 경로에서 알람이 자동 업데이트되길 원한다, so that 태그 변경만으로 알람 임계치가 반영된다.

#### Acceptance Criteria

1. WHEN Sync_Path 실행 시 기존 Dynamic_Alarm의 임계치와 현재 Threshold_Tag 값이 다르면, THE Sync_Path SHALL 해당 Dynamic_Alarm을 새 임계치로 업데이트한다
2. WHEN Dynamic_Alarm 임계치가 일치하면, THE Sync_Path SHALL 해당 알람을 `ok` 목록에 포함한다
3. WHEN Dynamic_Alarm 임계치가 변경되면, THE Sync_Path SHALL 해당 알람을 `updated` 목록에 포함한다

### Requirement 8: tag_resolver Off_Value 처리

**User Story:** As a 개발자, I want `get_threshold()` 함수가 Off_Value를 명확하게 처리하길 원한다, so that 알람 생성 로직에서 off 상태를 안전하게 판별할 수 있다.

#### Acceptance Criteria

1. WHEN `get_threshold()` 호출 시 Threshold_Tag 값이 Off_Value이면, THE tag_resolver SHALL 환경 변수나 하드코딩 기본값으로 폴백하지 않고 Off_Value 상태를 호출자에게 전달한다
2. THE tag_resolver SHALL Off_Value 판별을 위한 별도 함수(`is_threshold_off()`)를 제공한다
3. THE `is_threshold_off()` 함수 SHALL 대소문자 무관하게 `off` 문자열을 인식한다
