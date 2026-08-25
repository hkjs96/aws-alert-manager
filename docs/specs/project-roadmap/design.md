# Design Document — 프로젝트 로드맵

## Overview

미완료 항목을 의존관계 분석에 기반하여 5개 Phase로 구분한다.
각 Phase는 선행 Phase의 완료를 전제로 하되, 독립적인 작업은 병렬 진행 가능하다.

## Phase 구조 및 의존 관계

```
Phase 0: Quick Wins (1일)
├─ remaining-resources-e2e-test Task 10.4 (5분, 블로커 해소)
├─ pytest 커버리지 설정 (30분)
└─ extended-resource-monitoring PBT 마무리 (2시간, 96%→100%)

Phase 1: 테스트 갭 해소 (1주)
├─ alarm_builder 테스트
├─ alarm_naming 테스트
├─ dimension_builder 테스트
├─ threshold_resolver 테스트
└─ Lambda handler 직접 unit 테스트

Phase 2: 백엔드 API + 인프라 (2주)  ← 가장 큰 작업
├─ CloudFormation 리소스 추가 (DynamoDB, SQS FIFO, API Gateway)
├─ api_handler Lambda 구현 (9개 라우트)
├─ SQS Worker Lambda 구현
└─ 프론트엔드-백엔드 통합 연결

Phase 3: PBT 보강 + E2E 완성 (1주)
├─ tag-driven-alarm-engine PBT 8개
├─ alarm-manager-frontend-features PBT 10개
├─ create-alarm-modal 미완 테스트 12개
└─ remaining-resources-e2e-test 마무리 + 최종 검증

Phase 4: Enhancement (2주)
├─ KI-009 동적 알람 방향 (Threshold_LT_ prefix)
├─ global-service-alarm-notification 설계 + 구현
├─ metric-key-rename 설계 + 구현
└─ 전체 회귀 테스트 + 배포
```

## Phase별 상세 설계

### Phase 0: Quick Wins

**목적**: 블로커 제거 + 인프라 개선. 작업 시작 첫날에 완료.

| 작업 | 시간 | 효과 |
|------|------|------|
| E2E Task 10.4 (APIGW HTTP curl 20회) | 5분 | remaining-resources-e2e-test 블로커 해소 |
| pyproject.toml에 pytest-cov 설정 추가 | 30분 | 커버리지 가시성 확보 |
| extended-resource-monitoring PBT 마무리 | 2시간 | 96%→100%, 12개 Collector 정합성 검증 |

### Phase 1: 테스트 갭 해소

**목적**: Phase 2의 대규모 리팩터링/기능 추가 전에 안전망 확보.
**원칙**: TDD Red→Green→Refactor. 기존 코드 변경 없이 테스트만 추가.

| 모듈 | 테스트 전략 | 예상 테스트 수 |
|------|-----------|-------------|
| alarm_builder | unit + PBT (알람 생성 파라미터, 리전 분기, AlarmActions 구성) | 10~15 |
| alarm_naming | PBT (포맷 규칙, 255자 truncate, Short_ID 변환, 파싱 역변환) | 8~12 |
| dimension_builder | unit (리소스별 디멘션 조합, 글로벌 서비스, CWAgent 디멘션) | 10~15 |
| threshold_resolver | unit + PBT (3단계 폴백, 단위 환산 multiplier, 퍼센트 변환) | 8~12 |
| daily_monitor handler | moto 기반 unit (이벤트 처리 흐름, collector 호출, 고아 알람 정리) | 5~8 |
| remediation handler | moto 기반 unit (이벤트 매핑, ARN 변환, handle_delete/modify) | 5~8 |

**완료 기준**: `pytest tests/ --cov=common --cov=daily_monitor --cov=remediation_handler` 에서 common/ 80%+ 달성.

### Phase 2: 백엔드 API + 인프라

**목적**: alarm-manager-frontend spec의 Tasks 11~16 완료. 프론트엔드와 실제 AWS 백엔드 연결.

**2A. CloudFormation 리소스 (Task 11)**
- DynamoDB 테이블 3개: `customers`, `accounts`, `threshold_overrides`
  - (+ `job_status`: SQS 작업 추적용)
- SQS FIFO 큐: 벌크 알람 생성/삭제 비동기 처리
- API Gateway REST API + Lambda 통합
- IAM 역할/정책 추가

**2B. api_handler Lambda (Task 12)**
- 9개 라우트 구현:
  - `GET /dashboard/stats`, `GET /dashboard/recent-alarms`
  - `GET /resources`, `GET /resources/{id}`, `GET /resources/{id}/alarms`
  - `POST /bulk/monitoring`, `GET /alarms`
  - CRUD: `customers`, `accounts`, `thresholds`
- 기존 `common/` 모듈(alarm_manager, alarm_registry, collectors) 재활용
- DynamoDB CRUD 헬퍼 모듈 신규 작성

**2C. SQS Worker Lambda (Task 14)**
- SQS FIFO 큐에서 메시지 소비
- 벌크 모니터링 토글 (alarm create/delete) 처리
- `job_status` DynamoDB 테이블에 진행 상태 기록

**2D. 프론트엔드-백엔드 통합 (Task 15)**
- `lib/api.ts`의 Mock 엔드포인트를 실제 API Gateway URL로 교체
- 환경 변수: `NEXT_PUBLIC_API_ENDPOINT`
- E2E 통합 테스트

### Phase 3: PBT 보강 + E2E 완성

**목적**: 정합성 검증 강화 + E2E 파이프라인 완성.

**3A. PBT 보강**
| 스펙 | 미완 PBT 수 | 대상 |
|------|-----------|------|
| tag-driven-alarm-engine | 8 | Property 1~8 (test_pbt_tag_driven_alarm.py) |
| alarm-manager-frontend-features | 10 | API 타입, 필터, 토스트, UI, 동기화, CSV 등 |
| create-alarm-modal | 12 | 순수 함수, 컴포넌트, 통합 테스트 |

**3B. E2E 완성**
- remaining-resources-e2e-test Task 10.4 (Phase 0에서 완료) → Task 11 최종 검증
- AWS 배포 후 daily_monitor 실행 → 알람 생성 검증
- 전체 리소스 타입 커버리지 확인

### Phase 4: Enhancement

**목적**: Known Issues 해소 + 미착수 스펙 구현.

**4A. KI-009 동적 알람 방향 해소**
- `Threshold_LT_{MetricName}={Value}` prefix 지원
- `_create_dynamic_alarm()`에서 LT prefix 감지 → `LessThanThreshold` 사용
- 기존 `Threshold_{MetricName}` (LT 없음)은 `GreaterThanThreshold` 유지 (하위 호환)
- PBT: 방향 속성 보존 테스트

**4B. global-service-alarm-notification**
- design.md + tasks.md 작성 (Kiro Spec 포맷)
- CustomResource Lambda (us-east-1 SNS 토픽 생성)
- alarm_builder.py에 region 필드 지원 + AlarmActions 분기
- AWS Chatbot 수동 설정 가이드

**4C. metric-key-rename**
- design.md + tasks.md 작성
- 15+ 모듈 일괄 리네이밍 (내부 키 → CW metric_name)
- `_LEGACY_KEY_MAP` 폴백 추가 (기존 알람 호환)
- 테스트 파일 15+ 개 업데이트
- **주의**: Phase 2 통합 완료 후 실행해야 프론트엔드 태그 표시와 일관성 유지

## 리스크 및 완화

| 리스크 | 영향 | 완화 |
|--------|------|------|
| Phase 2 api_handler가 예상보다 복잡 | 일정 지연 | DynamoDB 스키마를 단순화, 핵심 3개 라우트 먼저 구현 |
| metric-key-rename 시 기존 알람 호환 실패 | 프로덕션 알람 누락 | _LEGACY_KEY_MAP + 단계적 마이그레이션 (신규 알람부터 적용) |
| E2E 테스트 인프라 비용 | AWS 비용 | 테스트 후 즉시 스택 삭제, Spot 인스턴스 활용 |
| 글로벌 서비스 Chatbot 수동 설정 | 자동화 불가 | 설정 가이드 문서화 + CFN 가능 범위까지만 자동화 |

## 일정 요약

| Phase | 기간 | 핵심 산출물 |
|-------|------|-----------|
| Phase 0 | 1일 | 블로커 해소, 커버리지 설정, extended-resource-monitoring 100% |
| Phase 1 | 1주 | 4개 모듈 테스트 + Lambda handler 테스트, 커버리지 80%+ |
| Phase 2 | 2주 | 백엔드 API, CFN 인프라, 프론트엔드 통합 |
| Phase 3 | 1주 | PBT 30개+, E2E 검증 완료 |
| Phase 4 | 2주 | KI-009 해소, 글로벌 알림, 메트릭 키 리네이밍 |
| **총합** | **~7주** | **프로젝트 100% 완성** |
