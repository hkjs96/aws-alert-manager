# 구현 계획: Alarm Manager 프론트엔드 (MVP)

## 개요

Phase1 백엔드(Python Lambda 기반 알람 자동 생성/동기화 엔진) 위에 웹 UI를 구축한다.
프론트엔드(Next.js App Router + TypeScript + Tailwind CSS), 백엔드 API(API Gateway + Lambda Python 3.12),
인프라(CloudFormation DynamoDB/SQS FIFO), 테스트(Vitest + fast-check / pytest + hypothesis)를 단계적으로 구현한다.

## Tasks

- [x] 1. 프로젝트 초기 설정 및 공통 타입/상수 정의
  - [x] 1.1 Next.js App Router 프로젝트 초기화 및 Tailwind CSS 설정
    - `frontend/` 디렉토리에 Next.js 프로젝트 생성 (App Router, TypeScript, Tailwind CSS)
    - `tsconfig.json`, `tailwind.config.ts`, `postcss.config.js` 설정
    - Vitest + React Testing Library + fast-check 개발 의존성 설치 및 설정
    - _Requirements: 1.5, 14.5_

  - [x] 1.2 TypeScript 인터페이스 및 타입 정의
    - `frontend/types/` 디렉토리에 Resource, AlarmConfig, AlarmSummary, Customer, Account, ThresholdOverride, Job 인터페이스 정의
    - AlarmState, SeverityLevel, SourceType, Direction 등 유니온 타입 정의
    - provider 필드 포함 (기본값 "aws")
    - _Requirements: 13.1, 13.3_

  - [x] 1.3 공통 상수 및 매핑 데이터 정의
    - `frontend/lib/constants.ts`에 SUPPORTED_RESOURCE_TYPES(30종), RESOURCE_TYPE_CATEGORIES(6개 카테고리 매핑), SEVERITY_COLORS, ALARM_STATE_COLORS, SOURCE_BADGE_STYLES, DIRECTION_STYLES 정의
    - _Requirements: 3.2, 5.3, 5.4, 5.5, 5.6, 11.1, 14.1, 14.2, 14.3_

  - [ ]* 1.4 Property 2: 리소스 유형 카테고리 매핑 일관성 속성 테스트
    - **Property 2: 리소스 유형 카테고리 매핑 일관성**
    - fast-check로 30종 리소스 유형이 정확히 하나의 카테고리에 속하는지, 모든 유형이 매핑에 포함되는지 검증
    - **Validates: Requirements 3.2**

  - [x] 1.5 API 클라이언트 모듈 구현
    - `frontend/lib/api.ts`에 ApiError 클래스, apiFetch 래퍼 함수 구현 (에러 핸들링 + 재시도 옵션)
    - API_BASE_URL 환경 변수 설정
    - _Requirements: 10.6_

- [x] 2. 공유 UI 컴포넌트 구현
  - [x] 2.1 SeverityBadge 컴포넌트 구현
    - `frontend/components/shared/SeverityBadge.tsx` — SEV-1~SEV-5 읽기 전용 아웃라인 뱃지
    - 각 등급별 색상: SEV-1(#dc2626), SEV-2(#ea580c), SEV-3(#d97706), SEV-4(#2563eb), SEV-5(#6b7280)
    - 정의되지 않은 메트릭은 SEV-5 폴백
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [ ]* 2.2 Property 4: Severity 뱃지 렌더링 및 조회 일관성 속성 테스트
    - **Property 4: Severity 뱃지 렌더링 및 조회 일관성**
    - fast-check로 모든 메트릭 키에 대해 올바른 Severity 등급 조회 및 색상 렌더링 검증
    - **Validates: Requirements 2.4, 3.4, 5.4, 11.1, 11.2, 11.3**

  - [x] 2.3 SourceBadge, DirectionIcon, AlarmStatusPill 컴포넌트 구현
    - `frontend/components/shared/SourceBadge.tsx` — System(회색), Customer(파란), Custom(보라) 뱃지
    - `frontend/components/shared/DirectionIcon.tsx` — ▲(빨간/주황, GreaterThan), ▼(파란, LessThan) 아이콘
    - `frontend/components/shared/AlarmStatusPill.tsx` — OK(초록), ALARM(빨간), INSUFFICIENT_DATA(앰버), OFF(회색)
    - _Requirements: 5.3, 5.5, 5.6, 14.1, 14.2, 14.3_

  - [ ]* 2.4 Property 5, 6, 7: Direction/Source/AlarmStatus 속성 테스트
    - **Property 5: Direction Icon과 비교 방향 매칭**
    - **Property 6: Source Badge와 임계치 출처 매칭**
    - **Property 7: 알람 상태 색상 코드 매칭**
    - fast-check로 각 컴포넌트의 입력-출력 매핑 일관성 검증
    - **Validates: Requirements 5.3, 5.5, 5.6, 14.1, 14.2, 14.3**

  - [x] 2.5 MonitoringToggle, DataTable, FilterBar, Pagination 공통 컴포넌트 구현
    - `frontend/components/shared/MonitoringToggle.tsx` — ON/OFF 토글 스위치 (onChange 콜백)
    - `frontend/components/shared/DataTable.tsx` — 범용 테이블 (정렬, 체크박스 선택 지원)
    - `frontend/components/shared/FilterBar.tsx` — 필터 입력 바 (드롭다운, 텍스트 검색)
    - `frontend/components/shared/Pagination.tsx` — 페이지네이션 컴포넌트
    - _Requirements: 3.1, 3.3, 3.7, 4.2_

  - [x] 2.6 BulkProgressBar, 에러 토스트 컴포넌트 구현
    - `frontend/components/shared/BulkProgressBar.tsx` — 벌크 작업 진행률 표시 (completed/total)
    - `frontend/components/shared/Toast.tsx` — 에러/성공 토스트 알림 + 재시도 버튼
    - _Requirements: 10.6, 12.3_

- [x] 3. 레이아웃 및 내비게이션 구현
  - [x] 3.1 RootLayout, TopBar, Sidebar 구현
    - `frontend/app/layout.tsx` — RootLayout: TopBar + Sidebar + GlobalFilterProvider + 메인 콘텐츠 영역
    - `frontend/components/layout/TopBar.tsx` — 로고("Alarm Manager"), 글로벌 필터 슬롯, 서비스 스위처 슬롯, 사용자 아바타
    - `frontend/components/layout/Sidebar.tsx` — Dashboard, Resources, Settings 내비게이션 + 축소 토글
    - 라이트 테마 적용 (흰색 배경, #f8fafc 사이드바, #2563eb 액센트)
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.6_

  - [x] 3.2 GlobalFilter Context 및 컴포넌트 구현
    - `frontend/hooks/useGlobalFilter.ts` — React Context + useGlobalFilter hook (고객사/어카운트/서비스 상태 관리)
    - `frontend/components/layout/GlobalFilter.tsx` — 상단 바 내 글로벌 필터 드롭다운 (고객사, 어카운트, 서비스)
    - 필터 변경 시 모든 페이지 데이터 갱신 트리거
    - _Requirements: 1.1, 1.4_

  - [ ]* 3.3 Property 1: 글로벌 필터 전파 속성 테스트
    - **Property 1: 글로벌 필터 전파**
    - fast-check로 글로벌 필터 변경 시 API 호출에 필터 파라미터가 포함되는지 검증
    - **Validates: Requirements 1.4, 2.5**

- [x] 4. Checkpoint — 공통 컴포넌트 및 레이아웃 검증
  - 모든 테스트 통과 확인, 사용자에게 질문이 있으면 문의.

- [x] 5. Dashboard 페이지 구현
  - [x] 5.1 Dashboard 페이지 및 StatCard 컴포넌트 구현
    - `frontend/app/dashboard/page.tsx` — DashboardPage: 4개 통계 카드 + 최근 알람 테이블
    - `frontend/components/dashboard/StatCard.tsx` — 모니터링 리소스 수, 활성 알람 수(빨간 강조), 미모니터링 수, 어카운트 수
    - `/api/dashboard/stats` API 연동
    - _Requirements: 2.1, 2.2, 2.5_

  - [x] 5.2 RecentAlarmsTable 컴포넌트 구현
    - `frontend/components/dashboard/RecentAlarmsTable.tsx` — 최근 10건 알람 트리거 테이블
    - 컬럼: 시간, 리소스, 유형, 메트릭, 상태, 값/임계치, SeverityBadge
    - `/api/dashboard/recent-alarms` API 연동
    - _Requirements: 2.3, 2.4_

- [x] 6. Resources 목록 페이지 구현
  - [x] 6.1 ResourcesPage 및 ResourceTable 구현
    - `frontend/app/resources/page.tsx` — ResourcesPage: 필터 바 + 리소스 테이블 + 벌크 액션 바 + 통계 요약
    - `frontend/components/resources/ResourceTable.tsx` — 리소스 테이블 (체크박스, 고객사, 리소스 ID(모노스페이스), 이름, 유형(아이콘), 어카운트, 리전, 모니터링 토글, 활성 알람 뱃지)
    - 리소스 유형 드롭다운을 Resource_Type_Category별 그룹화
    - 활성 알람 뱃지에 Severity 등급 포함 (예: "2 SEV-1"(빨간), "0 ACTIVE"(회색))
    - `/api/resources` API 연동 (필터/페이지네이션)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6, 3.7, 3.10, 13.2_

  - [x] 6.2 BulkActionBar 컴포넌트 구현
    - `frontend/components/resources/BulkActionBar.tsx` — 벌크 액션 바 (모니터링 활성화, 비활성화, 알람 설정)
    - 1개 이상 리소스 선택 시 표시, 0개 선택 시 숨김
    - 벌크 알람 설정 시 공통 메트릭별 임계치 입력 폼 표시 (선택적 메트릭 업데이트)
    - `/api/bulk/monitoring`, `/api/bulk/alarms` API 연동
    - _Requirements: 3.5, 12.1, 12.2, 12.4_

  - [ ]* 6.3 Property 19: 벌크 액션 바 조건부 표시 속성 테스트
    - **Property 19: 벌크 액션 바 조건부 표시**
    - fast-check로 선택된 리소스 수에 따른 벌크 액션 바 표시/숨김 검증
    - **Validates: Requirements 3.5, 12.1**

  - [x] 6.4 useJobPolling hook 및 벌크 작업 진행 상태 구현
    - `frontend/hooks/useJobPolling.ts` — job_id 기반 polling hook (상태 조회 + 프로그레스 바 업데이트)
    - 성공/실패 결과 요약 표시 (실패 건 DLQ 이동 안내)
    - 작업 이력 조회 기능 (`/api/jobs`)
    - _Requirements: 12.3, 12.5, 12.6_

  - [x] 6.5 CSV 내보내기 및 리소스 동기화 기능 구현
    - CSV 내보내기 버튼 → `/api/resources/export` 호출
    - 리소스 동기화 버튼 → `/api/resources/sync` 호출 + job polling
    - _Requirements: 3.8, 3.9_

- [x] 7. Resource Detail 페이지 구현
  - [x] 7.1 ResourceDetailPage 헤더 및 모니터링 토글 구현
    - `frontend/app/resources/[id]/page.tsx` — ResourceDetailPage
    - 헤더: 리소스 ID, 이름, 유형, 어카운트, 리전 + 대형 모니터링 ON/OFF 토글
    - 모니터링 OFF → 모든 알람 비활성화, ON → 알람 설정 테이블 기반 활성화
    - `/api/resources/{id}`, `/api/resources/{id}/monitoring` API 연동
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 7.2 AlarmConfigTable 컴포넌트 구현
    - `frontend/components/resources/AlarmConfigTable.tsx` — 알람 설정 테이블
    - 컬럼: 개별 모니터링 토글, 메트릭명, CW 메트릭명(회색 모노스페이스), 임계치(편집 가능), 단위, DirectionIcon, SeverityBadge(읽기 전용), SourceBadge, 상태(AlarmStatusPill), 현재 값
    - Alarm_Registry 기반 자동 생성 (30종 리소스 유형)
    - EC2 Disk 메트릭: 마운트 경로별 개별 행 표시
    - "변경사항 저장" + "기본값으로 초기화" 버튼
    - 미저장 변경 표시기
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 14.4_

  - [ ]* 7.3 Property 10: EC2 Disk 마운트 경로별 행 생성 속성 테스트
    - **Property 10: EC2 Disk 마운트 경로별 행 생성**
    - fast-check로 EC2 Disk 메트릭의 마운트 경로별 개별 행 생성 및 고유성 검증
    - **Validates: Requirements 5.7**

  - [ ]* 7.4 Property 11: 미저장 변경 감지 속성 테스트
    - **Property 11: 미저장 변경 감지**
    - fast-check로 폼 값과 저장된 값 비교 시 미저장 변경 표시기 표시/숨김 검증
    - **Validates: Requirements 5.9**

  - [x] 7.5 최근 이벤트 섹션 구현
    - Resource Detail 페이지 하단에 최근 이벤트 목록 표시
    - _Requirements: 5.10_

  - [x] 7.6 CustomMetricForm 및 MetricAutocomplete 구현
    - `frontend/components/resources/CustomMetricForm.tsx` — 커스텀 메트릭 추가 인라인 폼
    - `frontend/components/resources/MetricAutocomplete.tsx` — CloudWatch list_metrics 기반 자동완성 드롭다운 (하드코딩 메트릭 제외, "MetricName (Namespace)" 형식)
    - 자유 텍스트 입력 허용
    - 메트릭 존재 시 ✅ 초록색 검증 표시기, 미존재 시 ⚠️ 앰버색 경고 표시기
    - 커스텀 알람 별도 테이블 표시 (메트릭, 네임스페이스, 임계치, 방향, 상태, 출처, 액션)
    - `/api/resources/{id}/metrics`, `/api/resources/{id}/custom-alarms` API 연동
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [ ]* 7.7 Property 12, 13: 커스텀 메트릭 자동완성 및 검증 속성 테스트
    - **Property 12: 커스텀 메트릭 자동완성 필터링**
    - **Property 13: 커스텀 메트릭 검증 표시기**
    - fast-check로 하드코딩 메트릭 제외 필터링 및 존재 여부별 표시기 검증
    - **Validates: Requirements 6.3, 6.5, 6.6, 10.5**

- [x] 8. Checkpoint — 프론트엔드 페이지 검증
  - 모든 테스트 통과 확인, 사용자에게 질문이 있으면 문의.

- [x] 9. Settings 페이지 구현
  - [x] 9.1 고객사 관리 탭 구현
    - `frontend/app/settings/page.tsx` — SettingsPage (탭: 고객사, 어카운트, 임계치 오버라이드)
    - `frontend/components/settings/CustomerList.tsx` — 고객사 목록 (이름, 코드, 연결 어카운트 수) + 추가/편집/삭제 폼
    - 삭제 시 연결 어카운트 존재하면 확인 경고 표시
    - `/api/customers` CRUD API 연동
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ]* 9.2 Property 14: 고객사 삭제 시 연결 어카운트 경고 속성 테스트
    - **Property 14: 고객사 삭제 시 연결 어카운트 경고**
    - fast-check로 연결 어카운트 수에 따른 삭제 경고 표시/미표시 검증
    - **Validates: Requirements 7.5**

  - [x] 9.3 어카운트 등록 탭 구현
    - `frontend/components/settings/AccountRegistry.tsx` — 어카운트 목록 (ID, 이름, Role ARN, 고객사, 연결 상태) + 추가/편집/삭제 폼
    - "연결 테스트" 버튼 → `/api/accounts/{id}/test-connection` API 호출
    - `/api/accounts` CRUD API 연동
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 9.4 임계치 오버라이드 탭 구현
    - `frontend/components/settings/ThresholdOverrideTabs.tsx` — 30종 리소스 유형 수평 스크롤 탭
    - `frontend/components/settings/MetricOverrideCard.tsx` — 메트릭 카드 (메트릭명, CW 메트릭명, 비교 방향, 시스템 기본값, 고객사별 오버라이드 목록)
    - "오버라이드 추가" 버튼 (고객사 선택 + 임계치 입력) + 편집/삭제
    - Alarm_Registry 기반 메트릭 카드 자동 생성
    - `/api/thresholds/{resource_type}` API 연동
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [ ]* 9.5 Property 3: Alarm Registry 기반 메트릭 테이블 일관성 속성 테스트
    - **Property 3: Alarm Registry 기반 메트릭 테이블 일관성**
    - fast-check로 리소스 유형별 메트릭 테이블이 alarm_registry 데이터와 일치하는지 검증
    - **Validates: Requirements 5.1, 9.1, 9.2**

- [ ] 10. Checkpoint — 프론트엔드 전체 페이지 검증
  - 모든 테스트 통과 확인, 사용자에게 질문이 있으면 문의.

- [ ] 11. 백엔드 인프라 — CloudFormation 리소스 추가
  - [ ] 11.1 DynamoDB 테이블 4개 CloudFormation 정의
    - `template.yaml`에 CustomersTable, AccountsTable(GSI: customer_id-index), ThresholdOverridesTable(복합 키 pk+metric_key), JobStatusTable(GSI: status-created_at-index, TTL 활성화) 추가
    - _Requirements: 10.1, 10.11_

  - [ ] 11.2 SQS FIFO 큐 및 DLQ CloudFormation 정의
    - `template.yaml`에 AlarmOpsFifoQueue(alarm-ops.fifo, ContentBasedDeduplication: false), AlarmOpsDlqQueue(alarm-ops-dlq.fifo) 추가
    - RedrivePolicy: maxReceiveCount=3
    - DlqAlarm: DLQ 메시지 수 > 0 시 CloudWatch Alarm → SNS 운영팀 알림
    - _Requirements: 10.8, 10.9, 10.10_

  - [ ] 11.3 API Gateway + Lambda 함수 CloudFormation 정의
    - ApiGateway(REST API), ApiHandlerFunction(api_handler Lambda, Python 3.12, CommonLayer 공유), SqsWorkerFunction(sqs_worker Lambda, SQS 이벤트 소스 매핑)
    - IAM Role: api_handler용 (DynamoDB CRUD + SQS SendMessage + STS AssumeRole + CloudWatch), sqs_worker용 (DynamoDB + STS AssumeRole + CloudWatch)
    - _Requirements: 10.1, 10.2, 10.3_

- [ ] 12. 백엔드 API — api_handler Lambda 구현
  - [ ] 12.1 api_handler 라우팅 및 공통 유틸리티 구현
    - `api_handler/lambda_handler.py` — API Gateway 이벤트 라우팅 (path + method 기반)
    - `api_handler/utils/response.py` — API Gateway 응답 포맷 헬퍼 (200, 400, 404, 500 등)
    - `api_handler/utils/validators.py` — 입력 검증 유틸리티
    - _Requirements: 10.1_

  - [ ] 12.2 고객사/어카운트 CRUD 라우트 구현
    - `api_handler/routes/customers.py` — 고객사 CRUD (DynamoDB customers 테이블)
    - `api_handler/routes/accounts.py` — 어카운트 CRUD (DynamoDB accounts 테이블) + 연결 테스트 (AssumeRole 유효성 검증)
    - _Requirements: 7.1~7.5, 8.1~8.5_

  - [ ] 12.3 임계치 오버라이드 라우트 구현
    - `api_handler/routes/thresholds.py` — 리소스 유형별 임계치 오버라이드 조회/저장 (DynamoDB threshold_overrides 테이블, 복합 키)
    - _Requirements: 9.1~9.6_

  - [ ]* 12.4 Property 15: 임계치 오버라이드 라운드트립 속성 테스트
    - **Property 15: 임계치 오버라이드 라운드트립**
    - hypothesis로 고객사/리소스유형/메트릭키 조합의 저장-조회 라운드트립 일관성 검증
    - **Validates: Requirements 9.5**

  - [ ] 12.5 리소스 조회 및 알람 설정 라우트 구현
    - `api_handler/routes/resources.py` — 리소스 목록 조회 (AssumeRole → 고객 어카운트 리소스 수집, 기존 collectors 활용), 리소스 상세 + 알람 설정 조회
    - `api_handler/services/resource_service.py` — AssumeRole + 리소스 수집 서비스 (기존 common/collectors 활용)
    - `api_handler/services/alarm_service.py` — 알람 조회/설정 서비스 (기존 common/alarm_manager 활용, 임계치 우선순위 적용)
    - CSV 내보내기, 리소스 동기화 트리거
    - _Requirements: 10.2, 10.3, 10.4, 10.7, 3.8, 3.9_

  - [ ]* 12.6 Property 8: 임계치 조회 우선순위 속성 테스트
    - **Property 8: 임계치 조회 우선순위**
    - hypothesis로 리소스 태그 > 고객사 오버라이드 > 환경 변수 > 시스템 기본값 우선순위 검증
    - **Validates: Requirements 10.7**

  - [ ] 12.7 알람 변경 및 벌크 작업 라우트 구현
    - `api_handler/routes/alarms.py` — 알람 임계치 저장, 모니터링 토글 (SQS FIFO enqueue + DynamoDB job 생성)
    - `api_handler/routes/bulk.py` — 벌크 모니터링 ON/OFF, 벌크 알람 설정 (SQS FIFO enqueue)
    - `api_handler/services/sqs_service.py` — SQS FIFO enqueue 헬퍼 (MessageGroupId: "{account_id}:{resource_id}", MessageDeduplicationId: "{job_id}:{resource_id}")
    - _Requirements: 10.8, 12.1, 12.2_

  - [ ] 12.8 작업 상태 조회 및 대시보드 라우트 구현
    - `api_handler/routes/jobs.py` — 작업 진행 상태 조회 (DynamoDB job_status), 작업 이력 목록
    - `api_handler/routes/dashboard.py` — 통계 카드 데이터 집계, 최근 알람 트리거 조회
    - _Requirements: 10.11, 12.3, 12.6, 2.1~2.5_

  - [ ] 12.9 커스텀 메트릭 자동완성 라우트 구현
    - `api_handler/routes/resources.py`에 CloudWatch list_metrics 프록시 엔드포인트 추가
    - 하드코딩 메트릭 제외 필터링
    - _Requirements: 10.5, 6.3_

- [ ] 13. Checkpoint — 백엔드 API 검증
  - 모든 테스트 통과 확인, 사용자에게 질문이 있으면 문의.

- [ ] 14. 백엔드 — SQS Worker Lambda 구현
  - [ ] 14.1 sqs_worker Lambda 구현
    - `sqs_worker/lambda_handler.py` — SQS FIFO 이벤트 처리
    - 메시지 action별 분기: create_alarms, update_alarms, delete_alarms, toggle_monitoring
    - 기존 common/alarm_manager 함수 호출 (create_alarms_for_resource, sync_alarms_for_resource 등)
    - AssumeRole → 고객 어카운트 CloudWatch 알람 CRUD
    - DynamoDB job_status 상태 업데이트 (completed_count, failed_count 증분)
    - 에러 처리: ClientError catch → job_status 실패 기록, 3회 실패 시 DLQ 이동
    - _Requirements: 10.2, 10.8, 10.9_

  - [ ]* 14.2 Property 16: 비동기 작업 상태 추적 속성 테스트
    - **Property 16: 비동기 작업 상태 추적**
    - hypothesis로 N개 리소스 벌크 작업 시 completed_count + failed_count ≤ total_count 불변식 검증
    - **Validates: Requirements 10.11, 12.2, 12.3, 12.5**

  - [ ]* 14.3 Property 17: 알람 생성 시 태그 및 AlarmActions 설정 속성 테스트
    - **Property 17: 알람 생성 시 태그 및 AlarmActions 설정**
    - hypothesis로 알람 생성 시 SNS AlarmActions, Severity 태그, ManagedBy=AlarmManager 태그, AlarmDescription JSON(customer_id, account_id) 포함 검증
    - **Validates: Requirements 13.3, 15.2, 15.3**

- [ ] 15. 프론트엔드-백엔드 통합 연결
  - [ ] 15.1 API 에러 핸들링 통합
    - 프론트엔드 API 클라이언트에서 4xx/5xx/네트워크 에러 시 토스트 알림 + 재시도 버튼 표시
    - 페이지 로딩 실패 시 에러 바운더리 + 새로고침 버튼
    - _Requirements: 10.6_

  - [ ]* 15.2 Property 18: API 에러 시 사용자 피드백 속성 테스트
    - **Property 18: API 에러 시 사용자 피드백**
    - fast-check로 다양한 HTTP 상태 코드(400, 404, 500, 502, 503)에 대한 에러 메시지 및 재시도 옵션 표시 검증
    - **Validates: Requirements 10.6**

  - [ ] 15.3 모니터링 토글 및 알람 저장 비동기 흐름 연결
    - Resource Detail 페이지에서 모니터링 토글 → API 호출 → job_id 반환 → polling → 상태 업데이트
    - 알람 임계치 저장 → API 호출 → job_id 반환 → polling → 완료 표시
    - _Requirements: 4.3, 4.4, 5.8_

  - [ ]* 15.4 Property 9: 모니터링 토글 라운드트립 속성 테스트
    - **Property 9: 모니터링 토글 라운드트립**
    - hypothesis로 모니터링 OFF→ON 전환 시 알람 복원, OFF 시 전체 비활성화 검증
    - **Validates: Requirements 4.3, 4.4**

  - [ ]* 15.5 Property 20: 리소스 데이터 모델 provider 필드 속성 테스트
    - **Property 20: 리소스 데이터 모델 provider 필드**
    - hypothesis로 API 반환 리소스 객체에 provider 필드 존재 및 기본값 "aws" 검증
    - **Validates: Requirements 13.1**

- [ ] 16. 최종 Checkpoint — 전체 통합 검증
  - 모든 프론트엔드/백엔드 테스트 통과 확인, 사용자에게 질문이 있으면 문의.

## Notes

- `*` 표시된 태스크는 선택 사항이며 빠른 MVP를 위해 건너뛸 수 있음
- 각 태스크는 특정 요구사항을 참조하여 추적 가능
- Checkpoint에서 점진적 검증 수행
- 속성 테스트(Property-Based Test)는 보편적 정합성 속성을 검증
- 단위 테스트는 특정 예시 및 엣지 케이스를 검증
- 프론트엔드: Vitest + React Testing Library + fast-check
- 백엔드: pytest + moto + hypothesis
- 기존 Phase1 common/ 모듈(alarm_manager, alarm_registry, collectors)을 최대한 재사용
