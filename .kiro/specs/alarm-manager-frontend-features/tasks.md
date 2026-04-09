# Implementation Plan: Alarm Manager 프론트엔드 기능 구현

## Overview

현재 mock 데이터 기반 UI를 실제 백엔드 API 연동으로 전환하고, 글로벌 필터, 서버사이드 페이지네이션, 벌크 액션, 토스트 알림, 에러/로딩 상태 등 17개 요구사항을 5개 Phase로 나누어 구현한다. 백엔드 REST API가 아직 없으므로 Phase 1에서 Next.js Route Handler 기반 Mock API를 먼저 생성한다.

## Tasks

- [x] 1. Phase 1 — 기반 인프라 (API 타입, Mock API, API 클라이언트, 토스트, 공통 UI)
  - [x] 1.1 API 요청/응답 타입 정의 (`types/api.ts`)
    - `GlobalFilterParams`, `PaginationParams`, `PaginatedResponse<T>`, `ApiError`, `BulkMonitoringRequest`, `BulkOperationResponse`, `JobStatus`, `SaveAlarmConfigRequest`, `CreateCustomerRequest`, `CreateAccountRequest`, `ConnectionTestResult`, `ThresholdOverride`, `SyncResult`, `AvailableMetric`, `AlarmSummary` 등 설계 문서의 모든 API 타입을 정의
    - 기존 `types/index.ts`의 도메인 타입을 확장하되 별도 파일로 분리
    - _Requirements: 1.1_

  - [ ]* 1.2 API 타입 속성 테스트 작성
    - **Property 2: 글로벌 필터 API 전파** — `buildFilterParams()`가 비어있지 않은 필터 값만 쿼리 파라미터로 포함하는지 검증
    - **Validates: Requirements 1.3, 2.4**

  - [x] 1.3 Mock API Route Handlers 생성 (`app/api/*`)
    - `app/api/dashboard/stats/route.ts` — GET: DashboardStats 반환
    - `app/api/dashboard/recent-alarms/route.ts` — GET: PaginatedResponse<RecentAlarm> 반환
    - `app/api/resources/route.ts` — GET: PaginatedResponse<Resource> (필터, 페이지네이션, 정렬 지원)
    - `app/api/resources/sync/route.ts` — POST: SyncResult 반환
    - `app/api/resources/export/route.ts` — GET: CSV Blob 반환
    - `app/api/resources/[id]/route.ts` — GET: Resource 반환
    - `app/api/resources/[id]/alarms/route.ts` — GET/PUT: AlarmConfig[] 반환/저장
    - `app/api/resources/[id]/events/route.ts` — GET: RecentAlarm[] 반환
    - `app/api/resources/[id]/metrics/route.ts` — GET: AvailableMetric[] 반환
    - `app/api/resources/[id]/monitoring/route.ts` — PUT: 모니터링 토글
    - `app/api/bulk/monitoring/route.ts` — POST: BulkOperationResponse 반환
    - `app/api/alarms/route.ts` — GET: PaginatedResponse<Alarm> 반환
    - `app/api/alarms/summary/route.ts` — GET: AlarmSummary 반환
    - `app/api/alarms/export/route.ts` — GET: CSV Blob 반환
    - `app/api/customers/route.ts` — GET/POST: Customer CRUD
    - `app/api/customers/[id]/route.ts` — DELETE: Customer 삭제
    - `app/api/accounts/route.ts` — GET/POST: Account CRUD
    - `app/api/accounts/[id]/test/route.ts` — POST: ConnectionTestResult 반환
    - `app/api/thresholds/[type]/route.ts` — GET/PUT: ThresholdOverride[] 반환/저장
    - 기존 `lib/mock-data.ts` 데이터를 Route Handler 내부에서 활용
    - _Requirements: 1.1, 3.1, 3.2, 4.1, 5.1, 6.1, 6.2, 7.1, 7.2, 7.3, 8.2, 9.1, 10.1, 11.1, 12.1, 13.2, 16.1, 17.1, 17.2_

  - [x] 1.4 API 클라이언트 모듈 구현 (`lib/api.ts`)
    - `apiFetch<T>()` 제네릭 fetch wrapper (에러 시 `ApiError` throw)
    - `buildFilterParams()` 글로벌 필터 → URLSearchParams 변환
    - `NEXT_PUBLIC_API_BASE_URL` 환경 변수 기반 base URL
    - HTTP 에러(4xx/5xx) 시 `{ status, code, message }` 구조화된 에러 객체
    - 네트워크 에러 시 `status: 0, code: "NETWORK_ERROR"` 반환
    - _Requirements: 1.1, 1.2, 1.3, 1.5_

  - [ ]* 1.5 API 클라이언트 속성 테스트 작성
    - **Property 1: API 에러 응답 구조화** — HTTP 에러 상태 코드(400~599)에 대해 throw되는 에러 객체가 `status`, `code`, `message` 필드를 포함하는지 검증
    - **Validates: Requirements 1.2**

  - [x] 1.6 필터 파라미터 유틸리티 함수 구현 (`lib/filterParams.ts`)
    - `serializeFilters()` — 필터 상태를 URL searchParams 문자열로 직렬화
    - `parseFilters()` — URL searchParams를 필터 상태 객체로 파싱
    - `buildPaginationParams()` — 페이지네이션 파라미터 생성 (page_size 허용값 25/50/100 검증)
    - `buildSortParams()` — 정렬 파라미터 생성
    - _Requirements: 2.3, 4.2, 4.4_

  - [ ]* 1.7 필터 파라미터 속성 테스트 작성
    - **Property 4: 필터 URL 라운드트립** — 필터 값을 직렬화 후 파싱하면 원래 값과 동일한지 검증
    - **Validates: Requirements 2.3**
    - **Property 5: 페이지네이션 파라미터 정합성** — page ≥ 1, page_size ∈ {25, 50, 100} 검증
    - **Validates: Requirements 4.2, 10.2**
    - **Property 6: 정렬 파라미터 전파** — sort, order 파라미터가 올바르게 포함되는지 검증
    - **Validates: Requirements 4.4**

  - [x] 1.8 토스트 알림 시스템 구현 (`components/shared/Toast.tsx`)
    - `ToastProvider` — layout.tsx에 배치할 Context Provider
    - `useToast()` hook — `showToast(variant, message, duration?)` 반환
    - `ToastContainer` — fixed top-right, 수직 스택 렌더링
    - 4가지 변형: success(green), error(red), warning(amber), info(blue)
    - 5초 후 자동 dismiss + X 버튼 수동 dismiss
    - layout.tsx에 `<ToastProvider>` 래핑 추가
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_

  - [ ]* 1.9 토스트 속성 테스트 작성
    - **Property 16: 토스트 변형별 색상 매핑** — 각 변형(success/error/warning/info)이 지정된 색상 클래스를 포함하는지 검증
    - **Validates: Requirements 14.2**

  - [x] 1.10 공통 UI 컴포넌트 구현
    - `components/shared/Skeleton.tsx` — 카드, 테이블 행, 텍스트 변형 스켈레톤
    - `components/shared/ErrorPanel.tsx` — 에러 메시지 + Retry 버튼 인라인 컴포넌트
    - `components/shared/LoadingButton.tsx` — isLoading 시 disabled + 스피너 표시
    - `components/shared/ConfirmDialog.tsx` — 삭제 등 위험 액션 확인 모달
    - `components/shared/Pagination.tsx` — 서버사이드 페이지네이션 컨트롤 (페이지 크기 선택, 페이지 이동, 총 건수)
    - `components/shared/SeverityBadge.tsx` — SEV-1~SEV-5 아웃라인 뱃지
    - `components/shared/SourceBadge.tsx` — System/Customer/Custom 출처 뱃지
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 7.6, 7.7_

  - [ ]* 1.11 공통 UI 속성 테스트 작성
    - **Property 10: Severity 뱃지 색상 매핑** — SEV-1~SEV-5 각 레벨에 지정된 아웃라인 색상 클래스 검증
    - **Validates: Requirements 7.6**
    - **Property 11: Source 뱃지 색상 매핑** — System/Customer/Custom 각 타입에 지정된 색상 클래스 검증
    - **Validates: Requirements 7.7**
    - **Property 17: 에러 패널 구조 일관성** — ErrorPanel이 에러 메시지 텍스트와 Retry 버튼을 모두 렌더링하는지 검증
    - **Validates: Requirements 15.2**

- [x] 2. Checkpoint — Phase 1 완료 확인
  - Ensure all tests pass, ask the user if questions arise.


- [x] 3. Phase 2 — 글로벌 필터 + Dashboard (Req 2, 3)
  - [x] 3.1 GlobalFilterBar 컴포넌트 구현 (`components/layout/GlobalFilterBar.tsx`)
    - 3개 캐스케이딩 드롭다운: Customer → Account → Service
    - Customer 선택 시 해당 Customer 소속 Account만 필터링
    - 선택 변경 시 `router.push()` 로 URL searchParams 업데이트
    - 초기 렌더링 시 `/api/customers`, `/api/accounts` 에서 옵션 목록 fetch
    - TopBar.tsx에 GlobalFilterBar 통합
    - _Requirements: 2.1, 2.2, 2.3, 2.5_

  - [ ]* 3.2 GlobalFilterBar 속성 테스트 작성
    - **Property 3: 캐스케이딩 어카운트 필터링** — 고객사 선택 시 해당 customer_id와 일치하는 어카운트만 표시되는지 검증
    - **Validates: Requirements 2.2**

  - [x] 3.3 Dashboard Server Component 리팩터링 (`app/dashboard/page.tsx`)
    - `'use client'` 제거 → Server Component로 전환
    - `page.tsx`에서 `fetchDashboardStats()` + `fetchRecentAlarms()` 호출 (searchParams 기반 필터 적용)
    - `components/dashboard/DashboardContent.tsx` (Client) — 새로고침 버튼, 검색
    - `components/dashboard/StatCardGrid.tsx` — 통계 카드 4개 (서버에서 props 전달)
    - `components/dashboard/RecentAlarmsTable.tsx` (Client) — 검색, 페이지네이션
    - 글로벌 필터 변경 시 데이터 재페칭 (URL searchParams 변경 → Server Component 재실행)
    - _Requirements: 2.4, 3.1, 3.2, 3.5_

  - [x] 3.4 Dashboard loading.tsx + error.tsx 구현
    - `app/dashboard/loading.tsx` — StatCard 스켈레톤 4개 + 테이블 스켈레톤
    - `app/dashboard/error.tsx` — ErrorPanel + `reset()` 재시도
    - _Requirements: 3.3, 3.4, 15.1, 15.2_

- [x] 4. Checkpoint — Phase 2 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Phase 3 — Resources 목록 (Req 4, 5, 16, 17)
  - [x] 5.1 Resources Server/Client 분리 리팩터링
    - `app/resources/page.tsx` — Server Component로 전환, `fetchResources(searchParams)` 호출
    - `components/resources/ResourcesContent.tsx` (Client) — 필터, 검색, 정렬 상태 관리
    - `components/resources/ResourceTable.tsx` (Client) — 체크박스 선택, 모니터링 토글, 행 클릭
    - `components/resources/BulkActionBar.tsx` (Client) — 선택 카운트, Enable/Disable 버튼
    - 서버사이드 페이지네이션: Pagination 컴포넌트 연동 (page, page_size, sort, order → URL searchParams)
    - 필터 변경 시 API 재호출 (Customer, Account, Resource Type, search → searchParams)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 5.2 Resources loading.tsx + error.tsx 구현
    - `app/resources/loading.tsx` — 필터 바 스켈레톤 + 테이블 스켈레톤
    - `app/resources/error.tsx` — ErrorPanel + `reset()` 재시도
    - _Requirements: 4.5, 4.6, 15.1, 15.2_

  - [x] 5.3 모니터링 토글 API 연동 (`hooks/useMonitoringToggle.ts`)
    - ResourceTable 내 토글 클릭 시 `PUT /api/resources/{id}/monitoring` 호출
    - 토글 진행 중 loading 상태 (disabled + spinner)
    - 성공 시 토글 상태 업데이트, 실패 시 이전 상태로 롤백 + 에러 토스트
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

  - [ ]* 5.4 모니터링 토글 롤백 속성 테스트 작성
    - **Property 18: 모니터링 토글 실패 시 롤백** — API 실패 시 토글 상태가 원래 값으로 복원되는지 검증
    - **Validates: Requirements 16.4**

  - [x] 5.5 리소스 동기화 기능 구현
    - "Sync Resources" 버튼 클릭 시 `POST /api/resources/sync` 호출
    - 진행 중 버튼에 스피너 + disabled (LoadingButton 사용)
    - 성공 시 Toast에 동기화 요약 (discovered, updated, removed) 표시
    - 실패 시 에러 Toast 표시
    - 완료 후 리소스 목록 자동 재페칭 (`router.refresh()`)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ]* 5.6 동기화 토스트 메시지 속성 테스트 작성
    - **Property 7: 동기화 결과 토스트 메시지 정합성** — 성공 토스트에 discovered, updated, removed 세 가지 카운트가 모두 포함되는지 검증
    - **Validates: Requirements 5.3**

  - [x] 5.7 CSV 내보내기 기능 구현 (`lib/exportCsv.ts`)
    - Resources 페이지 "Export CSV" 버튼 → `GET /api/resources/export` (현재 필터 파라미터 포함)
    - 응답 Blob을 브라우저 다운로드로 트리거
    - 파일명: `resources_{YYYY-MM-DD}.csv` 형식
    - 내보내기 중 버튼 로딩 표시
    - _Requirements: 17.1, 17.3, 17.4_

  - [ ]* 5.8 CSV 내보내기 속성 테스트 작성
    - **Property 19: CSV 내보내기 필터 전파** — 현재 필터 파라미터가 내보내기 요청에 모두 포함되는지 검증
    - **Validates: Requirements 17.1, 17.2**
    - **Property 20: CSV 파일명 형식** — 파일명이 `{type}_{YYYY-MM-DD}.csv` 형식인지 검증
    - **Validates: Requirements 17.3**

- [x] 6. Checkpoint — Phase 3 완료 확인
  - Ensure all tests pass, ask the user if questions arise.


- [x] 7. Phase 4 — 벌크 액션 + Resource Detail (Req 6, 7, 8, 9)
  - [x] 7.1 벌크 Enable/Disable 모달 API 연동
    - `components/resources/EnableModal.tsx` (Client) — 메트릭 설정 + 커스텀 메트릭 폼, `POST /api/bulk/monitoring` 호출
    - `components/resources/DisableModal.tsx` (Client) — 비활성화 확인, `POST /api/bulk/monitoring` 호출
    - 진행 중 모달 내 submit 버튼 LoadingButton 사용
    - 성공 시 success Toast + 처리 건수 표시, 부분 실패 시 warning Toast + 실패 리소스 ID 목록
    - 완료 후 선택 초기화 + `router.refresh()`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ]* 7.2 벌크 액션 속성 테스트 작성
    - **Property 8: 벌크 요청 리소스 ID 완전성** — 선택된 모든 ID가 요청에 포함되고 선택되지 않은 ID는 제외되는지 검증
    - **Validates: Requirements 6.1, 6.2**
    - **Property 9: 벌크 결과 토스트 메시지 정합성** — 전체 성공 시 success 토스트에 처리 건수, 부분 실패 시 warning 토스트에 실패 ID 목록 포함 검증
    - **Validates: Requirements 6.4, 6.5**

  - [x] 7.3 Resource Detail Server Component 리팩터링
    - `app/resources/[id]/page.tsx` — Server Component로 전환
    - `fetchResource(id)` + `fetchAlarmConfigs(id)` + `fetchEvents(id)` 병렬 호출 (`Promise.all`)
    - `components/resources/ResourceHeader.tsx` — 메타데이터 표시 (ID, name, type, account, region, monitoring)
    - `components/resources/AlarmConfigTable.tsx` (Client) — 임계치 편집, 메트릭 토글, SeverityBadge, SourceBadge 표시
    - `components/resources/ResourceEvents.tsx` — 최근 이벤트 목록
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [x] 7.4 Resource Detail loading.tsx + error.tsx 구현
    - `app/resources/[id]/loading.tsx` — 헤더 스켈레톤 + 알람 테이블 스켈레톤
    - `app/resources/[id]/error.tsx` — ErrorPanel + `reset()` 재시도
    - _Requirements: 7.4, 7.5, 15.1, 15.2_

  - [x] 7.5 알람 설정 저장 기능 구현
    - AlarmConfigTable에서 임계치 수정/메트릭 토글 시 unsaved changes 추적
    - unsaved indicator 표시 (변경 사항 있을 때)
    - "Save Changes" 클릭 시 `PUT /api/resources/{id}/alarms` 호출
    - 저장 중 LoadingButton 사용, 성공 시 Toast + unsaved indicator 해제
    - 실패 시 에러 Toast + unsaved changes 유지
    - "Reset to Defaults" 클릭 시 시스템 기본값으로 복원 (API 호출 없음)
    - Monitoring Status 토글 시 `PUT /api/resources/{id}/monitoring` 호출
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [ ]* 7.6 알람 설정 속성 테스트 작성
    - **Property 12: 미저장 변경 감지** — 현재 값이 저장된 값과 다르면 unsaved indicator 표시, 동일하면 숨김 검증
    - **Validates: Requirements 8.1**
    - **Property 13: 기본값 리셋 라운드트립** — Reset to Defaults 후 모든 임계치가 시스템 기본값과 동일한지 검증
    - **Validates: Requirements 8.6**

  - [x] 7.7 커스텀 메트릭 추가 기능 구현
    - `components/resources/CustomMetricForm.tsx` (Client) — 커스텀 메트릭 추가 폼
    - "Add Custom Metric" 클릭 시 `GET /api/resources/{id}/metrics` 호출하여 사용 가능한 메트릭 목록 fetch
    - 자동완성 드롭다운: `"{metric_name} ({namespace})"` 형식 표시
    - 메트릭 선택 시 CloudWatch 존재 여부에 따라 초록색(found) 또는 앰버색(not found) 검증 표시기
    - 제출 시 알람 설정 테이블에 unsaved change로 추가
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ]* 7.8 커스텀 메트릭 속성 테스트 작성
    - **Property 14: 커스텀 메트릭 표시 형식** — 자동완성 표시 텍스트가 `"{metric_name} ({namespace})"` 형식인지 검증
    - **Validates: Requirements 9.2**
    - **Property 15: 커스텀 메트릭 검증 표시기** — 존재하면 초록색, 미존재하면 앰버색 표시기 렌더링 검증
    - **Validates: Requirements 9.4, 9.5**

- [x] 8. Checkpoint — Phase 4 완료 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Phase 5 — Alarms + Settings (Req 10, 11, 12, 13)
  - [x] 9.1 Alarms Server Component 리팩터링
    - `app/alarms/page.tsx` — Server Component로 전환, `fetchAlarms(searchParams)` + `fetchAlarmSummary()` 호출
    - `components/alarms/AlarmsContent.tsx` (Client) — 필터 탭 (ALL/ALARM/INSUFFICIENT/OK/OFF), 검색
    - `components/alarms/AlarmSummaryCards.tsx` — 상태별 카운트 카드 (Total, ALARM, OK, INSUFFICIENT)
    - `components/alarms/AlarmTable.tsx` (Client) — 테이블 + 서버사이드 페이지네이션
    - 필터/검색 변경 시 URL searchParams 업데이트 → Server Component 재실행
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x] 9.2 Alarms loading.tsx + error.tsx 구현
    - `app/alarms/loading.tsx` — 요약 카드 스켈레톤 + 테이블 스켈레톤
    - `app/alarms/error.tsx` — ErrorPanel + `reset()` 재시도
    - _Requirements: 10.5, 15.1, 15.2_

  - [x] 9.3 Alarms CSV 내보내기 연동
    - "Export Report" 버튼 → `GET /api/alarms/export` (현재 필터 + state 파라미터 포함)
    - 파일명: `alarms_{YYYY-MM-DD}.csv`
    - 내보내기 중 버튼 로딩 표시
    - _Requirements: 17.2, 17.3, 17.4_

  - [x] 9.4 Settings 고객사 CRUD 구현
    - `app/settings/page.tsx` — Server Component로 전환, `fetchCustomers()` + `fetchAccounts()` 호출
    - `components/settings/CustomerSection.tsx` (Client) — 고객사 목록 표시 + 등록 폼
    - 등록 폼 제출 시 `POST /api/customers` 호출
    - 성공 시 Toast + 목록 재페칭, 실패 시 인라인 에러 메시지
    - 삭제 시 ConfirmDialog 표시 후 `DELETE /api/customers/{id}` 호출
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

  - [x] 9.5 Settings 어카운트 CRUD 구현
    - `components/settings/AccountSection.tsx` (Client) — 어카운트 목록 + 등록 폼 + 연결 테스트
    - 등록 폼 제출 시 `POST /api/accounts` 호출 (account_id, role_arn, name, customer_id)
    - 성공 시 Toast + 목록 재페칭, 실패 시 인라인 에러 메시지
    - "Test Connection" 클릭 시 `POST /api/accounts/{id}/test` 호출
    - 테스트 진행 중 버튼 스피너, 결과를 status 컬럼에 반영 (connected/failed)
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [x] 9.6 Settings 임계치 오버라이드 구현
    - `components/settings/ThresholdSection.tsx` (Client) — 리소스 유형 탭 + 임계치 편집 테이블
    - 수평 스크롤 가능한 리소스 유형 탭 (30개 타입)
    - 탭 선택 시 `GET /api/thresholds/{type}` 호출하여 메트릭 임계치 테이블 표시
    - 시스템 기본값 + 고객사 오버라이드 값 표시, 활성 레벨 시각적 표시기
    - 오버라이드 수정 후 저장 시 `PUT /api/thresholds/{type}` 호출
    - 성공 시 Toast 표시
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

  - [ ]* 9.7 임계치 계층 속성 테스트 작성
    - **Property 21: 임계치 계층 활성 레벨 표시** — 고객사 오버라이드 존재 시 "Customer" 레벨 활성, 미존재 시 "System" 레벨 활성 표시 검증
    - **Validates: Requirements 13.4**

  - [x] 9.8 Settings loading.tsx + error.tsx 구현
    - `app/settings/loading.tsx` — 고객사/어카운트 섹션 스켈레톤
    - `app/settings/error.tsx` — ErrorPanel + `reset()` 재시도
    - _Requirements: 15.1, 15.2_

- [x] 10. Final Checkpoint — 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.
  - `npx tsc --noEmit` 타입 에러 0개 확인

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- 각 Phase는 이전 Phase의 결과물에 의존하므로 순서대로 진행
- 백엔드 API가 준비되면 Mock Route Handler를 실제 API URL로 교체 (환경 변수 `NEXT_PUBLIC_API_BASE_URL` 변경)
- Property 테스트는 fast-check 라이브러리 사용 (이미 devDependencies에 설치됨)
- TDD 사이클 (Red → Green → Refactor) 준수, 테스트 설명은 한국어로 작성
- 파일 200줄 제한 준수 — 초과 시 역할별 분리
