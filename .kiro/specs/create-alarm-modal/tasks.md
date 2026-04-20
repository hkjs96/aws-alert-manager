# Implementation Plan: Create Alarm Modal

## Overview

Dashboard의 "Create Alarm" 버튼으로 열리는 멀티스텝 모달을 구현한다. 순수 함수 유틸리티 → 서브 컴포넌트(TrackSelector, ResourceFilterStep, MetricConfigStep) → 컨테이너(CreateAlarmModal) → DashboardContent 연동 순서로 점진적으로 구축한다. TDD 사이클을 따르며 파일 200줄 제한을 준수한다.

## Tasks

- [x] 1. 순수 함수 유틸리티 구현 (`frontend/lib/alarm-modal-utils.ts`)
  - [x] 1.1 `filterAccounts`, `filterResources`, `isSubmitEnabled` 순수 함수 구현
    - `filterAccounts(accounts, customerId)` — customer_id 일치 어카운트 필터링
    - `filterResources(resources, accountId, track)` — account 일치 + 트랙별 monitoring 필터링 (트랙 1: monitoring=true, 트랙 2: monitoring=false)
    - `isSubmitEnabled(track, metrics, customMetrics)` — 트랙 1: customMetrics ≥ 1, 트랙 2: enabled metrics ≥ 1 또는 customMetrics ≥ 1
    - _Requirements: 3.2, 3.4, 3.5, 7.1, 7.2, 8.1, 8.2_

  - [ ]* 1.2 `filterAccounts` 속성 테스트 작성
    - **Property 4: 어카운트 필터링 정확성** — 임의의 customer_id에 대해 반환된 모든 어카운트의 customer_id가 일치하고, 해당 customer_id를 가진 모든 어카운트가 빠짐없이 포함되는지 검증
    - **Validates: Requirements 3.2**

  - [ ]* 1.3 `filterResources` 속성 테스트 작성
    - **Property 5: 트랙별 리소스 필터링 정확성** — 임의의 (track, accountId)에 대해 반환된 리소스가 account 일치 + 트랙별 monitoring 조건을 만족하고, 조건을 만족하는 모든 리소스가 빠짐없이 포함되는지 검증
    - **Validates: Requirements 3.4, 3.5**

  - [ ]* 1.4 `isSubmitEnabled` 속성 테스트 작성
    - **Property 9: Submit 버튼 활성화 조건 정합성** — 임의의 (track, metrics enabled 상태, customMetrics 개수)에 대해 활성화 여부가 설계 문서의 조건과 동치인지 검증
    - **Validates: Requirements 7.1, 7.2, 8.1, 8.2**

  - [ ]* 1.5 순수 함수 단위 테스트 작성 (`__tests__/lib/alarm-modal-utils.test.ts`)
    - filterAccounts: 빈 배열, 일치하는 어카운트, 일치하지 않는 customer_id
    - filterResources: 트랙 1 monitoring=true만, 트랙 2 monitoring=false만, 빈 결과
    - isSubmitEnabled: 트랙 1 커스텀 메트릭 0개/1개, 트랙 2 기본 메트릭 전체 비활성화 + 커스텀 0개/1개
    - _Requirements: 3.2, 3.4, 3.5, 7.1, 7.2, 8.1, 8.2_

- [x] 2. Checkpoint — 순수 함수 유틸리티 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. TrackSelector 컴포넌트 구현 (`frontend/components/dashboard/create-alarm/TrackSelector.tsx`)
  - [x] 3.1 TrackSelector UI 구현
    - "커스텀 알람 추가" (트랙 1)와 "새 모니터링 설정" (트랙 2) 두 개의 선택 카드 렌더링
    - 선택 상태 시각적 피드백 (border highlight, 배경색 변경)
    - 카드 클릭 시 `onSelectTrack` 콜백 호출
    - `data-testid` 속성 추가 (track-card-1, track-card-2)
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ]* 3.2 TrackSelector 단위 테스트 작성
    - 두 카드 렌더링 확인, 클릭 시 onSelectTrack 호출 확인, 선택 상태 스타일 확인
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 4. ResourceFilterStep 컴포넌트 구현 (`frontend/components/dashboard/create-alarm/ResourceFilterStep.tsx`)
  - [x] 4.1 ResourceFilterStep UI 구현
    - 고객사 → 어카운트 → 리소스 3단 캐스케이딩 드롭다운
    - `filterAccounts`, `filterResources` 순수 함수 사용하여 옵션 필터링
    - 트랙별 monitoring 필터 적용 (트랙 1: monitoring=true, 트랙 2: monitoring=false)
    - 빈 상태 메시지 표시: "모니터링 중인 리소스가 없습니다" / "미모니터링 리소스가 없습니다" / "어카운트가 없습니다"
    - MOCK_CUSTOMERS, MOCK_ACCOUNTS, MOCK_RESOURCES에서 데이터 import
    - `data-testid` 속성 추가 (customer-select, account-select, resource-select)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 9.1, 9.2, 9.3_

  - [ ]* 4.2 ResourceFilterStep 단위 테스트 작성
    - 고객사 목록 렌더링, 어카운트 캐스케이딩 필터, 트랙별 리소스 필터, 빈 상태 메시지 표시
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 9.1, 9.2, 9.3_

- [x] 5. MetricConfigStep 컴포넌트 구현 (`frontend/components/dashboard/create-alarm/MetricConfigStep.tsx`)
  - [x] 5.1 MetricConfigStep UI 구현
    - 트랙 1: AVAILABLE_CW_METRICS 드롭다운 + 임계치/단위/방향 입력만 표시 (기본 메트릭 테이블 숨김)
    - 트랙 2: MetricConfigSection 재사용 (기본 메트릭 테이블 + 커스텀 메트릭 추가)
    - 리소스 타입에 AVAILABLE_CW_METRICS가 비어있으면 안내 메시지 표시
    - `addCustomFromDropdown` 핸들러 구현 (커스텀 메트릭 추가 로직)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 9.4_

  - [ ]* 5.2 MetricConfigStep 단위 테스트 작성
    - 트랙 1: 커스텀 메트릭 드롭다운만 표시, 기본 메트릭 테이블 미표시
    - 트랙 2: MetricConfigSection 렌더링, 기본 메트릭 + 커스텀 메트릭 영역 표시
    - 빈 메트릭 안내 메시지 표시
    - _Requirements: 4.1, 4.5, 5.1, 9.4_

- [x] 6. Checkpoint — 서브 컴포넌트 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. CreateAlarmModal 컨테이너 구현
  - [x] 7.1 InfoBanner + ModalFooter 구현 (`frontend/components/dashboard/create-alarm/InfoBanner.tsx`, `ModalFooter.tsx`)
    - InfoBanner: 정보성 아이콘 + SNS 토픽 안내 메시지 배너
    - ModalFooter: Cancel + Create Alarm 버튼, LoadingButton 재사용, isSubmitDisabled 연동
    - _Requirements: 6.1, 6.2, 7.3, 7.6, 8.3, 8.6_

  - [x] 7.2 CreateAlarmModal 컨테이너 구현 (`frontend/components/dashboard/create-alarm/CreateAlarmModal.tsx`)
    - 오버레이 + 모달 컨테이너 렌더링
    - step에 따른 서브 컴포넌트 조건부 렌더링 (track-select → resource-filter → metric-config)
    - 전체 상태 관리: step, track, customerId, accountId, resourceId, metrics, customMetrics, isSubmitting
    - 트랙 변경 시 하위 상태 전체 초기화
    - 고객사 변경 시 accountId + resourceId 초기화, 어카운트 변경 시 resourceId 초기화
    - 닫기(X) / Cancel 시 `resetState()` 호출하여 전체 상태 초기화
    - Create Alarm 클릭 시 mock API 호출 (setTimeout 시뮬레이션) + Toast 표시
    - `isSubmitEnabled` 순수 함수로 submit 버튼 활성화 판단
    - `data-testid` 속성 추가 (create-alarm-modal, close-button)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.4, 3.3, 3.6, 7.3, 7.4, 7.5, 7.6, 8.3, 8.4, 8.5, 8.6_

  - [ ]* 7.3 CreateAlarmModal 단위 테스트 작성
    - 모달 열기/닫기, X 버튼 클릭 시 상태 초기화, Cancel 클릭 시 상태 초기화
    - 트랙 선택 후 ResourceFilterStep 표시, 리소스 선택 후 MetricConfigStep 표시
    - API 호출 성공 시 Toast + 모달 닫기, 실패 시 Toast + 모달 유지
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 7.4, 7.5, 8.4, 8.5_

  - [ ]* 7.4 캐스케이딩 초기화 속성 테스트 작성
    - **Property 3: 캐스케이딩 초기화** — 임의의 필터 상태에서 상위 드롭다운 변경 시 하위 선택값이 모두 초기화되는지 검증
    - **Validates: Requirements 3.3, 3.6**

  - [ ]* 7.5 모달 재오픈 초기 상태 속성 테스트 작성
    - **Property 1: 모달 재오픈 시 초기 상태 복원** — 임의의 ModalState에서 모달 닫고 다시 열면 초기 상태로 복원되는지 검증
    - **Validates: Requirements 1.4**

  - [ ]* 7.6 트랙 변경 시 하위 상태 초기화 속성 테스트 작성
    - **Property 2: 트랙 변경 시 하위 상태 전체 초기화** — 임의의 하위 상태에서 트랙 변경 시 모든 하위 상태가 초기값으로 리셋되는지 검증
    - **Validates: Requirements 2.4**

- [x] 8. Checkpoint — CreateAlarmModal 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. DashboardContent 연동
  - [x] 9.1 DashboardContent에 모달 open 연결
    - `DashboardContent`에 `useState<boolean>` 추가하여 모달 open/close 관리
    - "Create Alarm" 버튼 onClick에 `setIsModalOpen(true)` 연결
    - `<CreateAlarmModal open={isModalOpen} onClose={() => setIsModalOpen(false)} />` 렌더링
    - _Requirements: 1.1_

  - [ ]* 9.2 DashboardContent 연동 테스트 작성
    - "Create Alarm" 버튼 클릭 시 모달 표시 확인
    - _Requirements: 1.1_

- [x] 10. Final Checkpoint — 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.
  - `npx tsc --noEmit` 타입 에러 0개 확인

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- 각 태스크는 이전 태스크의 결과물에 의존하므로 순서대로 진행
- 순수 함수(alarm-modal-utils.ts)를 먼저 구현하여 Property-Based 테스트를 React 렌더링 없이 실행 가능
- Property 테스트는 fast-check 라이브러리 사용
- TDD 사이클 (Red → Green → Refactor) 준수, 테스트 설명은 한국어로 작성
- 파일 200줄 제한 준수 — 초과 시 역할별 분리
- 기존 MetricConfigSection, LoadingButton, Toast 컴포넌트 재사용
