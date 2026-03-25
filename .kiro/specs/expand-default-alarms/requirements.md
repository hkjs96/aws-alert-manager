# Requirements Document

## Introduction

리소스 유형별 기본 알람 정의(`_EC2_ALARMS`, `_RDS_ALARMS`, `_ALB_ALARMS`, `_NLB_ALARMS`, `_TG_ALARMS`)를 확장하여 운영에 필수적인 메트릭을 하드코딩 기본 알람에 추가한다.

현재 동적 태그 알람 시스템(`Threshold_*` 태그 → `list_metrics` API → 자동 알람 생성)은 이미 구현되어 있으므로, 이 기능은 하드코딩 기본 알람 정의와 관련 매핑(`_METRIC_DISPLAY`, `_HARDCODED_METRIC_KEYS`, `_metric_name_to_key`, `HARDCODED_DEFAULTS`)만 확장한다.

추가 대상 메트릭:
- ALB: `HTTPCode_ELB_5XX_Count`, `TargetResponseTime`
- NLB: `TCP_Client_Reset_Count`, `TCP_Target_Reset_Count`
- EC2: `StatusCheckFailed`
- RDS: `ReadLatency`, `WriteLatency`
- TG (ALB TG): `RequestCountPerTarget`, `TargetResponseTime`

## Glossary

- **Alarm_Manager**: `common/alarm_manager.py` 모듈. CloudWatch Alarm 자동 생성/삭제/동기화를 담당
- **Tag_Resolver**: `common/tag_resolver.py` 모듈. 태그 → 환경 변수 → 하드코딩 기본값 순으로 임계치를 조회
- **HARDCODED_DEFAULTS**: `common/__init__.py`에 정의된 메트릭별 시스템 기본 임계치 딕셔너리
- **_METRIC_DISPLAY**: 메트릭 키 → (CloudWatch 메트릭 이름, 방향, 단위) 매핑 딕셔너리
- **_HARDCODED_METRIC_KEYS**: 리소스 유형별 하드코딩 메트릭 키 집합 딕셔너리
- **_metric_name_to_key**: CloudWatch 메트릭 이름 → 내부 메트릭 키 변환 함수
- **Dynamic_Tag_Alarm**: `Threshold_*` 태그 + `list_metrics` API로 자동 생성되는 동적 알람
- **TG**: Target Group. ALB TG와 NLB TG를 포함하며, namespace는 `_lb_type`에 따라 동적 결정

## Requirements

### Requirement 1: ALB 기본 알람 확장

**User Story:** As an operator, I want ALB default alarms to include 5XX error count and target response time, so that I can detect server errors and latency issues without manual tag configuration.

#### Acceptance Criteria

1. WHEN the Alarm_Manager creates alarms for an ALB resource, THE Alarm_Manager SHALL create an alarm for `HTTPCode_ELB_5XX_Count` metric in the `AWS/ApplicationELB` namespace with `Sum` statistic and `GreaterThanThreshold` comparison
2. WHEN the Alarm_Manager creates alarms for an ALB resource, THE Alarm_Manager SHALL create an alarm for `TargetResponseTime` metric in the `AWS/ApplicationELB` namespace with `Average` statistic and `GreaterThanThreshold` comparison
3. THE `HTTPCode_ELB_5XX_Count` alarm SHALL use `LoadBalancer` single dimension only (LB-level metric, TargetGroup dimension not available per AWS docs)
4. THE `TargetResponseTime` alarm for ALB SHALL use `LoadBalancer` single dimension (LB-level aggregate)
5. THE _METRIC_DISPLAY SHALL contain entries for `ELB5XX` mapping to `("HTTPCode_ELB_5XX_Count", ">", "")` and `TargetResponseTime` mapping to `("TargetResponseTime", ">", "s")`
6. THE _HARDCODED_METRIC_KEYS for `ALB` SHALL contain `{"RequestCount", "ELB5XX", "TargetResponseTime"}`
7. THE HARDCODED_DEFAULTS SHALL contain default threshold values for `ELB5XX` and `TargetResponseTime`
8. THE _metric_name_to_key function SHALL map `HTTPCode_ELB_5XX_Count` to `ELB5XX` and `TargetResponseTime` to `TargetResponseTime`

### Requirement 2: NLB 기본 알람 확장

**User Story:** As an operator, I want NLB default alarms to include TCP reset counts, so that I can detect connection reset issues without manual tag configuration.

#### Acceptance Criteria

1. WHEN the Alarm_Manager creates alarms for an NLB resource, THE Alarm_Manager SHALL create an alarm for `TCP_Client_Reset_Count` metric in the `AWS/NetworkELB` namespace with `Sum` statistic and `GreaterThanThreshold` comparison
2. WHEN the Alarm_Manager creates alarms for an NLB resource, THE Alarm_Manager SHALL create an alarm for `TCP_Target_Reset_Count` metric in the `AWS/NetworkELB` namespace with `Sum` statistic and `GreaterThanThreshold` comparison
3. THE `TCP_Client_Reset_Count` and `TCP_Target_Reset_Count` alarms SHALL use `LoadBalancer` single dimension (LB-level metrics per AWS docs)
4. THE _METRIC_DISPLAY SHALL contain entries for `TCPClientReset` mapping to `("TCP_Client_Reset_Count", ">", "")` and `TCPTargetReset` mapping to `("TCP_Target_Reset_Count", ">", "")`
5. THE _HARDCODED_METRIC_KEYS for `NLB` SHALL contain `{"ProcessedBytes", "ActiveFlowCount", "NewFlowCount", "TCPClientReset", "TCPTargetReset"}`
6. THE HARDCODED_DEFAULTS SHALL contain default threshold values for `TCPClientReset` and `TCPTargetReset`
7. THE _metric_name_to_key function SHALL map `TCP_Client_Reset_Count` to `TCPClientReset` and `TCP_Target_Reset_Count` to `TCPTargetReset`

### Requirement 3: EC2 기본 알람 확장

**User Story:** As an operator, I want EC2 default alarms to include status check failed, so that I can detect instance health issues without manual tag configuration.

#### Acceptance Criteria

1. WHEN the Alarm_Manager creates alarms for an EC2 resource, THE Alarm_Manager SHALL create an alarm for `StatusCheckFailed` metric in the `AWS/EC2` namespace with `Maximum` statistic and `GreaterThanThreshold` comparison
2. THE `StatusCheckFailed` alarm SHALL use `InstanceId` single dimension (AWS/EC2 namespace, per AWS docs)
3. THE _METRIC_DISPLAY SHALL contain an entry for `StatusCheckFailed` mapping to `("StatusCheckFailed", ">", "")`
4. THE _HARDCODED_METRIC_KEYS for `EC2` SHALL contain `{"CPU", "Memory", "Disk", "StatusCheckFailed"}`
5. THE HARDCODED_DEFAULTS SHALL contain a default threshold value for `StatusCheckFailed`
6. THE _metric_name_to_key function SHALL map `StatusCheckFailed` to `StatusCheckFailed`

### Requirement 4: RDS 기본 알람 확장

**User Story:** As an operator, I want RDS default alarms to include read/write latency, so that I can detect I/O performance degradation without manual tag configuration.

#### Acceptance Criteria

1. WHEN the Alarm_Manager creates alarms for an RDS resource, THE Alarm_Manager SHALL create an alarm for `ReadLatency` metric in the `AWS/RDS` namespace with `Average` statistic and `GreaterThanThreshold` comparison
2. WHEN the Alarm_Manager creates alarms for an RDS resource, THE Alarm_Manager SHALL create an alarm for `WriteLatency` metric in the `AWS/RDS` namespace with `Average` statistic and `GreaterThanThreshold` comparison
3. THE `ReadLatency` and `WriteLatency` alarms SHALL use `DBInstanceIdentifier` single dimension (AWS/RDS namespace, per AWS docs)
4. THE _METRIC_DISPLAY SHALL contain entries for `ReadLatency` mapping to `("ReadLatency", ">", "s")` and `WriteLatency` mapping to `("WriteLatency", ">", "s")`
5. THE _HARDCODED_METRIC_KEYS for `RDS` SHALL contain `{"CPU", "FreeMemoryGB", "FreeStorageGB", "Connections", "ReadLatency", "WriteLatency"}`
6. THE HARDCODED_DEFAULTS SHALL contain default threshold values for `ReadLatency` and `WriteLatency`
7. THE _metric_name_to_key function SHALL map `ReadLatency` to `ReadLatency` and `WriteLatency` to `WriteLatency`

### Requirement 5: TG 기본 알람 확장

**User Story:** As an operator, I want Target Group default alarms to include request count per target and target response time, so that I can detect load imbalance and latency issues without manual tag configuration.

#### Acceptance Criteria

1. WHEN the Alarm_Manager creates alarms for a TG resource, THE Alarm_Manager SHALL create an alarm for `RequestCountPerTarget` metric with `Sum` statistic and `GreaterThanThreshold` comparison
2. WHEN the Alarm_Manager creates alarms for a TG resource, THE Alarm_Manager SHALL create an alarm for `TargetResponseTime` metric with `Average` statistic and `GreaterThanThreshold` comparison
3. THE `RequestCountPerTarget` alarm SHALL use `TargetGroup` + `LoadBalancer` compound dimensions (TargetGroup dimension is mandatory per AWS docs; LoadBalancer added for consistency with existing TG alarm pattern)
4. THE `TargetResponseTime` alarm for TG SHALL use `TargetGroup` + `LoadBalancer` compound dimensions (TG-level metric per AWS docs)
5. WHILE the TG resource has `_lb_type` equal to `network`, THE Alarm_Manager SHALL use `AWS/NetworkELB` namespace for TG alarms
6. WHILE the TG resource has `_lb_type` not equal to `network`, THE Alarm_Manager SHALL use `AWS/ApplicationELB` namespace for TG alarms
7. THE _METRIC_DISPLAY SHALL contain entries for `RequestCountPerTarget` mapping to `("RequestCountPerTarget", ">", "")` and `TGResponseTime` mapping to `("TargetResponseTime", ">", "s")`
8. THE _HARDCODED_METRIC_KEYS for `TG` SHALL contain `{"HealthyHostCount", "UnHealthyHostCount", "RequestCountPerTarget", "TGResponseTime"}`
9. THE HARDCODED_DEFAULTS SHALL contain default threshold values for `RequestCountPerTarget` and `TGResponseTime`
10. THE _metric_name_to_key function SHALL map `RequestCountPerTarget` to `RequestCountPerTarget`

### Requirement 6: 기존 동적 태그 알람과의 호환성 유지

**User Story:** As an operator, I want the expanded default alarms to coexist with the existing dynamic tag alarm system, so that custom Threshold_* tags continue to override default thresholds.

#### Acceptance Criteria

1. WHEN a `Threshold_{metric_key}` tag exists for a newly added hardcoded metric, THE Tag_Resolver SHALL use the tag value as the alarm threshold instead of the hardcoded default
2. THE _parse_threshold_tags function SHALL exclude all newly added hardcoded metric keys from dynamic alarm creation to prevent duplicate alarms
3. WHEN the Alarm_Manager creates alarms for a resource, THE Alarm_Manager SHALL create both existing and newly added hardcoded alarms in a single invocation of `create_alarms_for_resource`

### Requirement 7: 알람 이름 및 메타데이터 일관성

**User Story:** As an operator, I want newly added alarms to follow the same naming convention and metadata format, so that alarm management remains consistent.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL generate alarm names for newly added metrics following the format `[{resource_type}] {label} {display_metric} {direction}{threshold}{unit} ({resource_id})`
2. THE Alarm_Manager SHALL include `metric_key`, `resource_id`, and `resource_type` in the `AlarmDescription` JSON metadata for all newly added alarms
3. WHEN the alarm name exceeds 255 characters, THE Alarm_Manager SHALL truncate label first, then display_metric, while preserving the resource_id suffix

### Requirement 8: CloudWatch 디멘션 정합성

**User Story:** As an operator, I want all alarms to use the correct CloudWatch dimensions per AWS documentation, so that alarms receive metric data and do not remain in INSUFFICIENT_DATA state.

#### Acceptance Criteria

1. THE alarm definition for each newly added metric SHALL specify the correct `dimension_key` matching the AWS CloudWatch documentation
2. THE `_build_dimensions()` function SHALL produce the correct dimension list for each resource type: `InstanceId` for EC2, `DBInstanceIdentifier` for RDS, `LoadBalancer` for ALB/NLB LB-level metrics, `TargetGroup` + `LoadBalancer` for TG-level metrics
3. THE dimension values SHALL follow the ARN suffix format: `app/...` or `net/...` for LoadBalancer, `targetgroup/...` for TargetGroup (extracted by `_extract_elb_dimension()`)
4. WHEN a metric is LB-level only (e.g., `HTTPCode_ELB_5XX_Count`, `TCP_Client_Reset_Count`), THE alarm SHALL NOT include `TargetGroup` dimension
5. WHEN a metric is TG-level (e.g., `RequestCountPerTarget`, TG `TargetResponseTime`), THE alarm SHALL include both `TargetGroup` and `LoadBalancer` dimensions
6. THE coding governance (`.kiro/steering/coding-governance.md`) SHALL document the dimension mapping rules in section §6-1 for reference when adding future metrics
