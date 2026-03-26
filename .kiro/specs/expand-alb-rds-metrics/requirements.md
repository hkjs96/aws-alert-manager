# Requirements Document

## Introduction

기존 ALB 및 RDS 리소스의 하드코딩 기본 알람 정의를 확장하여 세 가지 메트릭을 추가한다. 기존 `expand-default-alarms` 스펙의 패턴을 그대로 따르며, 데이터 정의만 추가하는 작업이다.

추가 대상 메트릭:
- ALB: `HTTPCode_ELB_4XX_Count` (클라이언트 에러 감지)
- ALB: `TargetConnectionErrorCount` (타겟 연결 실패 감지)
- RDS: `ConnectionAttempts` (연결 시도 급증 감지)

기존 헬퍼 함수(`_build_dimensions`, `_resolve_tg_namespace`, `_create_standard_alarm`, `_parse_threshold_tags`)는 수정하지 않는다.

## Glossary

- **Alarm_Manager**: `common/alarm_manager.py` 모듈. CloudWatch Alarm 자동 생성/삭제/동기화를 담당
- **Tag_Resolver**: `common/tag_resolver.py` 모듈. 태그 → 환경 변수 → 하드코딩 기본값 순으로 임계치를 조회
- **HARDCODED_DEFAULTS**: `common/__init__.py`에 정의된 메트릭별 시스템 기본 임계치 딕셔너리
- **_METRIC_DISPLAY**: 메트릭 키 → (CloudWatch 메트릭 이름, 방향, 단위) 매핑 딕셔너리
- **_HARDCODED_METRIC_KEYS**: 리소스 유형별 하드코딩 메트릭 키 집합 딕셔너리
- **_metric_name_to_key**: CloudWatch 메트릭 이름 → 내부 메트릭 키 변환 함수

## Requirements

### Requirement 1: ALB HTTPCode_ELB_4XX_Count 기본 알람 추가

**User Story:** As an operator, I want ALB default alarms to include 4XX error count, so that I can detect client error spikes indicating misconfigured clients or missing resources without manual tag configuration.

#### Acceptance Criteria

1. WHEN the Alarm_Manager creates alarms for an ALB resource, THE Alarm_Manager SHALL create an alarm for `HTTPCode_ELB_4XX_Count` metric in the `AWS/ApplicationELB` namespace with `Sum` statistic and `GreaterThanThreshold` comparison
2. THE `HTTPCode_ELB_4XX_Count` alarm SHALL use `LoadBalancer` single dimension only (LB-level metric per AWS docs, TargetGroup dimension not applicable)
3. THE _METRIC_DISPLAY SHALL contain an entry for `ELB4XX` mapping to `("HTTPCode_ELB_4XX_Count", ">", "")`
4. THE _HARDCODED_METRIC_KEYS for `ALB` SHALL contain `{"RequestCount", "ELB5XX", "TargetResponseTime", "ELB4XX"}`
5. THE HARDCODED_DEFAULTS SHALL contain a default threshold value of `100.0` for `ELB4XX`
6. THE _metric_name_to_key function SHALL map `HTTPCode_ELB_4XX_Count` to `ELB4XX`

### Requirement 2: ALB TargetConnectionErrorCount 기본 알람 추가

**User Story:** As an operator, I want ALB default alarms to include target connection error count, so that I can detect backend connectivity failures without manual tag configuration.

#### Acceptance Criteria

1. WHEN the Alarm_Manager creates alarms for an ALB resource, THE Alarm_Manager SHALL create an alarm for `TargetConnectionErrorCount` metric in the `AWS/ApplicationELB` namespace with `Sum` statistic and `GreaterThanThreshold` comparison
2. THE `TargetConnectionErrorCount` alarm SHALL use `LoadBalancer` single dimension only (LB-level metric per AWS docs)
3. THE _METRIC_DISPLAY SHALL contain an entry for `TargetConnectionError` mapping to `("TargetConnectionErrorCount", ">", "")`
4. THE _HARDCODED_METRIC_KEYS for `ALB` SHALL contain `TargetConnectionError` in addition to existing keys
5. THE HARDCODED_DEFAULTS SHALL contain a default threshold value of `50.0` for `TargetConnectionError`
6. THE _metric_name_to_key function SHALL map `TargetConnectionErrorCount` to `TargetConnectionError`

### Requirement 3: RDS ConnectionAttempts 기본 알람 추가

**User Story:** As an operator, I want RDS default alarms to include connection attempts count, so that I can detect connection attempt spikes indicating potential brute-force or misconfigured connection pools without manual tag configuration.

#### Acceptance Criteria

1. WHEN the Alarm_Manager creates alarms for an RDS resource, THE Alarm_Manager SHALL create an alarm for `ConnectionAttempts` metric in the `AWS/RDS` namespace with `Sum` statistic and `GreaterThanThreshold` comparison
2. THE `ConnectionAttempts` alarm SHALL use `DBInstanceIdentifier` single dimension (AWS/RDS namespace per AWS docs)
3. THE _METRIC_DISPLAY SHALL contain an entry for `ConnectionAttempts` mapping to `("ConnectionAttempts", ">", "")`
4. THE _HARDCODED_METRIC_KEYS for `RDS` SHALL contain `{"CPU", "FreeMemoryGB", "FreeStorageGB", "Connections", "ReadLatency", "WriteLatency", "ConnectionAttempts"}`
5. THE HARDCODED_DEFAULTS SHALL contain a default threshold value of `500.0` for `ConnectionAttempts`
6. THE _metric_name_to_key function SHALL map `ConnectionAttempts` to `ConnectionAttempts`

### Requirement 4: 기존 동적 태그 알람과의 호환성 유지

**User Story:** As an operator, I want the expanded default alarms to coexist with the existing dynamic tag alarm system, so that custom Threshold_* tags continue to override default thresholds.

#### Acceptance Criteria

1. WHEN a `Threshold_{metric_key}` tag exists for a newly added hardcoded metric (ELB4XX, TargetConnectionError, ConnectionAttempts), THE Tag_Resolver SHALL use the tag value as the alarm threshold instead of the hardcoded default
2. THE _parse_threshold_tags function SHALL exclude all newly added hardcoded metric keys from dynamic alarm creation to prevent duplicate alarms
3. WHEN the Alarm_Manager creates alarms for a resource, THE Alarm_Manager SHALL create both existing and newly added hardcoded alarms in a single invocation of `create_alarms_for_resource`

### Requirement 5: 알람 이름 및 메타데이터 일관성

**User Story:** As an operator, I want newly added alarms to follow the same naming convention and metadata format, so that alarm management remains consistent.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL generate alarm names for newly added metrics following the format `[{resource_type}] {label} {display_metric} {direction}{threshold}{unit} ({resource_id})`
2. THE Alarm_Manager SHALL include `metric_key`, `resource_id`, and `resource_type` in the `AlarmDescription` JSON metadata for all newly added alarms
3. WHEN the alarm name exceeds 255 characters, THE Alarm_Manager SHALL truncate label first, then display_metric, while preserving the resource_id suffix

### Requirement 6: CloudWatch 디멘션 정합성

**User Story:** As an operator, I want all alarms to use the correct CloudWatch dimensions per AWS documentation, so that alarms receive metric data and do not remain in INSUFFICIENT_DATA state.

#### Acceptance Criteria

1. THE alarm definition for each newly added metric SHALL specify the correct `dimension_key` matching the AWS CloudWatch documentation
2. WHEN a metric is ALB LB-level (`HTTPCode_ELB_4XX_Count`, `TargetConnectionErrorCount`), THE alarm SHALL use `LoadBalancer` single dimension and SHALL NOT include `TargetGroup` dimension
3. WHEN a metric is RDS instance-level (`ConnectionAttempts`), THE alarm SHALL use `DBInstanceIdentifier` single dimension
