# Requirements Document

## Introduction

현재 ELB collector(`common/collectors/elb.py`)에서 ALB, NLB, Target Group 모두 `resource_type`을 `"ELB"`로 통일하여 사용 중이다. 이로 인해 알람 이름이 `[ELB] ...`로 동일하게 표시되어 ALB/NLB/TG를 구분할 수 없다.

이 기능은 리소스 유형을 세분화하여 알람 이름에서 `[ALB]`, `[NLB]`, `[TG]`로 구분 표시하고, 기존 `[ELB]` 알람을 새 포맷으로 마이그레이션하는 것을 목표로 한다.

## Glossary

- **ELB_Collector**: `common/collectors/elb.py` 모듈. ALB, NLB, TG 리소스를 수집하는 컬렉터
- **Alarm_Manager**: `common/alarm_manager.py` 모듈. CloudWatch 알람 생성/삭제/동기화를 담당
- **Daily_Monitor**: `daily_monitor/lambda_handler.py` 모듈. 매일 1회 알람 동기화 및 메트릭 점검 실행
- **Resource_Type**: `ResourceInfo["type"]` 필드. 알람 이름 prefix(`[ALB]`, `[NLB]`, `[TG]`)로 사용
- **ALB**: Application Load Balancer. AWS ELBv2 `Type=application`
- **NLB**: Network Load Balancer. AWS ELBv2 `Type=network`
- **TG**: Target Group. ALB 또는 NLB에 연결된 대상 그룹
- **Legacy_Alarm**: 기존 `[ELB]` prefix를 사용하는 알람
- **Alarm_Name_Format**: `[{resource_type}] {label} {display_metric} {direction}{threshold}{unit} ({resource_id})`

## Requirements

### Requirement 1: ALB 리소스 타입 구분

**User Story:** As a 운영자, I want ALB 알람 이름에 `[ALB]` prefix가 표시되기를, so that ALB 알람을 NLB/TG 알람과 즉시 구분할 수 있다.

#### Acceptance Criteria

1. WHEN ELB_Collector가 `Type=application`인 Load Balancer를 수집할 때, THE ELB_Collector SHALL `ResourceInfo.type`을 `"ALB"`로 설정한다
2. WHEN Alarm_Manager가 Resource_Type `"ALB"`인 리소스에 대해 알람을 생성할 때, THE Alarm_Manager SHALL 알람 이름 prefix를 `[ALB]`로 설정한다
3. WHEN Alarm_Manager가 Resource_Type `"ALB"`인 리소스의 알람을 검색할 때, THE Alarm_Manager SHALL `[ALB] ` prefix로 검색한다

### Requirement 2: NLB 리소스 타입 구분

**User Story:** As a 운영자, I want NLB 알람 이름에 `[NLB]` prefix가 표시되기를, so that NLB 알람을 ALB/TG 알람과 즉시 구분할 수 있다.

#### Acceptance Criteria

1. WHEN ELB_Collector가 `Type=network`인 Load Balancer를 수집할 때, THE ELB_Collector SHALL `ResourceInfo.type`을 `"NLB"`로 설정한다
2. WHEN Alarm_Manager가 Resource_Type `"NLB"`인 리소스에 대해 알람을 생성할 때, THE Alarm_Manager SHALL 알람 이름 prefix를 `[NLB]`로 설정한다
3. WHEN Alarm_Manager가 Resource_Type `"NLB"`인 리소스의 알람을 검색할 때, THE Alarm_Manager SHALL `[NLB] ` prefix로 검색한다

### Requirement 3: TG 리소스 타입 유지

**User Story:** As a 운영자, I want TG 알람 이름에 `[TG]` prefix가 유지되기를, so that Target Group 알람을 LB 알람과 구분할 수 있다.

#### Acceptance Criteria

1. THE ELB_Collector SHALL Target Group 리소스의 `ResourceInfo.type`을 `"TG"`로 유지한다
2. WHEN Alarm_Manager가 Resource_Type `"TG"`인 리소스에 대해 알람을 생성할 때, THE Alarm_Manager SHALL 알람 이름 prefix를 `[TG]`로 설정한다

### Requirement 4: Alarm_Manager의 ALB/NLB/TG 알람 정의 분기

**User Story:** As a 개발자, I want Alarm_Manager가 ALB, NLB, TG 각각에 맞는 알람 정의를 반환하기를, so that 리소스 유형별로 올바른 메트릭과 네임스페이스가 적용된다.

#### Acceptance Criteria

1. WHEN Alarm_Manager가 Resource_Type `"ALB"`에 대한 알람 정의를 조회할 때, THE Alarm_Manager SHALL `AWS/ApplicationELB` 네임스페이스의 `RequestCount` 메트릭 정의를 반환한다
2. WHEN Alarm_Manager가 Resource_Type `"NLB"`에 대한 알람 정의를 조회할 때, THE Alarm_Manager SHALL `AWS/NetworkELB` 네임스페이스의 `ProcessedBytes`, `ActiveFlowCount`, `NewFlowCount` 메트릭 정의를 반환한다
3. WHEN Alarm_Manager가 Resource_Type `"TG"`에 대한 알람 정의를 조회할 때, THE Alarm_Manager SHALL 연결된 LB 타입에 맞는 네임스페이스의 `RequestCount`, `HealthyHostCount` 메트릭 정의를 반환한다
4. WHEN Alarm_Manager가 Resource_Type `"ALB"` 또는 `"NLB"` 또는 `"TG"`인 리소스의 디멘션 값을 설정할 때, THE Alarm_Manager SHALL ARN에서 `loadbalancer/` 이후 suffix를 추출하여 사용한다

### Requirement 5: 기존 Legacy_Alarm 마이그레이션

**User Story:** As a 운영자, I want 기존 `[ELB]` 알람이 다음 Daily_Monitor 실행 시 자동으로 `[ALB]`/`[NLB]`/`[TG]` 알람으로 교체되기를, so that 수동 개입 없이 새 포맷으로 전환된다.

#### Acceptance Criteria

1. WHEN Daily_Monitor가 알람 동기화를 실행할 때, THE Alarm_Manager SHALL `[ELB] ` prefix 알람도 검색 대상에 포함한다
2. WHEN Alarm_Manager가 Legacy_Alarm을 발견하고 해당 리소스가 존재할 때, THE Alarm_Manager SHALL Legacy_Alarm을 삭제하고 새 Resource_Type prefix(`[ALB]`/`[NLB]`/`[TG]`)로 알람을 재생성한다
3. WHEN Daily_Monitor가 고아 알람 정리를 실행할 때, THE Daily_Monitor SHALL `[ELB]` prefix 알람도 고아 알람 검색 대상에 포함한다

### Requirement 6: 알람 이름 255자 제한 준수

**User Story:** As a 개발자, I want 새 Resource_Type prefix(`[ALB]`, `[NLB]`, `[TG]`)를 사용해도 알람 이름이 255자를 초과하지 않기를, so that CloudWatch API 제약을 위반하지 않는다.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL Resource_Type이 `"ALB"`, `"NLB"`, `"TG"` 중 하나일 때에도 알람 이름을 255자 이하로 생성한다
2. WHEN 알람 이름이 255자를 초과할 때, THE Alarm_Manager SHALL 기존 truncate 규칙(label → display_metric 순)을 동일하게 적용한다

### Requirement 7: 관련 모듈 상수 및 매핑 업데이트

**User Story:** As a 개발자, I want `SUPPORTED_RESOURCE_TYPES`, `_HARDCODED_METRIC_KEYS`, `_NAMESPACE_MAP`, `_DIMENSION_KEY_MAP` 등 상수가 ALB/NLB/TG를 반영하기를, so that 시스템 전체에서 새 리소스 타입이 일관되게 동작한다.

#### Acceptance Criteria

1. THE `common/__init__.py` SHALL `SUPPORTED_RESOURCE_TYPES`에 `"ALB"`, `"NLB"`, `"TG"`를 포함하고 `"ELB"`를 제거한다
2. THE Alarm_Manager SHALL `_HARDCODED_METRIC_KEYS`에 `"ALB"`, `"NLB"`, `"TG"` 키를 추가하고 `"ELB"` 키를 제거한다
3. THE Alarm_Manager SHALL `_NAMESPACE_MAP`에 `"ALB"`, `"NLB"`, `"TG"` 키를 추가하고 `"ELB"` 키를 제거한다
4. THE Alarm_Manager SHALL `_DIMENSION_KEY_MAP`에 `"ALB"`, `"NLB"`, `"TG"` 키를 추가하고 `"ELB"` 키를 제거한다

### Requirement 8: 고아 알람 정리 호환성

**User Story:** As a 운영자, I want 고아 알람 정리 로직이 `[ALB]`, `[NLB]`, `[TG]` prefix 알람을 올바르게 분류하기를, so that 삭제된 리소스의 알람이 정리된다.

#### Acceptance Criteria

1. WHEN Daily_Monitor가 `[ALB]` prefix 알람을 분류할 때, THE Daily_Monitor SHALL 해당 알람의 resource_id를 ELB 존재 확인 함수로 전달한다
2. WHEN Daily_Monitor가 `[NLB]` prefix 알람을 분류할 때, THE Daily_Monitor SHALL 해당 알람의 resource_id를 ELB 존재 확인 함수로 전달한다
3. WHEN Daily_Monitor가 `[TG]` prefix 알람을 분류할 때, THE Daily_Monitor SHALL 해당 알람의 resource_id를 TG 존재 확인 함수로 전달한다
4. THE Daily_Monitor SHALL `alive_checkers` 매핑에 `"ALB"`, `"NLB"` 키를 추가하여 `_find_alive_elb_resources` 함수를 연결한다

### Requirement 9: Remediation Handler 호환성

**User Story:** As a 개발자, I want Remediation Handler가 ALB/NLB 리소스에 대해 올바른 resource_type을 사용하기를, so that CloudTrail 이벤트 처리 시 알람 생성/삭제가 정상 동작한다.

#### Acceptance Criteria

1. WHEN Remediation Handler가 ELB 관련 CloudTrail 이벤트를 파싱할 때, THE Remediation Handler SHALL ARN의 `app/` 또는 `net/` prefix를 기반으로 resource_type을 `"ALB"` 또는 `"NLB"`로 설정한다
2. WHEN Remediation Handler가 resource_type `"ALB"` 또는 `"NLB"`인 리소스의 태그를 조회할 때, THE tag_resolver SHALL ELBv2 API를 사용하여 태그를 반환한다
