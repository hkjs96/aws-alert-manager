# Requirements Document

## Introduction

ALB/NLB/TG 리소스의 알람 이름에서 전체 ARN 대신 짧은 식별자(short ID)를 사용하도록 변경한다.

현재 `_pretty_alarm_name()`의 suffix `({resource_id})`에 전체 ARN이 들어가면서 알람 이름이 불필요하게 길어진다. 예를 들어 TG ARN `arn:aws:elasticloadbalancing:us-east-1:949501913924:targetgroup/lb-tg-TestA-W92AEI92L2RJ/a53c5a4b6dcac9c5`가 그대로 suffix에 포함되어 가독성이 떨어진다.

ALB/NLB/TG에 한해 ARN에서 이름+해시 부분만 추출하여 짧은 식별자로 사용한다. 알람 매칭은 메타데이터(Namespace, MetricName, Dimensions) 기반이므로 이름 변경은 매칭 로직에 영향을 주지 않는다. 단, `_find_alarms_for_resource()`의 suffix 필터 `({resource_id})`가 변경되므로 검색 로직 호환성을 확보해야 한다.

## Glossary

- **Alarm_Manager**: `common/alarm_manager.py` 모듈. CloudWatch 알람 생성/삭제/동기화를 담당
- **Short_ID**: ALB/NLB/TG ARN에서 추출한 짧은 식별자. 이름+해시 부분만 포함
- **Full_ARN**: `arn:aws:elasticloadbalancing:...` 형태의 전체 Amazon Resource Name
- **Pretty_Alarm_Name**: `_pretty_alarm_name()` 함수가 생성하는 알람 이름 포맷
- **Alarm_Search**: `_find_alarms_for_resource()` 함수의 알람 검색 로직
- **Suffix_Filter**: 알람 검색 시 `name.endswith(suffix)` 조건으로 필터링하는 로직
- **ELB_Dimension_Extractor**: `_extract_elb_dimension()` 함수. ARN에서 CloudWatch 디멘션 값을 추출

## Requirements

### Requirement 1: ALB/NLB/TG ARN에서 짧은 식별자 추출

**User Story:** As a 운영자, I want ALB/NLB/TG 알람 이름에서 전체 ARN 대신 짧은 식별자를 보고 싶다, so that 알람 이름의 가독성이 향상되고 CloudWatch 콘솔에서 알람을 쉽게 식별할 수 있다.

#### Acceptance Criteria

1. WHEN ALB ARN `arn:aws:elasticloadbalancing:{region}:{account}:loadbalancer/app/{name}/{hash}`가 입력되면, THE Alarm_Manager SHALL `{name}/{hash}` 형태의 Short_ID를 반환한다
2. WHEN NLB ARN `arn:aws:elasticloadbalancing:{region}:{account}:loadbalancer/net/{name}/{hash}`가 입력되면, THE Alarm_Manager SHALL `{name}/{hash}` 형태의 Short_ID를 반환한다
3. WHEN TG ARN `arn:aws:elasticloadbalancing:{region}:{account}:targetgroup/{name}/{hash}`가 입력되면, THE Alarm_Manager SHALL `{name}/{hash}` 형태의 Short_ID를 반환한다
4. WHEN EC2 또는 RDS resource_id가 입력되면, THE Alarm_Manager SHALL resource_id를 변환 없이 그대로 반환한다 (기존 동작 유지)
5. WHEN ARN이 아닌 문자열이 ALB/NLB/TG resource_id로 입력되면, THE Alarm_Manager SHALL 해당 문자열을 변환 없이 그대로 반환한다 (방어적 처리)

### Requirement 2: 알람 이름 suffix에 Short_ID 적용

**User Story:** As a 운영자, I want 알람 이름의 suffix 부분이 짧은 식별자를 사용하길 원한다, so that 알람 이름이 간결해지고 255자 제한 내에서 label과 metric 정보를 더 많이 표시할 수 있다.

#### Acceptance Criteria

1. WHEN ALB/NLB/TG 리소스에 대해 알람을 생성하면, THE Pretty_Alarm_Name SHALL suffix를 `({short_id})` 형태로 생성한다 (Full_ARN 대신 Short_ID 사용)
2. WHEN EC2/RDS 리소스에 대해 알람을 생성하면, THE Pretty_Alarm_Name SHALL 기존과 동일하게 `({resource_id})` 형태의 suffix를 생성한다
3. THE Pretty_Alarm_Name SHALL 알람 이름 길이가 255자를 초과하지 않는다 (기존 truncate 로직 유지)
4. WHEN 동적 태그 알람(`_create_dynamic_alarm`)을 ALB/NLB/TG에 대해 생성하면, THE Alarm_Manager SHALL suffix에 Short_ID를 사용한다

### Requirement 3: 알람 검색 로직 호환성

**User Story:** As a 시스템, I want 알람 검색이 새 Short_ID suffix와 레거시 Full_ARN suffix 모두에서 동작하길 원한다, so that 기존 알람과 새 알람 모두 정상적으로 검색/삭제/동기화된다.

#### Acceptance Criteria

1. WHEN 새 포맷(Short_ID suffix) 알람을 검색하면, THE Alarm_Search SHALL Short_ID 기반 suffix 필터로 해당 알람을 찾는다
2. WHEN 레거시 포맷(Full_ARN suffix) 알람이 존재하면, THE Alarm_Search SHALL Full_ARN 기반 suffix 필터로 해당 알람도 찾는다
3. THE Alarm_Search SHALL 새 포맷과 레거시 포맷 알람을 중복 없이 합쳐서 반환한다
4. WHEN EC2/RDS 리소스의 알람을 검색하면, THE Alarm_Search SHALL 기존 검색 로직을 변경 없이 유지한다

### Requirement 4: AlarmDescription 메타데이터 무결성

**User Story:** As a 시스템, I want AlarmDescription의 메타데이터에 항상 전체 resource_id(Full_ARN)가 저장되길 원한다, so that 알람 매칭과 역추적이 정확하게 동작한다.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL AlarmDescription JSON 메타데이터의 `resource_id` 필드에 항상 Full_ARN을 저장한다 (Short_ID가 아닌 원본 값)
2. WHEN 알람 동기화(`sync_alarms_for_resource`)를 수행하면, THE Alarm_Manager SHALL 메타데이터의 `resource_id`로 알람을 매칭한다 (알람 이름 문자열 매칭 금지, 거버넌스 §6)

### Requirement 5: Short_ID 추출 함수와 기존 디멘션 추출 함수의 관계

**User Story:** As a 개발자, I want Short_ID 추출 로직이 기존 `_extract_elb_dimension()`과 중복되지 않길 원한다, so that 코드 중복이 최소화되고 유지보수가 용이하다.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL Short_ID 추출을 위한 별도 함수 `_shorten_elb_resource_id()`를 제공한다
2. THE `_shorten_elb_resource_id()` SHALL `_extract_elb_dimension()`과 독립적으로 동작한다 (디멘션 값과 Short_ID는 포맷이 다름: 디멘션은 `app/name/hash` 또는 `targetgroup/name/hash`, Short_ID는 `name/hash`)
3. FOR ALL 유효한 ALB/NLB/TG ARN에 대해, `_shorten_elb_resource_id()`를 적용한 후 다시 적용하면 동일한 결과를 반환한다 (멱등성)
