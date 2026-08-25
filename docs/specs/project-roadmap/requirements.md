# Requirements Document — 프로젝트 로드맵

## Introduction

AWS Monitoring Engine 프로젝트의 미완료 스펙, 테스트 갭, Known Issues를 종합 분석하여
우선순위 기반 실행 로드맵을 수립한다. 전체 35개 스펙 중 17개 완료(100%), 14개 진행 중,
3개 미착수 상태이며 전체 태스크 기준 약 78%가 완료되었다.

## Glossary

- **Phase**: 논리적 실행 단위. 선행 Phase 완료 후 다음 Phase를 시작한다.
- **Quick Win**: 5분~30분 내 완료 가능한 소규모 블로커 해소 작업.
- **PBT**: Property-Based Testing (Hypothesis/fast-check). 정합성 검증용.
- **Test Gap**: 프로덕션 모듈에 대응하는 테스트가 없는 상태.
- **Backend Wiring**: 프론트엔드 Mock API를 실제 Lambda API로 교체하는 작업.
- **Golden Signal**: SRE 4대 시그널 (Latency/Traffic/Errors/Saturation).

---

## Requirements

### Requirement 1: 테스트 안정성 확보 (Foundation)

**User Story:** As a 개발자, I want 핵심 비즈니스 로직 모듈에 테스트가 존재하여, so that 리팩터링이나 기능 추가 시 리그레션을 즉시 감지할 수 있다.

#### Acceptance Criteria

1. WHEN alarm_builder.py가 수정되면, THE 테스트 스위트 SHALL 알람 생성 로직의 정합성을 검증한다.
2. WHEN alarm_naming.py가 수정되면, THE 테스트 스위트 SHALL 이름 포맷/truncate/파싱 규칙을 검증한다.
3. WHEN dimension_builder.py가 수정되면, THE 테스트 스위트 SHALL 리소스 유형별 디멘션 조합을 검증한다.
4. WHEN threshold_resolver.py가 수정되면, THE 테스트 스위트 SHALL 3단계 폴백(태그→환경변수→기본값) + 단위 환산을 검증한다.
5. THE pytest 설정 SHALL coverage 리포트를 생성하고, common/ 모듈의 커버리지가 80% 이상이어야 한다.

### Requirement 2: 백엔드 → 프론트엔드 통합 (Core)

**User Story:** As a 클라우드 운영자, I want 프론트엔드 UI에서 실제 AWS 리소스/알람 데이터를 조회하고 변경하고 싶다, so that 콘솔에 접속하지 않고도 모니터링 설정을 관리할 수 있다.

#### Acceptance Criteria

1. WHEN 사용자가 Dashboard 페이지에 접속하면, THE api_handler Lambda SHALL DynamoDB와 CloudWatch에서 데이터를 조회하여 반환한다.
2. WHEN 사용자가 벌크 모니터링 토글을 실행하면, THE SQS Worker Lambda SHALL 비동기로 알람 생성/삭제를 처리한다.
3. WHEN 사용자가 Settings에서 고객사/어카운트를 CRUD하면, THE api_handler SHALL DynamoDB에 반영한다.
4. THE CloudFormation 템플릿 SHALL DynamoDB 테이블, SQS FIFO 큐, API Gateway, Lambda를 프로비저닝한다.
5. THE 프론트엔드 SHALL Mock API 대신 실제 API Gateway 엔드포인트를 호출한다.

### Requirement 3: E2E 테스트 완성 (Validation)

**User Story:** As a 개발자, I want 모든 리소스 타입에 대해 E2E 검증이 가능하도록, so that 배포 전 엔진 전체 동작을 확인할 수 있다.

#### Acceptance Criteria

1. WHEN remaining-resources-e2e-test CFN 스택이 배포되면, THE 8개 리소스 타입 SHALL 생성되고 Monitoring=on 태그가 부착된다.
2. WHEN 트래픽 생성 스크립트가 실행되면, THE 모든 Phase(1~5) SHALL 정상 완료되고 메트릭이 발행된다.
3. WHEN daily_monitor가 실행되면, THE 알람 SHALL 모든 리소스 타입에 대해 올바르게 생성된다.

### Requirement 4: 미완료 PBT 보강 (Quality)

**User Story:** As a 개발자, I want 태그 기반 동적 알람과 확장 리소스 모니터링의 PBT가 완성되어, so that 속성 기반 정합성이 수학적으로 검증된다.

#### Acceptance Criteria

1. THE tag-driven-alarm-engine SHALL Property 1~8에 대한 PBT가 작성되어 통과한다.
2. THE extended-resource-monitoring SHALL 설계 문서의 10개 Correctness Property에 대한 PBT가 통과한다.
3. THE alarm-manager-frontend-features SHALL 10개 PBT 속성 테스트가 통과한다.

### Requirement 5: Known Issues 해소 및 미착수 스펙 설계 (Enhancement)

**User Story:** As a 운영자, I want 동적 알람의 방향 제한(KI-009)이 해소되고 글로벌 서비스 알림이 동작하길 원한다, so that 모니터링 커버리지에 빈틈이 없다.

#### Acceptance Criteria

1. WHEN `Threshold_LT_{MetricName}` 태그가 설정되면, THE 동적 알람 SHALL `LessThanThreshold` 비교 연산자를 사용한다.
2. WHEN CloudFront/Route53 알람이 ALARM 상태가 되면, THE us-east-1 SNS 토픽 SHALL 알림을 발송한다.
3. WHEN metric-key-rename이 적용되면, THE 모든 내부 키 SHALL CloudWatch metric_name과 일치하고 레거시 호환이 유지된다.
