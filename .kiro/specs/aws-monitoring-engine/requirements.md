# Requirements Document

## Introduction

AWS 리소스(EC2, RDS, ELB) 모니터링 자동화 엔진(Headless 버전)이다.
UI나 DB 없이 AWS 태그(Tags)만을 기준으로 동작하는 경량 서버리스 아키텍처로,
EventBridge Scheduler와 Lambda를 조합하여 1일 1회 정기 모니터링, 태그 기반 동적 임계치 알림,
CloudTrail 이벤트 기반 무단 변경 실시간 감지 및 자동 복구(Auto-Remediation)를 수행한다.
단일 SAM template.yaml로 배포 가능하며, 향후 DB/UI 확장을 고려한 모듈화 구조를 갖는다.

## Glossary

- **Monitoring_Engine**: 본 시스템 전체를 지칭하는 이름
- **Daily_Monitor**: EventBridge Scheduler에 의해 1일 1회 트리거되는 Python Lambda 함수
- **Remediation_Handler**: CloudTrail 이벤트를 수신하여 무단 변경을 처리하는 Python Lambda 함수
- **Tag_Resolver**: 리소스 태그 및 환경 변수에서 설정값(임계치 등)을 읽어오는 모듈 함수
- **Threshold**: 알림 발송 기준이 되는 메트릭 임계치 값. 단위는 메트릭 종류에 따라 퍼센트(%), 카운트(count) 등 다양할 수 있으며, 양의 숫자(정수 또는 실수)로 표현된다.
- **Monitoring_Tag**: 리소스에 부착된 `Monitoring=on` 태그. 이 태그가 있는 리소스만 수집 대상이 됨
- **Threshold_Tag**: 리소스에 부착된 `Threshold_CPU=90` 형식의 태그. 개별 임계치를 지정하며, 값은 단위에 무관하게 양의 숫자(정수 또는 실수)이어야 한다.
- **Default_Threshold**: 환경 변수에 설정된 기본 임계치 값 (예: `DEFAULT_CPU_THRESHOLD=80`). 값은 양의 숫자(정수 또는 실수)로 지정한다.
- **SNS_Notifier**: Amazon SNS를 통해 알림 메시지를 발송하는 모듈 함수
- **Auto_Remediation**: 무단 변경 감지 시 해당 리소스를 자동으로 중지 또는 삭제하는 처리
- **CloudTrail_Event**: AWS CloudTrail이 기록하는 API 호출 이벤트 (리소스 스펙 변경 포함)
- **SAM_Template**: AWS Serverless Application Model 배포 템플릿 (`template.yaml`)
- **Supported_Resource**: 본 시스템이 지원하는 AWS 리소스 유형 (EC2, RDS, ELB)

---

## Requirements

### Requirement 1: 모니터링 대상 리소스 수집

**User Story:** As a 클라우드 운영자, I want Monitoring=on 태그가 있는 리소스만 자동으로 수집하고 싶다, so that 불필요한 리소스를 모니터링 범위에서 제외하고 비용을 절감할 수 있다.

#### Acceptance Criteria

1. WHEN EventBridge Scheduler가 1일 1회 트리거를 발생시키면, THE Daily_Monitor SHALL EC2, RDS, ELB 리소스 중 `Monitoring=on` 태그가 있는 리소스 목록을 수집한다.
2. THE Daily_Monitor SHALL `Monitoring=on` 태그가 없는 리소스를 수집 대상에서 제외한다.
3. WHEN 수집 대상 리소스가 0개인 경우, THE Daily_Monitor SHALL 알림 없이 정상 종료한다.
4. IF AWS API 호출 중 오류가 발생하면, THEN THE Daily_Monitor SHALL 오류 내용을 CloudWatch Logs에 기록하고 SNS_Notifier를 통해 운영자에게 알림을 발송한다.
5. WHEN Daily_Monitor가 수집한 리소스가 이미 삭제되었거나 존재하지 않는 경우, THE Daily_Monitor SHALL 해당 리소스를 수집 대상에서 제외하고 CloudWatch Logs에 기록한다.

---

### Requirement 2: 태그 기반 동적 임계치 적용

**User Story:** As a 클라우드 운영자, I want 리소스별로 개별 임계치를 태그로 지정하고 싶다, so that 리소스 특성에 맞는 세밀한 모니터링 기준을 적용할 수 있다.

#### Acceptance Criteria

1. WHEN Tag_Resolver가 리소스의 임계치를 조회할 때, THE Tag_Resolver SHALL 해당 리소스에 `Threshold_CPU`, `Threshold_Memory`, `Threshold_Connections` 태그가 존재하면 해당 태그 값을 임계치로 사용한다.
2. WHEN Tag_Resolver가 리소스의 임계치를 조회할 때, IF 해당 리소스에 임계치 태그가 없으면, THEN THE Tag_Resolver SHALL 환경 변수(`DEFAULT_CPU_THRESHOLD`, `DEFAULT_MEMORY_THRESHOLD`, `DEFAULT_CONNECTIONS_THRESHOLD`)에 설정된 기본값을 임계치로 사용한다.
3. THE Tag_Resolver SHALL 임계치 태그 값이 유효한 양의 숫자(정수 또는 실수)가 아닌 경우 해당 태그를 무효로 처리하고 기본값을 사용한다.
4. THE Tag_Resolver SHALL 설정값을 읽어오는 로직을 독립된 함수로 분리하여 Daily_Monitor 및 Remediation_Handler 양쪽에서 재사용 가능하도록 제공한다.
5. THE Tag_Resolver SHALL 어떤 경우에도 유효한 임계치 값을 반환해야 하며, 태그 값과 환경 변수 기본값 모두 사용할 수 없는 경우 시스템 하드코딩 기본값(CPU: 80, Memory: 80, Connections: 100)을 최종 폴백으로 사용한다.

---

### Requirement 3: 임계치 초과 알림 발송

**User Story:** As a 클라우드 운영자, I want 리소스 메트릭이 임계치를 초과하면 즉시 알림을 받고 싶다, so that 장애 발생 전에 선제적으로 대응할 수 있다.

#### Acceptance Criteria

1. WHEN Daily_Monitor가 수집한 리소스의 메트릭이 Tag_Resolver가 반환한 임계치를 초과하면, THE SNS_Notifier SHALL 리소스 ID, 리소스 유형, 메트릭 이름, 현재 값, 임계치 값을 포함한 알림 메시지를 SNS 토픽으로 발송한다.
2. THE SNS_Notifier SHALL 알림 메시지를 JSON 형식으로 구성한다.
3. WHEN 단일 실행 주기에서 복수의 리소스가 임계치를 초과하면, THE SNS_Notifier SHALL 각 리소스에 대해 개별 알림을 발송한다.
4. IF SNS 발송 중 오류가 발생하면, THEN THE SNS_Notifier SHALL 오류 내용을 CloudWatch Logs에 기록하고 나머지 리소스에 대한 처리를 계속 진행한다.
5. WHEN CloudWatch 메트릭 조회 결과 데이터가 없거나 InsufficientData 상태인 경우, THE Daily_Monitor SHALL 해당 리소스에 대한 임계치 비교 및 알림 발송을 건너뛰고 CloudWatch Logs에 기록한다.

---

### Requirement 4: 무단 변경 실시간 감지

**User Story:** As a 보안 운영자, I want 승인되지 않은 리소스 스펙 변경을 실시간으로 감지하고 싶다, so that 보안 정책 위반을 즉시 인지하고 대응할 수 있다.

#### Acceptance Criteria

1. WHEN CloudTrail이 EC2, RDS, ELB 리소스의 스펙 변경 API 이벤트(예: `ModifyInstanceAttribute`, `ModifyDBInstance`, `ModifyLoadBalancerAttributes`)를 기록하면, THE Remediation_Handler SHALL EventBridge 규칙을 통해 해당 이벤트를 수신한다.
2. WHEN Remediation_Handler가 변경 이벤트를 수신하면, THE Remediation_Handler SHALL 변경된 리소스에 `Monitoring=on` 태그가 있는지 확인한다.
3. WHEN 변경된 리소스에 `Monitoring=on` 태그가 없는 경우, THE Remediation_Handler SHALL 해당 이벤트를 무시하고 정상 종료한다.
4. IF CloudTrail 이벤트 파싱 중 오류가 발생하면, THEN THE Remediation_Handler SHALL 오류 내용을 CloudWatch Logs에 기록하고 SNS_Notifier를 통해 운영자에게 알림을 발송한다.

---

### Requirement 5: 무단 변경 자동 복구 (Auto-Remediation)

**User Story:** As a 보안 운영자, I want Monitoring=on 태그가 있는 리소스의 무단 변경이 감지되면 자동으로 복구 조치가 취해지기를 원한다, so that 수동 개입 없이 보안 정책을 강제 적용할 수 있다.

#### Acceptance Criteria

1. WHEN Remediation_Handler가 `Monitoring=on` 태그가 있는 리소스의 무단 변경을 확인하면, THE Remediation_Handler SHALL 리소스 유형에 따라 EC2는 중지(stop), RDS는 중지(stop), ELB는 삭제(delete) 처리를 수행한다.
2. WHEN Auto_Remediation 처리가 완료되면, THE SNS_Notifier SHALL 리소스 ID, 리소스 유형, 감지된 변경 내용, 수행된 조치를 포함한 알림 메시지를 SNS 토픽으로 발송한다.
3. IF Auto_Remediation 처리 중 오류가 발생하면, THEN THE Remediation_Handler SHALL 오류 내용을 CloudWatch Logs에 기록하고 SNS_Notifier를 통해 운영자에게 즉시 알림을 발송한다.
4. THE Remediation_Handler SHALL Auto_Remediation 수행 전 CloudWatch Logs에 리소스 ID, 변경 이벤트 요약, 수행 예정 조치를 기록한다.

---

### Requirement 6: 모듈화 코드 구조

**User Story:** As a 개발자, I want 코드가 기능별로 모듈화되어 있기를 원한다, so that 향후 DB나 UI가 추가될 때 기존 코드를 최소한으로 수정하여 확장할 수 있다.

#### Acceptance Criteria

1. THE Monitoring_Engine SHALL Tag_Resolver, SNS_Notifier, 리소스별 수집 로직(EC2Collector, RDSCollector, ELBCollector)을 각각 독립된 Python 모듈로 분리한다.
2. THE Tag_Resolver SHALL 설정값 소스(태그 또는 환경 변수)를 추상화하여, 향후 DB나 외부 설정 서비스로 교체할 수 있는 인터페이스를 제공한다.
3. THE Monitoring_Engine SHALL Daily_Monitor와 Remediation_Handler가 공통 모듈을 임포트하여 사용하는 구조로 구성된다.
4. THE Monitoring_Engine SHALL 각 Lambda 함수의 핸들러 파일이 비즈니스 로직을 직접 포함하지 않고 공통 모듈을 호출하는 방식으로 구현된다.

---

### Requirement 7: 단일 SAM 템플릿 배포

**User Story:** As a DevOps 엔지니어, I want 단일 template.yaml 파일로 전체 인프라를 배포하고 싶다, so that 배포 절차를 단순화하고 인프라를 코드로 관리할 수 있다.

#### Acceptance Criteria

1. THE SAM_Template SHALL Daily_Monitor Lambda, Remediation_Handler Lambda, EventBridge Scheduler, EventBridge 규칙(CloudTrail 이벤트), SNS 토픽을 단일 `template.yaml` 파일에 정의한다.
2. THE SAM_Template SHALL Default_Threshold 값들을 SAM 파라미터 또는 환경 변수로 정의하여 배포 시 재정의 가능하도록 한다.
3. THE SAM_Template SHALL Lambda 실행에 필요한 IAM 역할 및 최소 권한 정책을 포함한다.
4. WHEN `sam deploy` 명령을 실행하면, THE SAM_Template SHALL 추가적인 수동 설정 없이 전체 시스템이 배포 완료되어야 한다.

---

### Requirement 8: 리소스 생명주기 및 태그 변경 추적

**User Story:** As a 클라우드 운영자, I want Monitoring=on 태그가 있는 리소스의 삭제 및 태그 변경을 실시간으로 추적하고 싶다, so that 모니터링 대상 리소스의 생명주기 변화를 즉시 인지하고 대응할 수 있다.

#### Acceptance Criteria

1. WHEN CloudTrail이 EC2 `TerminateInstances`, RDS `DeleteDBInstance`, ELB `DeleteLoadBalancer` 이벤트를 기록하면, THE Remediation_Handler SHALL EventBridge 규칙을 통해 해당 이벤트를 수신한다.
2. WHEN Remediation_Handler가 리소스 삭제 이벤트를 수신하고 삭제된 리소스에 `Monitoring=on` 태그가 있었다면, THE SNS_Notifier SHALL "Monitoring=on 리소스가 삭제됨" 내용을 포함한 알림 메시지를 SNS 토픽으로 발송한다.
3. WHEN Remediation_Handler가 리소스 삭제 이벤트를 수신하고 삭제된 리소스에 `Monitoring=on` 태그가 없었다면, THE Remediation_Handler SHALL 해당 이벤트를 무시하고 정상 종료한다.
4. WHEN CloudTrail이 `CreateTags` 또는 `DeleteTags` 이벤트를 기록하면, THE Remediation_Handler SHALL EventBridge 규칙을 통해 해당 이벤트를 수신한다.
5. WHEN Remediation_Handler가 `DeleteTags` 이벤트를 수신하고 `Monitoring=on` 태그가 제거된 것을 확인하면, THE SNS_Notifier SHALL "모니터링 대상에서 제외됨" 내용을 포함한 알림 메시지를 SNS 토픽으로 발송한다.
6. WHEN Remediation_Handler가 `CreateTags` 이벤트를 수신하고 `Monitoring=on` 태그가 추가된 것을 확인하면, THE Remediation_Handler SHALL "모니터링 대상에 추가됨" 내용을 CloudWatch Logs에 기록한다.
7. IF 삭제 이벤트 또는 태그 변경 이벤트 파싱 중 오류가 발생하면, THEN THE Remediation_Handler SHALL 오류 내용을 CloudWatch Logs에 기록하고 SNS_Notifier를 통해 운영자에게 알림을 발송한다.
