# Implementation Plan — 프로젝트 로드맵

## Overview

미완료 스펙, 테스트 갭, Known Issues를 5개 Phase로 나누어 실행한다.
전체 약 7주 분량이며, Phase 0~1은 기반 안정화, Phase 2~3은 핵심 기능 완성, Phase 4는 고도화이다.

## Tasks

### Phase 0: Quick Wins (1일)

- [ ] 0. Quick Wins — 블로커 해소 및 인프라 개선

  - [ ] 0.1 remaining-resources-e2e-test Task 10.4 완료
    - `infra-test/` 트래픽 스크립트에 Phase 3 (APIGW HTTP) 순차 curl 20회 추가
    - E2E 스펙: `.kiro/specs/remaining-resources-e2e-test/tasks.md` Task 10.4
    - _예상: 5분_

  - [ ] 0.2 pytest 커버리지 설정 추가
    - `pyproject.toml`에 `[tool.pytest.ini_options]` + `[tool.coverage.run]` 섹션 추가
    - `pytest-cov` 패키지를 `requirements.txt` 개발 의존성에 추가
    - 실행 확인: `pytest tests/ --cov=common --cov-report=term-missing`
    - _예상: 30분_

  - [ ] 0.3 extended-resource-monitoring PBT 마무리
    - `.kiro/specs/extended-resource-monitoring/tasks.md` Task 16의 Correctness Properties 10개 PBT 작성
    - 파일: `tests/test_pbt_extended_resource.py`
    - 전체 테스트 통과 확인: `pytest tests/ -x -q --tb=short`
    - _스펙 완료율: 96% → 100%_
    - _예상: 2시간_

---

### Phase 1: 테스트 갭 해소 (1주)

- [ ] 1. alarm_builder 테스트 작성

  - [ ] 1.1 alarm_builder 단위 테스트
    - 파일: `tests/test_alarm_builder.py`
    - 커버: `_create_standard_alarm()`, `_create_single_alarm()`, `_recreate_standard_alarm()`
    - 케이스: 리전 분기(글로벌 서비스 us-east-1), AlarmActions 구성, TreatMissingData 설정
    - _Requirements: 1.1_

  - [ ] 1.2 alarm_builder PBT
    - 파일: `tests/test_pbt_alarm_builder.py`
    - Property: 알람 파라미터 정합성 (Namespace+MetricName+Dimensions 조합 유효성)
    - Property: AlarmActions가 알람 리전과 동일한 리전의 SNS ARN만 포함
    - _Requirements: 1.1_

- [ ] 2. alarm_naming 테스트 작성

  - [ ] 2.1 alarm_naming PBT
    - 파일: `tests/test_pbt_alarm_naming.py`
    - Property: 생성된 이름이 255자 이하
    - Property: 이름에서 resource_type, metric, threshold 파싱 결과가 원본과 일치 (라운드트립)
    - Property: Short_ID 변환 후 역변환 시 원본 보존
    - Property: truncate 시 `...` 접미사 존재, 핵심 식별자(TagName) 보존
    - _Requirements: 1.2_

- [ ] 3. dimension_builder 테스트 작성

  - [ ] 3.1 dimension_builder 단위 테스트
    - 파일: `tests/test_dimension_builder.py`
    - 커버: 리소스 유형별 디멘션 조합 (EC2, RDS, ALB LB레벨, ALB TG레벨, NLB, CWAgent Disk)
    - 커버: 글로벌 서비스 디멘션 (CloudFront `Region:Global`, WAF `Region`, S3 `FilterId`)
    - 커버: Compound Dimension (TG `TargetGroup+LoadBalancer`)
    - _Requirements: 1.3_

  - [ ] 3.2 dimension_builder PBT
    - 파일: `tests/test_pbt_dimension_builder.py`
    - Property: ALB LB 레벨 메트릭에 TG 디멘션이 포함되지 않음
    - Property: TG 레벨 메트릭에 LoadBalancer 디멘션이 항상 포함됨
    - _Requirements: 1.3_

- [ ] 4. threshold_resolver 테스트 작성

  - [ ] 4.1 threshold_resolver 단위 테스트
    - 파일: `tests/test_threshold_resolver.py`
    - 커버: 3단계 폴백 (태그 → 환경변수 → HARDCODED_DEFAULTS)
    - 커버: 단위 환산 (`multiplier` GB→bytes 1073741824)
    - 커버: 퍼센트 기반 임계치 (`_resolve_free_memory_threshold()`)
    - 커버: `Threshold_off` 태그 처리
    - _Requirements: 1.4_

  - [ ] 4.2 threshold_resolver PBT
    - 파일: `tests/test_pbt_threshold_resolver.py`
    - Property: 태그 값이 존재하면 항상 태그 값이 반환됨 (환경변수/기본값보다 우선)
    - Property: multiplier 적용 후 결과가 원본 × multiplier와 일치
    - _Requirements: 1.4_

- [ ] 5. Lambda handler 직접 unit 테스트

  - [ ] 5.1 daily_monitor handler unit 테스트
    - 파일: `tests/test_daily_monitor_unit.py`
    - moto 기반: EventBridge → Lambda 호출 → collector 실행 → 알람 동기화 → 고아 정리
    - 케이스: 리소스 0개, collector 에러, 부분 실패
    - _Requirements: 1.5_

  - [ ] 5.2 remediation_handler unit 테스트
    - 파일: `tests/test_remediation_handler_unit.py`
    - moto 기반: CloudTrail 이벤트 → 이벤트 매핑 → ARN 변환 → handle_delete/modify
    - 케이스: Aurora 폴백(KI-008), 알 수 없는 이벤트, TagResource/UntagResource
    - _Requirements: 1.5_

  - [ ] 5.3 Checkpoint — 테스트 갭 해소 검증
    - `pytest tests/ --cov=common --cov=daily_monitor --cov=remediation_handler --cov-report=term-missing`
    - common/ 커버리지 80%+ 확인
    - 전체 테스트 통과 확인
    - _Requirements: 1.1~1.5_

---

### Phase 2: 백엔드 API + 인프라 (2주)

- [ ] 6. CloudFormation 리소스 추가

  - [ ] 6.1 DynamoDB 테이블 정의
    - `template.yaml`에 `CustomersTable`, `AccountsTable`, `ThresholdOverridesTable`, `JobStatusTable` 추가
    - 파티션 키, GSI 설계 (customer_id, account_id 기반 조회)
    - 기존 Mappings/Pseudo Parameters 규칙 준수 (AP-13, AP-14)
    - _Spec: alarm-manager-frontend Task 11.1_

  - [ ] 6.2 SQS FIFO 큐 정의
    - `template.yaml`에 `BulkOperationQueue.fifo` 추가
    - DLQ(Dead Letter Queue) 포함, maxReceiveCount=3
    - _Spec: alarm-manager-frontend Task 11.2_

  - [ ] 6.3 API Gateway + Lambda 정의
    - `template.yaml`에 REST API, 리소스/메서드, Lambda 통합 추가
    - CORS 설정, Stage 변수
    - api_handler Lambda 리소스 + IAM 역할
    - sqs_worker Lambda 리소스 + SQS 이벤트 소스 매핑
    - _Spec: alarm-manager-frontend Task 11.3_

- [ ] 7. api_handler Lambda 구현

  - [ ] 7.1 api_handler 기반 모듈 작성
    - `api_handler/lambda_handler.py` — 라우팅 디스패처
    - `api_handler/db_helpers.py` — DynamoDB CRUD 헬퍼 (lru_cache 클라이언트)
    - `api_handler/__init__.py`
    - _Spec: alarm-manager-frontend Task 12.1_

  - [ ] 7.2 Dashboard 라우트 구현
    - `GET /dashboard/stats` — 리소스 수, 알람 수, 상태별 집계
    - `GET /dashboard/recent-alarms` — 최근 ALARM 상태 변경 목록
    - 기존 `common/alarm_search.py`, `common/collectors/` 재활용
    - _Spec: alarm-manager-frontend Task 12.2~12.3_

  - [ ] 7.3 Resources 라우트 구현
    - `GET /resources` — 전체 리소스 목록 (필터: customer, account, type, monitoring)
    - `GET /resources/{id}` — 리소스 상세 + 태그
    - `GET /resources/{id}/alarms` — 리소스별 알람 목록
    - _Spec: alarm-manager-frontend Task 12.4~12.6_

  - [ ] 7.4 Bulk 라우트 구현
    - `POST /bulk/monitoring` — SQS FIFO 큐에 메시지 발행
    - `GET /alarms` — 전체 알람 목록 (필터, 페이지네이션)
    - _Spec: alarm-manager-frontend Task 12.7~12.8_

  - [ ] 7.5 Settings 라우트 구현
    - `CRUD /customers` — 고객사 생성/조회/수정/삭제
    - `CRUD /accounts` — 어카운트 CRUD
    - `CRUD /thresholds` — 임계치 오버라이드 CRUD
    - _Spec: alarm-manager-frontend Task 12.9_

  - [ ] 7.6 api_handler 테스트
    - `tests/test_api_handler.py` — moto + DynamoDB Local 기반 단위 테스트
    - 각 라우트별 정상/에러 케이스
    - 인증/인가 검증 (향후 확장 대비 구조만)
    - _Spec: alarm-manager-frontend Task 13_

- [ ] 8. SQS Worker Lambda 구현

  - [ ] 8.1 sqs_worker 구현
    - `sqs_worker/lambda_handler.py` — SQS 메시지 소비 + alarm_manager 호출
    - job_status DynamoDB 업데이트 (IN_PROGRESS → COMPLETED/FAILED)
    - 에러 시 DLQ 전달 + SNS 에러 알림
    - _Spec: alarm-manager-frontend Task 14.1~14.2_

  - [ ] 8.2 sqs_worker 테스트
    - `tests/test_sqs_worker.py`
    - 정상 처리, 부분 실패, DLQ 전달 케이스
    - _Spec: alarm-manager-frontend Task 14.3_

- [ ] 9. 프론트엔드-백엔드 통합

  - [ ] 9.1 API 클라이언트 교체
    - `frontend/src/lib/api.ts` — Mock 엔드포인트를 `NEXT_PUBLIC_API_ENDPOINT` 기반으로 교체
    - 에러 핸들링, 로딩 상태, 타임아웃 설정
    - _Spec: alarm-manager-frontend Task 15.1~15.2_

  - [ ] 9.2 환경 변수 설정
    - `frontend/.env.local` — `NEXT_PUBLIC_API_ENDPOINT` 설정
    - `frontend/.env.production` — 배포 환경
    - _Spec: alarm-manager-frontend Task 15.3_

  - [ ] 9.3 통합 테스트
    - 프론트엔드 → API Gateway → Lambda → DynamoDB/CloudWatch 전체 흐름 검증
    - Dashboard, Resources, Alarms, Settings 각 페이지
    - _Spec: alarm-manager-frontend Task 15.4~15.5_

  - [ ] 9.4 Checkpoint — 백엔드 통합 검증
    - `pytest tests/ -x -q --tb=short` 전체 통과
    - `cd frontend && npx vitest --run && npx tsc --noEmit`
    - CloudFormation 배포 테스트 (dev 환경)
    - _Spec: alarm-manager-frontend Task 16_

---

### Phase 3: PBT 보강 + E2E 완성 (1주)

- [ ] 10. tag-driven-alarm-engine PBT 보강

  - [ ] 10.1 Property 1~4 PBT 작성
    - Property 1: 태그 값 보존 (Threshold_CPU=90 → 알람 임계치 90)
    - Property 2: off 태그 시 알람 미생성
    - Property 3: 동적 알람 메트릭 키 유일성
    - Property 4: 하드코딩+동적 알람 합집합 정합성
    - 파일: `tests/test_pbt_tag_driven_alarm.py`
    - _Spec: tag-driven-alarm-engine Tasks 1.3, 2.4, 3.3, 5.3_

  - [ ] 10.2 Property 5~8 PBT 작성
    - Property 5: 동적 알람 디멘션 해석 정합성
    - Property 6: CW metric_name 별칭 필터링 (KI-005 방지)
    - Property 7: 임계치 폴백 체인 순서 보존
    - Property 8: 삭제된 태그의 알람 정리
    - _Spec: tag-driven-alarm-engine Tasks 6.4~6.7_

- [ ] 11. alarm-manager-frontend-features PBT 보강

  - [ ] 11.1 속성 테스트 10개 작성
    - API 타입 속성, 필터 파라미터, 토스트, 공통 UI, GlobalFilterBar
    - 동기화 토스트, CSV 내보내기, 벌크 액션, 커스텀 메트릭, 임계치 계층
    - 파일: `frontend/src/**/*.test.tsx` (각 컴포넌트별)
    - _Spec: alarm-manager-frontend-features 미완 태스크_

- [ ] 12. create-alarm-modal 미완 테스트

  - [ ] 12.1 순수 함수 + 컴포넌트 단위 테스트
    - filterAccounts, filterResources, isSubmitEnabled 속성 테스트
    - TrackSelector, ResourceFilterStep, MetricConfigStep 단위 테스트
    - 파일: `frontend/src/components/CreateAlarmModal/__tests__/`
    - _Spec: create-alarm-modal 미완 태스크_

  - [ ] 12.2 모달 통합 테스트
    - CreateAlarmModal 통합, 캐스케이딩 초기화, 재오픈 초기 상태
    - DashboardContent 연동
    - _Spec: create-alarm-modal Tasks 7.3~7.6, 9.2_

- [ ] 13. E2E 테스트 최종 검증

  - [ ] 13.1 remaining-resources-e2e-test 최종 검증
    - Phase 0에서 Task 10.4 완료 → Task 11 최종 CFN 검증
    - AWS 배포 → daily_monitor 실행 → 8개 리소스 타입 알람 생성 확인
    - _Spec: remaining-resources-e2e-test Task 11_

  - [ ] 13.2 Checkpoint — PBT + E2E 완성 검증
    - Python: `pytest tests/ -x -q --tb=short` (PBT 포함 전체 통과)
    - Frontend: `cd frontend && npx vitest --run --coverage`
    - E2E: 스택 배포 → 트래픽 → daily_monitor → 알람 검증 → 스택 삭제

---

### Phase 4: Enhancement (2주)

- [ ] 14. KI-009 동적 알람 방향 해소

  - [ ] 14.1 Threshold_LT_ prefix 설계
    - `.kiro/specs/` 에 `dynamic-alarm-direction/` 스펙 생성 (requirements + design + tasks)
    - `_parse_threshold_tags()`에서 `LT_` prefix 감지 로직 추가
    - `_create_dynamic_alarm()`에서 ComparisonOperator 분기

  - [ ] 14.2 구현 + 테스트
    - `common/alarm_manager.py` 수정
    - PBT: `Threshold_LT_X=Y` → `LessThanThreshold`, `Threshold_X=Y` → `GreaterThanThreshold`
    - 기존 동적 알람 하위 호환 확인
    - KNOWN-ISSUES.md KI-009 상태 → "해결됨" 업데이트

- [ ] 15. global-service-alarm-notification 설계 + 구현

  - [ ] 15.1 Kiro Spec 작성
    - `.kiro/specs/global-service-alarm-notification/` 에 design.md + tasks.md 작성
    - CustomResource Lambda 설계 (us-east-1 SNS 토픽 생성)
    - alarm_builder.py region 필드 + AlarmActions 분기 설계
    - AWS Chatbot 수동 설정 가이드

  - [ ] 15.2 CustomResource Lambda 구현
    - `common/cfn_custom_resource.py` — us-east-1 SNS 토픽 생성/삭제
    - `template.yaml`에 CustomResource 추가
    - 환경 변수: `SNS_TOPIC_ARN_GLOBAL_ALERT`

  - [ ] 15.3 alarm_builder 수정
    - 글로벌 서비스 알람 생성 시 us-east-1 SNS ARN을 AlarmActions에 설정
    - 기존 "AlarmActions 비움" 임시 처리 제거

  - [ ] 15.4 테스트 + 배포 검증
    - unit: CustomResource 생성/삭제
    - moto: 글로벌 알람 AlarmActions에 us-east-1 SNS ARN 포함 확인
    - 배포 후: CloudFront/Route53 알람 → Slack 알림 수신 확인

- [ ] 16. metric-key-rename 설계 + 구현

  - [ ] 16.1 Kiro Spec 작성
    - `.kiro/specs/metric-key-rename/` 에 design.md + tasks.md 작성
    - 리네이밍 매핑 테이블 확정 (내부 키 → CW metric_name)
    - `_LEGACY_KEY_MAP` 폴백 설계
    - 영향 범위: alarm_registry, alarm_manager, HARDCODED_DEFAULTS, _METRIC_DISPLAY, tag_resolver, 테스트 15+개

  - [ ] 16.2 단계적 리네이밍 구현
    - Step 1: `_LEGACY_KEY_MAP` 폴백 추가 (기존 알람 호환)
    - Step 2: alarm_registry `_*_ALARMS` 키 리네이밍
    - Step 3: HARDCODED_DEFAULTS 키 리네이밍
    - Step 4: _METRIC_DISPLAY 키 리네이밍
    - Step 5: tag_resolver Disk prefix 변경
    - Step 6: `_metric_name_to_key()` 함수 제거 (더 이상 불필요)

  - [ ] 16.3 테스트 업데이트 + 회귀 검증
    - 테스트 파일 15+개 키 이름 업데이트
    - `pytest tests/ -x -q --tb=short` 전체 통과
    - `cd frontend && npx vitest --run && npx tsc --noEmit`
    - KNOWN-ISSUES.md KI-005 관련 내용 업데이트

- [ ] 17. 최종 Checkpoint — 프로젝트 완성 검증

  - [ ] 17.1 전체 테스트 스위트 실행
    - `pytest tests/ --cov=common --cov=daily_monitor --cov=remediation_handler -x -q --tb=short`
    - `cd frontend && npx vitest --run --coverage && npx tsc --noEmit`
    - 커버리지: common/ 80%+, frontend src/domain/ 90%+

  - [ ] 17.2 전체 스펙 완료율 확인
    - 35개 스펙 모두 100% 완료 확인
    - KNOWN-ISSUES.md 9건 모두 "해결됨" 또는 "문서화" 상태 확인

  - [ ] 17.3 배포 검증
    - dev 환경 CloudFormation 스택 업데이트
    - E2E: 전체 리소스 타입 daily_monitor 실행 → 알람 생성 확인
    - 프론트엔드: 실제 API 연동 동작 확인
    - 글로벌 서비스: CloudFront/Route53 알람 → Slack 알림 수신 확인
