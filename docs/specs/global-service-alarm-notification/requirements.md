# Requirements Document

## Introduction

CloudFront/Route53 같은 글로벌 서비스의 CloudWatch 알람은 us-east-1에서만 생성 가능하다.
현재 `alarm_builder.py`에서 글로벌 서비스 알람 생성 시 크로스 리전 SNS 제약으로 인해 `AlarmActions`를 비워두는 임시 처리가 되어 있어, 알람 상태가 변경되어도 알림이 전송되지 않는다.

이 기능은 us-east-1에 전용 SNS 토픽을 생성하고, AWS Chatbot을 통해 기존 서울 리전 알림과 동일한 Slack 채널로 알림을 전달하는 파이프라인을 구성한다.
기존 서울 리전(ap-northeast-2) 알림 파이프라인에는 영향을 주지 않는다.

## Glossary

- **Monitoring_Engine**: CloudWatch 알람 자동 생성/동기화 전체 시스템
- **Global_Service_Alarm**: CloudFront/Route53 등 us-east-1에서만 메트릭이 발행되는 글로벌 서비스의 CloudWatch 알람
- **Global_SNS_Topic**: us-east-1에 생성되는 알람 알림 전용 SNS 토픽
- **Seoul_SNS_Topic**: ap-northeast-2(서울)에 존재하는 기존 알람 알림 SNS 토픽 (MonitoringAlertTopic)
- **Alarm_Builder**: CloudWatch put_metric_alarm을 호출하여 알람을 생성하는 모듈
- **Chatbot_Configuration**: AWS Chatbot의 Slack 채널 연동 설정 (SNS 토픽 구독 포함)
- **CustomResource_Lambda**: CloudFormation에서 크로스 리전 리소스를 생성하기 위한 Lambda 함수
- **_GLOBAL_SERVICE_REGION**: alarm_registry.py에 정의된 글로벌 서비스 리전 매핑 딕셔너리

## Requirements

### Requirement 1: us-east-1 SNS 토픽 생성

**User Story:** As a 운영자, I want us-east-1에 알람 알림 전용 SNS 토픽이 존재하길 원한다, so that 글로벌 서비스 알람의 AlarmActions에 유효한 SNS ARN을 지정할 수 있다.

#### Acceptance Criteria

1. THE template.yaml SHALL CustomResource_Lambda를 정의하여 us-east-1에 Global_SNS_Topic을 생성한다
2. THE CustomResource_Lambda SHALL CloudFormation Create 요청 시 us-east-1에 SNS 토픽을 생성하고, 토픽 ARN을 응답 Data에 포함한다
3. THE CustomResource_Lambda SHALL CloudFormation Delete 요청 시 us-east-1의 SNS 토픽을 삭제한다
4. IF CustomResource_Lambda의 Delete 핸들러에서 에러가 발생하면, THEN THE CustomResource_Lambda SHALL SUCCESS를 반환하여 스택 삭제가 블로킹되지 않도록 한다
5. THE CustomResource_Lambda SHALL CloudFormation Update 요청 시 기존 토픽을 유지하고 ARN을 반환한다
6. THE Global_SNS_Topic SHALL 토픽 이름에 Environment 파라미터 기반 접미사를 포함한다 (예: `aws-monitoring-engine-global-alert-prod`)

### Requirement 2: Lambda 환경변수에 us-east-1 SNS ARN 전달

**User Story:** As a 개발자, I want Lambda 함수가 us-east-1 SNS 토픽 ARN을 환경변수로 참조할 수 있길 원한다, so that alarm_builder가 글로벌 서비스 알람 생성 시 올바른 SNS ARN을 사용할 수 있다.

#### Acceptance Criteria

1. THE template.yaml SHALL CustomResource의 응답에서 Global_SNS_Topic ARN을 추출하여 DailyMonitorFunction의 환경변수 `SNS_TOPIC_ARN_GLOBAL_ALERT`에 설정한다
2. THE template.yaml SHALL CustomResource의 응답에서 Global_SNS_Topic ARN을 추출하여 RemediationHandlerFunction의 환경변수 `SNS_TOPIC_ARN_GLOBAL_ALERT`에 설정한다
3. THE Monitoring_Engine SHALL `SNS_TOPIC_ARN_GLOBAL_ALERT` 환경변수가 비어있거나 미설정인 경우에도 정상 동작한다 (알림 없이 알람만 생성)

### Requirement 3: alarm_builder 글로벌 서비스 AlarmActions 연결

**User Story:** As a 운영자, I want 글로벌 서비스 알람의 AlarmActions에 us-east-1 SNS 토픽이 설정되길 원한다, so that 알람 상태 변경 시 알림이 전송된다.

#### Acceptance Criteria

1. WHEN alarm_builder가 글로벌 서비스 알람을 생성할 때, THE Alarm_Builder SHALL `SNS_TOPIC_ARN_GLOBAL_ALERT` 환경변수에서 us-east-1 SNS ARN을 조회하여 AlarmActions와 OKActions에 설정한다
2. THE Alarm_Builder SHALL `_create_standard_alarm` 함수에서 region 필드가 있는 알람 정의에 대해 기존 `sns_arn = ""` 임시 처리를 제거하고 Global_SNS_Topic ARN을 사용한다
3. THE Alarm_Builder SHALL `_recreate_standard_alarm` 함수에서도 글로벌 서비스 알람 재생성 시 Global_SNS_Topic ARN을 AlarmActions에 설정한다
4. IF `SNS_TOPIC_ARN_GLOBAL_ALERT` 환경변수가 비어있으면, THEN THE Alarm_Builder SHALL AlarmActions를 빈 리스트로 설정한다 (기존 동작 유지)
5. THE Alarm_Builder SHALL 서울 리전 알람의 AlarmActions에는 기존 Seoul_SNS_Topic ARN을 그대로 사용한다 (기존 동작 변경 없음)

### Requirement 4: AWS Chatbot Slack 연동

**User Story:** As a 운영자, I want us-east-1 SNS 토픽의 알림이 기존 서울 알림과 동일한 Slack 채널로 전달되길 원한다, so that 글로벌 서비스 알람도 통합된 채널에서 확인할 수 있다.

#### Acceptance Criteria

1. THE Chatbot_Configuration SHALL us-east-1 Global_SNS_Topic을 구독하여 Slack 채널로 알림을 전달한다
2. THE Chatbot_Configuration SHALL 기존 Seoul_SNS_Topic 구독과 동일한 Slack 워크스페이스 및 채널을 사용한다
3. THE Chatbot_Configuration SHALL AWS Chatbot의 SNS 토픽 구독 목록에 Global_SNS_Topic ARN을 추가한다
4. THE Chatbot_Configuration SHALL 기존 Seoul_SNS_Topic 구독에 영향을 주지 않는다

### Requirement 5: IAM 권한

**User Story:** As a 개발자, I want Lambda 함수가 us-east-1 SNS 토픽에 대한 Publish 권한을 갖길 원한다, so that 글로벌 서비스 알람의 AlarmActions가 정상 동작한다.

#### Acceptance Criteria

1. THE template.yaml SHALL DailyMonitorFunction IAM Role에 Global_SNS_Topic에 대한 sns:Publish 권한을 추가한다
2. THE template.yaml SHALL RemediationHandlerFunction IAM Role에 Global_SNS_Topic에 대한 sns:Publish 권한을 추가한다
3. THE CustomResource_Lambda SHALL sns:CreateTopic, sns:DeleteTopic, sns:GetTopicAttributes 권한을 가진 IAM Role을 사용한다
4. THE CustomResource_Lambda IAM Role SHALL us-east-1 리전의 SNS 리소스에 대해서만 권한을 부여한다

### Requirement 6: 기존 파이프라인 무영향

**User Story:** As a 운영자, I want 이 변경이 기존 서울 리전 알림 파이프라인에 영향을 주지 않길 원한다, so that 기존 EC2/RDS/ELB 등의 알람 알림이 정상 동작한다.

#### Acceptance Criteria

1. THE Alarm_Builder SHALL 서울 리전 알람 생성 시 기존 `_get_sns_alert_arn()` 함수를 그대로 사용한다
2. THE Alarm_Builder SHALL `_create_dynamic_alarm` 함수의 동작을 변경하지 않는다 (동적 알람은 서울 리전에서만 생성)
3. THE template.yaml SHALL 기존 MonitoringAlertTopic, RemediationAlertTopic, LifecycleAlertTopic, ErrorAlertTopic의 정의를 변경하지 않는다
4. THE Monitoring_Engine SHALL `_GLOBAL_SERVICE_REGION` 매핑에 정의되지 않은 리소스 타입에 대해 기존 동작을 유지한다

### Requirement 7: CustomResource Lambda 안정성

**User Story:** As a 개발자, I want CustomResource Lambda가 안정적으로 동작하여 스택 배포/삭제가 실패하지 않길 원한다, so that 운영 안정성이 보장된다.

#### Acceptance Criteria

1. THE CustomResource_Lambda SHALL 모든 요청 타입(Create, Update, Delete)에 대해 CloudFormation 응답 URL로 결과를 전송한다
2. IF CustomResource_Lambda에서 예외가 발생하면, THEN THE CustomResource_Lambda SHALL FAILED 상태와 에러 메시지를 CloudFormation에 응답한다 (Delete 제외)
3. IF CustomResource_Lambda의 Delete 핸들러에서 예외가 발생하면, THEN THE CustomResource_Lambda SHALL SUCCESS를 반환한다
4. THE CustomResource_Lambda SHALL 생성한 SNS 토픽 ARN을 PhysicalResourceId로 사용하여 Update/Delete 시 동일 리소스를 참조한다
5. THE CustomResource_Lambda SHALL Python 3.12 런타임과 인라인 코드(ZipFile)로 구현한다 (기존 InitialSyncFunction 패턴 준용)
