# 요구사항 문서: LB/TG 알람 테스트 인프라

## 소개

aws-alert-manager 프로젝트의 ALB/NLB/Target Group 메트릭 수집 및 CloudWatch 알람 자동 생성 동작을 실제 AWS 환경에서 검증하기 위한 독립형 테스트 인프라.
기존 운영 코드(`common/`, `daily_monitor/`, `template.yaml`)를 일절 수정하지 않고, 별도 CloudFormation 스택으로 배포·삭제 가능한 임시 테스트 환경을 구성한다.

### 핵심 목적
1. ALB/NLB LB 레벨 하드코딩·동적 알람 생성 동작 검증
2. TG 레벨 메트릭 존재 확인 및 알람 자동 생성 미지원 범위 명시적 확인
3. EC2 기본 알람 생성 동작 부수 검증

### 정직성 원칙
- TG 알람 자동 생성은 현재 미구현 상태이며, 테스트 인프라는 이 사실을 명시적으로 확인하는 용도로 포함한다.
- "동작함"과 "미구현/갭"을 명확히 분리하여 문서화한다.
- 추측이 아닌 실제 코드 분석 기반으로 예상 결과를 기술한다.

## 용어 정의

- **Test_Stack**: 이 요구사항에서 생성하는 독립형 CloudFormation 스택
- **Test_CFN_Template**: Test_Stack을 정의하는 CloudFormation 템플릿 파일
- **Test_EC2**: Test_Stack 내 HTTP 백엔드 역할의 EC2 인스턴스
- **Test_ALB**: Test_Stack 내 Application Load Balancer
- **Test_NLB**: Test_Stack 내 Network Load Balancer
- **Test_ALB_TG**: Test_ALB에 연결된 Target Group
- **Test_NLB_TG**: Test_NLB에 연결된 Target Group
- **Alarm_Engine**: 기존 aws-alert-manager의 Daily Monitor Lambda (알람 자동 생성 엔진)
- **Deploy_Script**: Test_Stack 배포용 셸 스크립트
- **Delete_Script**: Test_Stack 삭제용 셸 스크립트
- **Verification_Doc**: 검증 절차 및 예상 결과를 기술한 문서
- **Infra_Test_Dir**: 테스트 인프라 파일이 위치하는 디렉터리 (`infra-test/lb-tg-alarm-lab/`)

## 요구사항

### 요구사항 1: 프로젝트 격리

**사용자 스토리:** 인프라 엔지니어로서, 테스트 인프라가 기존 운영 코드와 완전히 분리되기를 원한다. 그래야 운영 환경에 영향 없이 안전하게 테스트할 수 있다.

#### 인수 조건

1. THE Test_CFN_Template SHALL 위치를 Infra_Test_Dir 내부로 한정한다
2. THE Test_Stack SHALL 기존 `template.yaml` 스택과 독립적으로 배포 및 삭제가 가능하다
3. THE Test_Stack SHALL 기존 운영 코드 파일(`common/`, `daily_monitor/`, `remediation_handler/`, `template.yaml`)을 수정하지 않는다
4. THE Test_Stack SHALL 모든 리소스에 `Project=lb-tg-alarm-lab` 태그를 부착하여 테스트 리소스임을 식별 가능하게 한다
5. THE Test_Stack SHALL 스택 이름에 `lb-tg-alarm-lab` 접두사를 사용하여 운영 스택과 구분한다

### 요구사항 2: CloudFormation 템플릿 설계

**사용자 스토리:** 인프라 엔지니어로서, 순수 CloudFormation 템플릿으로 테스트 환경을 정의하고 싶다. 그래야 SAM 없이도 일관된 배포가 가능하다.

#### 인수 조건

1. THE Test_CFN_Template SHALL 순수 CloudFormation(AWSTemplateFormatVersion 2010-09-09)으로 작성한다 (SAM 미사용)
2. THE Test_CFN_Template SHALL VPC ID, Subnet ID, KeyPair 이름, AMI ID, 허용 IP CIDR을 Parameters로 받는다 (하드코딩 금지)
3. THE Test_CFN_Template SHALL 파라미터 기본값 예시 파일(`parameters.example.json`)을 함께 제공한다
4. THE Test_CFN_Template SHALL 모든 리소스에 대해 `DeletionPolicy`를 명시하지 않거나 `Delete`로 설정하여 스택 삭제 시 리소스가 완전히 제거되도록 한다
5. WHEN 필수 파라미터가 누락된 경우, THE Test_CFN_Template SHALL CloudFormation 검증 단계에서 명확한 오류 메시지를 반환한다

### 요구사항 3: EC2 백엔드 인스턴스

**사용자 스토리:** 인프라 엔지니어로서, ALB/NLB의 Target Group에 등록할 HTTP 백엔드 EC2 인스턴스가 필요하다. 그래야 헬스체크와 메트릭 수집이 동작한다.

#### 인수 조건

1. THE Test_CFN_Template SHALL 최소 1개의 Test_EC2 인스턴스를 생성한다
2. THE Test_EC2 SHALL 최소 사양(t3.micro 또는 t2.micro)으로 생성한다
3. THE Test_EC2 SHALL UserData를 통해 포트 80에서 HTTP 응답을 반환하는 간단한 웹 서버를 실행한다
4. THE Test_EC2 SHALL `Monitoring=on` 태그를 부착한다
5. THE Test_EC2 SHALL `Threshold_CPU` 태그를 부착하여 Alarm_Engine의 EC2 알람 생성을 검증할 수 있게 한다
6. THE Test_EC2 SHALL Security Group을 통해 ALB/NLB로부터의 HTTP(80) 트래픽과 지정된 IP의 SSH(22) 트래픽만 허용한다

### 요구사항 4: ALB 및 Target Group 구성

**사용자 스토리:** 인프라 엔지니어로서, ALB와 Target Group을 생성하여 ALB 레벨 메트릭 알람 생성과 TG 레벨 메트릭 존재를 검증하고 싶다.

#### 인수 조건

1. THE Test_CFN_Template SHALL 1개의 Test_ALB를 생성한다
2. THE Test_ALB SHALL `Monitoring=on` 태그를 부착한다
3. THE Test_ALB SHALL `Threshold_RequestCount` 태그를 부착하여 동적 알람 생성을 검증할 수 있게 한다
4. THE Test_CFN_Template SHALL Test_ALB에 연결된 1개의 Test_ALB_TG를 생성한다
5. THE Test_ALB_TG SHALL HTTP 프로토콜, 포트 80, 헬스체크 경로 `/`로 구성한다
6. THE Test_ALB_TG SHALL Test_EC2를 타겟으로 등록한다
7. THE Test_ALB SHALL 포트 80 HTTP Listener를 통해 Test_ALB_TG로 트래픽을 전달한다
8. THE Test_ALB_TG SHALL `Monitoring=on` 태그를 부착한다
9. THE Test_ALB_TG SHALL `Threshold_RequestCount` 태그를 부착하여 TG 레벨 동적 알람 시도를 검증할 수 있게 한다

### 요구사항 5: NLB 및 Target Group 구성

**사용자 스토리:** 인프라 엔지니어로서, NLB와 Target Group을 생성하여 NLB 레벨 동적 메트릭 알람과 TG 레벨 메트릭 존재를 검증하고 싶다.

#### 인수 조건

1. THE Test_CFN_Template SHALL 1개의 Test_NLB를 생성한다
2. THE Test_NLB SHALL `Monitoring=on` 태그를 부착한다
3. THE Test_NLB SHALL `Threshold_ProcessedBytes` 태그를 부착하여 NLB 동적 알람 생성을 검증할 수 있게 한다
4. THE Test_NLB SHALL `Threshold_ActiveFlowCount` 태그를 부착하여 복수 동적 메트릭 알람을 검증할 수 있게 한다
5. THE Test_CFN_Template SHALL Test_NLB에 연결된 1개의 Test_NLB_TG를 생성한다
6. THE Test_NLB_TG SHALL TCP 프로토콜, 포트 80, TCP 헬스체크로 구성한다
7. THE Test_NLB_TG SHALL Test_EC2를 타겟으로 등록한다
8. THE Test_NLB SHALL 포트 80 TCP Listener를 통해 Test_NLB_TG로 트래픽을 전달한다
9. THE Test_NLB_TG SHALL `Monitoring=on` 태그를 부착한다
10. THE Test_NLB_TG SHALL `Threshold_HealthyHostCount` 태그를 부착하여 TG 레벨 동적 알람 시도를 검증할 수 있게 한다

### 요구사항 6: 네트워크 보안

**사용자 스토리:** 인프라 엔지니어로서, 테스트 인프라의 네트워크 접근을 최소 권한으로 제한하고 싶다. 그래야 불필요한 보안 위험을 방지할 수 있다.

#### 인수 조건

1. THE Test_CFN_Template SHALL ALB용 Security Group을 생성하여 지정된 IP CIDR에서만 HTTP(80) 인바운드를 허용한다
2. THE Test_CFN_Template SHALL EC2용 Security Group을 생성하여 ALB/NLB Security Group으로부터의 HTTP(80)와 지정된 IP의 SSH(22)만 허용한다
3. THE Test_CFN_Template SHALL 모든 Security Group의 아웃바운드를 0.0.0.0/0 TCP 전체로 허용한다 (패키지 설치 및 헬스체크 응답용)

### 요구사항 7: 배포 및 삭제 스크립트

**사용자 스토리:** 인프라 엔지니어로서, 한 줄 명령으로 테스트 스택을 배포하고 삭제하고 싶다. 그래야 반복 테스트가 편리하다.

#### 인수 조건

1. THE Deploy_Script SHALL AWS CLI SSO 프로필(`bjs`)과 리전(`ap-northeast-2`)을 사용하여 Test_Stack을 배포한다
2. THE Deploy_Script SHALL 파라미터 파일 경로를 인자로 받아 `aws cloudformation deploy` 또는 `create-stack` 명령을 실행한다
3. THE Delete_Script SHALL Test_Stack을 완전히 삭제하는 `aws cloudformation delete-stack` 명령을 실행한다
4. THE Delete_Script SHALL 스택 삭제 완료를 `wait stack-delete-complete`로 확인한다
5. WHEN 배포 또는 삭제가 실패한 경우, THE Deploy_Script 또는 Delete_Script SHALL 오류 메시지를 출력하고 비정상 종료 코드를 반환한다

### 요구사항 8: 검증 절차 문서

**사용자 스토리:** 인프라 엔지니어로서, 배포 후 무엇을 어떻게 검증해야 하는지 명확한 절차서가 필요하다. 그래야 체계적으로 테스트를 수행할 수 있다.

#### 인수 조건

1. THE Verification_Doc SHALL 검증 시나리오별로 수행 절차, 확인 명령어(AWS CLI), 예상 결과를 기술한다
2. THE Verification_Doc SHALL 다음 5개 시나리오를 포함한다: (a) EC2 기본 알람 생성, (b) ALB LB 레벨 알람 생성, (c) NLB LB 레벨 동적 메트릭 알람 검증, (d) TG 메트릭 존재 및 디멘션 확인, (e) TG 알람 자동 생성 미지원 확인
3. THE Verification_Doc SHALL 각 시나리오의 예상 결과를 "현재 동작함" 또는 "미구현(갭)"으로 명확히 분류한다
4. THE Verification_Doc SHALL 예상 알람 결과 테이블을 포함한다 (리소스, 메트릭, 알람 생성 여부, 사유)
5. THE Verification_Doc SHALL TG 알람 미지원 사유를 코드 레벨에서 설명한다 (`_get_alarm_defs()`에 TG 정의 없음, `_DIMENSION_KEY_MAP`에 TG 매핑 없음, `_resolve_metric_dimensions()`가 단일 디멘션만 검색)

### 요구사항 9: 태그 설계

**사용자 스토리:** 인프라 엔지니어로서, 각 리소스에 부착할 태그를 사전에 설계하여 Alarm_Engine의 다양한 경로를 검증하고 싶다.

#### 인수 조건

1. THE Verification_Doc SHALL 리소스별 태그 설계 테이블을 포함한다 (리소스명, 태그 키, 태그 값, 검증 목적)
2. THE Test_Stack SHALL 모든 테스트 리소스에 공통 태그를 부착한다: `Monitoring=on`, `Project=lb-tg-alarm-lab`, `Environment=test`
3. THE Test_Stack SHALL EC2에 `Threshold_CPU` 태그를 부착하여 태그 기반 임계치 오버라이드를 검증한다
4. THE Test_Stack SHALL ALB에 `Threshold_RequestCount` 태그를 부착하여 하드코딩 메트릭의 태그 임계치 오버라이드를 검증한다
5. THE Test_Stack SHALL NLB에 `Threshold_ProcessedBytes`와 `Threshold_ActiveFlowCount` 태그를 부착하여 동적 메트릭 알람 생성을 검증한다
6. THE Test_Stack SHALL TG에 `Monitoring=on`과 `Threshold_*` 태그를 부착하여 TG 수집은 되지만 알람 생성은 안 되는 갭을 확인한다

### 요구사항 10: 예상 알람 결과 테이블

**사용자 스토리:** 인프라 엔지니어로서, 배포 후 Alarm_Engine 실행 시 어떤 알람이 생성되고 어떤 것이 생성되지 않는지 사전에 파악하고 싶다.

#### 인수 조건

1. THE Verification_Doc SHALL 다음 컬럼을 포함하는 예상 알람 결과 테이블을 제공한다: 리소스, 리소스 타입, 메트릭, 알람 생성 여부(O/X), 알람 유형(하드코딩/동적), 사유
2. THE Verification_Doc SHALL EC2 하드코딩 알람(CPU, Memory, Disk) 생성을 예상 결과 O로 기술한다
3. THE Verification_Doc SHALL ALB 하드코딩 알람(RequestCount) 생성을 예상 결과 O로 기술한다
4. THE Verification_Doc SHALL NLB 동적 알람(ProcessedBytes, ActiveFlowCount)의 예상 결과를 기술한다 (CloudWatch에 메트릭 데이터 존재 시 O, 미존재 시 X)
5. THE Verification_Doc SHALL TG 알람의 예상 결과를 X로 기술하고, 미지원 사유를 명시한다 (하드코딩 정의 없음, 디멘션 매핑 미지원)
6. THE Verification_Doc SHALL NLB 하드코딩 알람이 없는 이유를 명시한다 (`_ELB_ALARMS`에 `AWS/ApplicationELB` RequestCount만 정의되어 있고 NLB용 정의 없음)
